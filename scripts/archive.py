#!/usr/bin/env python3
"""
Build a versioned zip archive of adnacom_monitor_sdk via `git archive`.

Equivalent to:

    git archive --format=zip --prefix=adnacom_monitor_sdk/ \\
        -o ../adnacom-monitor-sdk-<version>.zip HEAD

but reads <version> from adnacom_monitor/_version.py so the filename always
matches the package version.

    python3 scripts/archive.py
    python3 scripts/archive.py --ref v1.1.1 --output /tmp/out.zip
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = REPO_ROOT / "adnacom_monitor" / "_version.py"


def read_version() -> str:
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', VERSION_FILE.read_text())
    if not match:
        sys.exit(f"ERROR: could not find __version__ in {VERSION_FILE}")
    return match.group(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="git ref to archive (default: HEAD)")
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="output zip path (default: ../adnacom-monitor-sdk-<version>.zip)",
    )
    args = parser.parse_args()

    version = read_version()
    output = Path(args.output) if args.output else REPO_ROOT.parent / f"adnacom-monitor-sdk-{version}.zip"

    cmd = [
        "git", "archive",
        "--format=zip",
        "--prefix=adnacom_monitor_sdk/",
        f"-o{output}",
        args.ref,
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    if result.returncode != 0:
        sys.exit("ERROR: git archive failed (see output above).")

    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
