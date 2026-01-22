#!/usr/bin/env python3
"""Check for AIA V9 response/emissivity files and download if missing."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from urllib.request import urlopen, urlretrieve


BASE_URL = "https://hesperia.gsfc.nasa.gov/ssw/sdo/aia/response/"
FILES = [
    "aia_V9_all_fullinst.genx",
    "aia_V9_fullemiss.genx",
    "aia_V9_chiantifix.genx",
    "aia_V9_20200706_215452_response_table.txt",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch AIA V9 response/emissivity files from SSW mirror.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--dest",
        default=str(Path(__file__).resolve().parent / "response_data"),
        help="Destination directory for downloads.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Download even if the file already exists.",
    )
    return p.parse_args()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    args = parse_args()
    dest = Path(args.dest).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)

    missing = []
    for name in FILES:
        path = dest / name
        if path.exists() and not args.force:
            print(f"OK: {path}")
            continue
        missing.append(name)

    if not missing:
        print("All required files are present.")
        return 0

    print("Downloading missing files...")
    for name in missing:
        url = BASE_URL + name
        path = dest / name
        print(f"GET {url}")
        urlretrieve(url, path)
        print(f"Saved {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
