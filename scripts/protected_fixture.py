"""Create disposable local verification accounts; never prints passwords or cookie tokens."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import tempfile
from pathlib import Path

from harbinger.api.auth import password_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", action="append", required=True, help="Pass two distinct existing site IDs")
    args = parser.parse_args()
    if len(args.site) != 2 or len(set(args.site)) != 2:
        parser.error("Exactly two distinct --site values are required")
    directory = Path(tempfile.mkdtemp(prefix="harbinger-protected-"))
    records, credentials = [], []
    for number, role in enumerate(("operator", "operator", "viewer", "admin")):
        username = "verify-" + secrets.token_hex(6)
        password = secrets.token_urlsafe(24)
        sites = [] if role == "admin" else [args.site[1 if number == 1 else 0]]
        credentials.append({"username": username, "password": password, "role": role, "sites": sites})
        records.append(
            {"username": username, "password_hash": password_hash(password), "role": role, "sites": sites}
        )
    for name, rows in (("users.json", records), ("credentials.json", credentials)):
        fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(rows, output)
    print(directory)


if __name__ == "__main__":
    main()
