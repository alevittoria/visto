"""Behavioral checks for the release build, wheel checker and release workflow."""

import contextlib
import importlib.util
import io
from pathlib import Path
import re
import shutil
import unittest
import uuid
import zipfile


SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_wheel = load("check_wheel")
build_release = load("build_release")

COMPLETE = {
    "visto/__init__.py": "",
    "visto/console/index.html": "<!doctype html>",
    "visto/console/assets/index-0a1b2c.js": "console.log(1)",
    "visto/toolchain/components.json": "{}",
    "visto/toolchain/android-sdk-license.txt": "terms",
    "visto/toolchain/appium/default/package.json": "{}",
    "visto/toolchain/appium/default/pnpm-lock.yaml": "lockfileVersion: '9.0'",
    "visto/toolchain/appium/macos/package.json": "{}",
    "visto/toolchain/appium/macos/pnpm-lock.yaml": "lockfileVersion: '9.0'",
    "visto/prompts/agent-core.md": "# core",
    "visto-0.1.0.dist-info/entry_points.txt": "[console_scripts]\nvisto = visto.cli:entry\n",
}


def make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in entries.items():
            archive.writestr(name, text)
    return path


class WorkspaceFixture(unittest.TestCase):
    def setUp(self):
        # Stay inside the writable workspace: some sandboxed Windows hosts reject the
        # permission mode used by tempfile.TemporaryDirectory.
        self.root = (SCRIPTS / (".test-fixture-" + uuid.uuid4().hex)).resolve()
        self.assertTrue(self.root.is_relative_to(SCRIPTS))
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)


class CheckWheel(WorkspaceFixture):
    def test_check_wheel_reports_missing(self):
        wheel = make_zip(self.root / "visto-0.1.0-py3-none-any.whl", {"visto/__init__.py": ""})
        missing = check_wheel.missing_entries(wheel)
        self.assertIn("visto/console/index.html", missing)
        self.assertIn("visto/toolchain/appium/macos/pnpm-lock.yaml", missing)
        self.assertTrue(any("visto = visto.cli:entry" in entry for entry in missing))

    def test_check_wheel_requires_console_assets_and_appium_manifests(self):
        for absent in (
            "visto/console/assets/index-0a1b2c.js",
            "visto/toolchain/appium/default/package.json",
            "visto/toolchain/appium/macos/package.json",
        ):
            entries = {name: text for name, text in COMPLETE.items() if name != absent}
            wheel = make_zip(self.root / "partial.whl", entries)
            missing = check_wheel.missing_entries(wheel)
            self.assertEqual(1, len(missing), absent)
            self.assertIn(absent.rsplit("/", 1)[0] if "assets" in absent else absent, missing[0])

    def test_check_wheel_accepts_complete(self):
        wheel = make_zip(self.root / "visto-0.1.0-py3-none-any.whl", COMPLETE)
        self.assertEqual([], check_wheel.missing_entries(wheel))

    def test_entry_point_must_name_the_cli_entry(self):
        entries = {**COMPLETE, "visto-0.1.0.dist-info/entry_points.txt": "[console_scripts]\nvisto = visto.cli:main\n"}
        wheel = make_zip(self.root / "visto-0.1.0-py3-none-any.whl", entries)
        self.assertEqual(1, len(check_wheel.missing_entries(wheel)))

    def test_main_exit_codes(self):
        complete = make_zip(self.root / "complete.whl", COMPLETE)
        partial = make_zip(self.root / "partial.whl", {"visto/__init__.py": ""})
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.assertEqual(0, check_wheel.main([str(complete)]))
            self.assertEqual(1, check_wheel.main([str(partial)]))
            self.assertEqual(1, check_wheel.main([str(self.root / "absent.whl")]))
        self.assertIn("missing: visto/console/index.html", output.getvalue())


class CleanCopy(WorkspaceFixture):
    def test_copy_tree_removes_stale_files(self):
        source = self.root / "dist"
        (source / "assets").mkdir(parents=True)
        (source / "index.html").write_text("new", encoding="utf-8")
        (source / "assets" / "app-new.js").write_text("new", encoding="utf-8")
        target = self.root / "console"
        (target / "assets").mkdir(parents=True)
        (target / "assets" / "app-old.js").write_text("old", encoding="utf-8")

        build_release.copy_tree(source, target)

        self.assertEqual(
            {"index.html", "assets/app-new.js"},
            {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()},
        )

    def test_copy_files_copies_only_the_named_files(self):
        source = self.root / "appium"
        source.mkdir()
        for name in ("package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"):
            (source / name).write_text(name, encoding="utf-8")
        target = self.root / "packaged" / "default"
        target.mkdir(parents=True)
        (target / "stale.txt").write_text("old", encoding="utf-8")

        build_release.copy_files(source, ("package.json", "pnpm-lock.yaml"), target)

        self.assertEqual({"package.json", "pnpm-lock.yaml"}, {p.name for p in target.iterdir()})

    def test_copy_files_reports_a_missing_source(self):
        (self.root / "appium").mkdir()
        with self.assertRaises(FileNotFoundError):
            build_release.copy_files(self.root / "appium", ("package.json",), self.root / "out")


class ReleaseWorkflow(unittest.TestCase):
    """Stdlib-only sanity checks; the workflow itself only runs on GitHub."""

    def setUp(self):
        self.text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    def test_every_action_is_pinned_by_commit_sha_with_a_version_comment(self):
        uses = re.findall(r"uses:\s*(\S+)(.*)", self.text)
        self.assertTrue(uses)
        for action, comment in uses:
            self.assertRegex(action, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")
            self.assertRegex(comment, r"#\s*v\d+")

    def test_runs_only_on_version_tags_with_write_contents(self):
        self.assertRegex(self.text, r"(?m)^on:\n  push:\n    tags:\n      - ['\"]?v\*['\"]?$")
        self.assertRegex(self.text, r"(?m)^permissions:\n  contents: write$")
        self.assertNotIn("git push", self.text)
        self.assertNotIn("branches", self.text)

    def test_uses_tabs_nowhere(self):
        self.assertNotIn("\t", self.text)


if __name__ == "__main__":
    unittest.main()
