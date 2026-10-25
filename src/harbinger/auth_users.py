"""Offline account provisioning: python -m harbinger.auth_users FILE USER --role operator --site S01."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import tempfile
from pathlib import Path

from harbinger.api.auth import AuthManager, password_hash
from harbinger.config import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("username")
    parser.add_argument("--role", required=True, choices=("admin", "viewer", "operator"))
    parser.add_argument("--site", action="append", default=[])
    args = parser.parse_args()
    password = getpass.getpass("Password (12–256 characters): ")
    if password != getpass.getpass("Confirm password: "):
        parser.error("Passwords do not match")
    try:
        hashed = password_hash(password)
        existing = json.loads(args.file.read_text()) if args.file.exists() else []
        records = [r for r in existing if r["username"] != args.username]
        records.append(
            {"username": args.username, "role": args.role, "sites": args.site, "password_hash": hashed}
        )
        args.file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".accounts-", dir=args.file.parent)
        try:
            with os.fdopen(fd, "w") as file:
                json.dump(records, file, indent=2)
                file.flush()
                os.fsync(file.fileno())
            AuthManager(
                Settings(protected_mode=True, auth_users_file=Path(tmp), auth_origin="https://localhost")
            )
            os.replace(tmp, args.file)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    except (ValueError, OSError, RuntimeError, KeyError, TypeError):
        parser.error("Invalid account configuration; file was not changed")
    print("Account file saved with mode 0600. Restart the service to apply account changes.")


if __name__ == "__main__":
    main()
