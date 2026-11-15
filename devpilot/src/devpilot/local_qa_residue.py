"""显式本地 QA 目录的已知残留清单：仅元数据，不读内容、不删除。

只检查固定文件名是否存在及其大小/修改时间；不发现其他文件、不打开任何
文件内容、不认证、不解密、不清理。明文副本和崩溃产物仍需独立人工处置。
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

_ERROR = "Invalid residue inventory request"
_NAMES = (
    "incomplete-output-disposal-complete.json",
    "incomplete-output-disposal-request.json",
    "observations.encrypted.jsonl",
    "observations.jsonl",
    "retention-receipt.json",
    "retention.lock",
    "run-receipt.json",
)


def _directory(value):
    path = Path(value).absolute()
    if path.is_symlink() or not path.is_dir():
        raise ValueError(_ERROR)
    info = path.stat()
    if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError(_ERROR)
    return path


def inventory_directory(directory, *, confirm_metadata_only_inventory):
    """Return presence/size/mtime for known names only; never read content."""
    if confirm_metadata_only_inventory is not True:
        raise ValueError(_ERROR)
    try:
        path = _directory(directory)
        entries = []
        for name in _NAMES:
            try:
                info = (path / name).lstat()
            except FileNotFoundError:
                entries.append(
                    {"name": name, "present": False, "size": None, "mtime_ms": None}
                )
                continue
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(_ERROR)
            entries.append(
                {
                    "name": name,
                    "present": True,
                    "size": info.st_size,
                    "mtime_ms": info.st_mtime_ns // 1_000_000,
                }
            )
        by_name = {entry["name"]: entry for entry in entries}
        return {
            "schema": "local-qa-directory-residue.v1",
            "scope": "metadata_only_known_names",
            "entries": entries,
            "plaintext_copy_present": by_name["observations.jsonl"]["present"],
            "encrypted_output_present": by_name["observations.encrypted.jsonl"][
                "present"
            ],
            "content_status": "not_inspected",
            "verdict": "NOT_EVALUATED",
            "automatic_cleanup": False,
            "approval": "not_approved",
        }
    except (OSError, ValueError, TypeError, AttributeError):
        raise ValueError(_ERROR) from None


def main(argv=None):
    """Explicit metadata-only directory inventory; never reads or deletes content."""

    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError(_ERROR)

    parser = Parser(
        description="Metadata-only inventory of known local QA residue names. No content, authentication, decryption or cleanup.",
        allow_abbrev=False,
    )
    operations = parser.add_subparsers(dest="operation", required=True)
    inspect = operations.add_parser("inventory", allow_abbrev=False)
    inspect.add_argument("--directory", required=True)
    inspect.add_argument(
        "--confirm-metadata-only-directory-inventory",
        action="store_true",
        required=True,
    )
    try:
        args = parser.parse_args(argv)
        result = inventory_directory(
            args.directory,
            confirm_metadata_only_inventory=args.confirm_metadata_only_directory_inventory,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except KeyboardInterrupt:
        print(_ERROR, file=sys.stderr)
        return 130
    except Exception:
        print(_ERROR, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
