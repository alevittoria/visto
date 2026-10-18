"""Behavioral checks for the repository companion-file checker."""

import importlib.util
from pathlib import Path
import shutil
import unittest
import uuid


SCRIPT = Path(__file__).resolve().parents[1] / "check_project.py"
spec = importlib.util.spec_from_file_location("check_project", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class ProjectChecks(unittest.TestCase):
    def setUp(self):
        # Stay inside the writable workspace; Windows sandbox ACLs reject the
        # permission mode used by tempfile.TemporaryDirectory on this host.
        self.fixture_parent = SCRIPT.parent.resolve()
        self.root = (self.fixture_parent / (".test-fixture-" + uuid.uuid4().hex)).resolve()
        self.assertNotEqual(self.root, self.fixture_parent)
        self.assertTrue(self.root.is_relative_to(self.fixture_parent))
        self.root.mkdir()
        self.addCleanup(self.remove_fixture)

    def remove_fixture(self):
        target = self.root.resolve()
        self.assertNotEqual(target, self.fixture_parent)
        self.assertTrue(target.is_relative_to(self.fixture_parent))
        shutil.rmtree(target)

    def write(self, path, text="placeholder\n"):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def test_missing_required_file_is_reported(self):
        self.assertIn("missing required file: AGENTS.md", checker.check_required(self.root))

    def test_broken_local_link_is_reported(self):
        self.write("README.md", "[missing](docs/missing.md)\n")
        self.assertTrue(any("docs/missing.md" in e for e in checker.check_links(self.root)))

    def test_links_ignore_fences_external_urls_and_anchors(self):
        self.write("README.md", "[web](https://example.test/a) [mail](mailto:a@b.test) [here](#a)\n```md\n[example](missing.md)\n```\n")
        self.assertEqual([], checker.check_links(self.root))

    def test_reference_and_image_links_are_checked(self):
        self.write("README.md", "![image](missing.png)\n[ref][other]\n[other]: gone.md\n")
        errors = checker.check_links(self.root)
        self.assertEqual(2, len(errors))

    def test_local_link_cannot_escape_repository(self):
        self.write("README.md", "[outside](../outside.md)\n")
        self.assertTrue(any("outside repository" in e for e in checker.check_links(self.root)))

    def test_existing_link_with_encoded_space_and_anchor_is_valid(self):
        self.write("docs/a b.md")
        self.write("README.md", "[ok](docs/a%20b.md#section)\n")
        self.assertEqual([], checker.check_links(self.root))

    def test_generated_and_dependency_markdown_is_not_checked(self):
        for directory in (
            ".work", ".venv", "node_modules", "dist", ".pytest_cache",
            ".ruff_cache", ".git", "vendor", "__pycache__",
        ):
            with self.subTest(directory=directory):
                self.write(f"frontend/{directory}/nested/README.md", "[external](missing.md)\n")
        self.write("docs/authored.md", "[broken](missing-authored.md)\n")

        errors = checker.check_links(self.root)

        self.assertEqual(1, len(errors), errors)
        self.assertIn("missing-authored.md", errors[0])

    def test_invalid_toml_is_reported(self):
        self.write("agents/codex/backend.toml", "name = [\n")
        self.assertTrue(any("invalid TOML" in e for e in checker.check_roles(self.root)))


if __name__ == "__main__":
    unittest.main()
