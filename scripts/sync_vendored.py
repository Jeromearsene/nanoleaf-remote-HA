"""Keep the vendored copy of `hapble` inside the Home Assistant integration
in sync with the reference library at the repository root.

HACS only installs `custom_components/<domain>/`, so the integration cannot
import the top-level `hapble` package. The library is therefore vendored.
The root `hapble/` package stays the single source of truth.

    python scripts/sync_vendored.py           # copy root -> vendored
    python scripts/sync_vendored.py --check   # exit 1 if they differ (CI)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "hapble"
TARGET = ROOT / "custom_components" / "nanoleaf_remote" / "hapble"

# Modules the integration needs. `mqtt_bridge` and `pairing_store` are only
# used by the standalone CLI tools, so they are deliberately not vendored.
VENDORED_MODULES = (
    "__init__",
    "ble_session",
    "crypto_hap",
    "facemap",
    "pair_verify",
    "pairing",
    "pdu",
    "srp",
    "tlv8",
    "transport",
    "uuids",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="only verify, do not write"
    )
    args = parser.parse_args()

    drift: list[str] = []
    for name in VENDORED_MODULES:
        source = SOURCE / f"{name}.py"
        target = TARGET / f"{name}.py"
        expected = source.read_bytes()
        if not target.exists() or target.read_bytes() != expected:
            drift.append(target.relative_to(ROOT).as_posix())
            if not args.check:
                TARGET.mkdir(parents=True, exist_ok=True)
                target.write_bytes(expected)

    extra = sorted(
        p.name for p in TARGET.glob("*.py") if p.stem not in VENDORED_MODULES
    )
    if extra:
        print(f"Unexpected files in vendored package: {', '.join(extra)}")
        return 1

    if drift and args.check:
        print("Vendored hapble is out of date. Run: python scripts/sync_vendored.py")
        for path in drift:
            print(f"  differs: {path}")
        return 1
    if drift:
        print(f"Updated {len(drift)} file(s).")
    else:
        print("Vendored hapble is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
