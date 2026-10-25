"""WebDriverAgent signing values and the XCUITest capabilities derived from them."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IOSSigning:
    team_id: str = ""
    signing_id: str = ""
    wda_bundle_id: str = ""
    prebuilt_wda: bool = False
    wda_derived_data: str = ""

    def capabilities(self) -> dict[str, object]:
        """Capabilities for the configured values; empty values are omitted."""
        capabilities: dict[str, object] = {}
        # A run never builds WebDriverAgent; building and installing it is an operator
        # pre-step, and the operator declares it with this flag.
        if self.prebuilt_wda:
            capabilities["appium:usePrebuiltWDA"] = True
        # The driver opens WebDriverAgent by its resolved path, so Xcode's default
        # derived data for a build made through a symlinked path is not found.
        derived_data = self.wda_derived_data.strip()
        if derived_data:
            capabilities["appium:derivedDataPath"] = str(Path(derived_data).expanduser())
        for capability, value in (
            ("appium:xcodeOrgId", self.team_id),
            ("appium:xcodeSigningId", self.signing_id),
            ("appium:updatedWDABundleId", self.wda_bundle_id),
        ):
            if value.strip():
                capabilities[capability] = value.strip()
        return capabilities
