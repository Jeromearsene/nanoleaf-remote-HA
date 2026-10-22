"""Check that the version is the same everywhere it is declared.

python scripts/check_versions.py             # manifest == pyproject
python scripts/check_versions.py v0.1.0      # ... and == the given tag
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str]) -> int:
    manifest = json.loads(
        (ROOT / "custom_components/nanoleaf_remote/manifest.json").read_text()
    )["version"]
    match = re.search(
        r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M
    )
    pyproject = match.group(1) if match else None
    versions = {"manifest.json": manifest, "pyproject.toml": pyproject}
    if len(argv) > 1:
        versions["tag"] = argv[1].removeprefix("v")

    if len(set(versions.values())) != 1:
        print("Version mismatch:")
        for name, value in versions.items():
            print(f"  {name}: {value}")
        return 1
    print(f"Version {manifest} is consistent ({', '.join(versions)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
