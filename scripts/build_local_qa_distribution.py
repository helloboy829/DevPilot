"""Build an offline Python 3.12 QA distribution from trusted source and wheels.

No download, installation, dataset export, platform authority or target call.
All supplied files/parents and the selected repository must be operator-trusted.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import stat
import sys
import tomllib
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

_GRAPH = {
    "httpx": {"anyio", "certifi", "httpcore", "idna"},
    "httpcore": {"certifi", "h11"},
    "anyio": {"idna", "typing-extensions"},
    "openpyxl": {"et-xmlfile"},
    "h11": set(),
    "certifi": set(),
    "idna": set(),
    "typing-extensions": set(),
    "et-xmlfile": set(),
}
_LIMIT = 4 * 1024 * 1024
_ERROR = "Invalid local QA distribution source or artifact"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_regular(file, limit=_LIMIT, *, allow_empty=False):
    file = Path(file)
    if file.is_symlink():
        raise ValueError(_ERROR)
    descriptor = os.open(file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not (0 if allow_empty else 1) <= info.st_size <= limit:
            raise ValueError(_ERROR)
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(_ERROR)
    return data


def dependency_artifacts(root):
    """Fail on closure/marker drift instead of silently resolving a new graph."""
    raw = read_regular(root / "backend/uv.lock")
    packages = tomllib.loads(raw.decode())["package"]
    selected = {}
    for name, dependencies in _GRAPH.items():
        matches = [item for item in packages if item["name"] == name]
        if len(matches) != 1:
            raise ValueError(_ERROR)
        item = matches[0]
        if item["source"] != {"registry": "https://pypi.org/simple"}:
            raise ValueError(_ERROR)
        rows = item.get("dependencies", [])
        expected = [{"name": child, **({"marker": "python_full_version < '3.13'"} if child == "typing-extensions" else {})} for child in sorted(dependencies)]
        if sorted(rows, key=lambda row: row["name"]) != expected:
            raise ValueError(_ERROR)
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", item["version"]) or len(item["wheels"]) != 1:
            raise ValueError(_ERROR)
        artifact = item["wheels"][0]
        url = urlsplit(artifact["url"])
        filename = PurePosixPath(url.path).name
        prefix = name.replace("-", "_") + "-" + item["version"]
        if (
            url.scheme != "https"
            or url.netloc != "files.pythonhosted.org"
            or url.query
            or url.fragment
            or filename not in {prefix + "-py3-none-any.whl", prefix + "-py2.py3-none-any.whl"}
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["hash"])
            or type(artifact["size"]) is not int
            or not 0 < artifact["size"] < _LIMIT
        ):
            raise ValueError(_ERROR)
        selected[name] = {"version": item["version"], "filename": filename, "sha256": artifact["hash"][7:], "size": artifact["size"], "url": artifact["url"]}
    return raw, selected


def dependency_requirements(artifacts):
    return "".join(f"{name}=={item['version']} --hash=sha256:{item['sha256']}\n" for name, item in sorted(artifacts.items()))


def archive_entries(data):
    """Read bounded regular, canonical POSIX names, never extract anything."""
    result = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if not 0 < len(infos) <= 512 or sum(info.file_size for info in infos) > 16 * _LIMIT:
            raise ValueError(_ERROR)
        for info in infos:
            name = info.filename
            parts = PurePosixPath(name).parts
            mode = info.external_attr >> 16
            if (
                not parts
                or info.orig_filename != name
                or PurePosixPath(name).as_posix() != name
                or any(part in {".", ".."} or ":" in part for part in parts)
                or name.startswith("/")
                or "\\" in name
                or "\x00" in name
                or name in result
                or info.is_dir()
                or name.casefold() in {key.casefold() for key in result}
                or stat.S_IFMT(mode) not in {0, stat.S_IFREG}
                or info.flag_bits & 1
                or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                or info.file_size > _LIMIT
            ):
                raise ValueError(_ERROR)
            result[name] = archive.read(info)
    return result


def _headers(raw, allowed, many=()):
    if len(raw) > 16384:
        raise ValueError(_ERROR)
    message = BytesParser(policy=policy.default).parsebytes(raw)
    if message.defects or message.get_payload() or set(message.keys()) != set(allowed):
        raise ValueError(_ERROR)
    if any(len(message.get_all(key)) != 1 for key in allowed if key not in many):
        raise ValueError(_ERROR)
    return message


def source_members(root):
    names = read_regular(root / "devpilot/distribution/source-members.txt", 16384).decode("utf-8").splitlines()
    if not names or len(names) != len(set(names)) or names != sorted(names):
        raise ValueError(_ERROR)
    result = {}
    for name in names:
        if (
            not name.startswith("devpilot/")
            or PurePosixPath(name).as_posix() != name
            or any(part in {".", ".."} for part in PurePosixPath(name).parts)
            or not re.fullmatch(r"[A-Za-z0-9_./-]+", name)
            or Path(name).suffix not in {".py", ".md"}
        ):
            raise ValueError(_ERROR)
        result[name] = read_regular(root / "devpilot/src" / name, allow_empty=True)
    if "devpilot/local_qa_cli.py" not in result or "devpilot/local_qa_reconcile.py" not in result:
        raise ValueError(_ERROR)
    return result


def validate_first_party(root, file, data):
    project = tomllib.loads(read_regular(root / "devpilot/pyproject.toml").decode())["project"]
    if project["name"] != "devpilot" or project["dependencies"] != ["httpx", "openpyxl"] or project["requires-python"] != ">=3.12":
        raise ValueError(_ERROR)
    version = project["version"]
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version) or file.name != f"devpilot-{version}-py3-none-any.whl":
        raise ValueError(_ERROR)
    prefix = f"devpilot-{version}.dist-info/"
    files = archive_entries(data)
    sources = source_members(root)
    if set(files) != set(sources) | {prefix + name for name in ("METADATA", "WHEEL", "RECORD")}:
        raise ValueError(_ERROR)
    if any(files[name] != expected for name, expected in sources.items()):
        raise ValueError(_ERROR)
    metadata = _headers(files[prefix + "METADATA"], ("Metadata-Version", "Name", "Version", "Summary", "Requires-Python", "Requires-Dist"), ("Requires-Dist",))
    if (
        metadata["Metadata-Version"] not in {"2.1", "2.2", "2.3", "2.4", "2.5"}
        or metadata["Name"] != "devpilot"
        or metadata["Summary"] != project["description"]
        or metadata["Version"] != version
        or metadata["Requires-Python"] != ">=3.12"
        or sorted(metadata.get_all("Requires-Dist")) != ["httpx", "openpyxl"]
    ):
        raise ValueError(_ERROR)
    wheel = _headers(files[prefix + "WHEEL"], ("Wheel-Version", "Generator", "Root-Is-Purelib", "Tag"))
    if wheel["Wheel-Version"] != "1.0" or wheel["Root-Is-Purelib"] != "true" or wheel["Tag"] != "py3-none-any" or wheel["Generator"] != "hatchling 1.33.0":
        raise ValueError(_ERROR)
    rows = list(csv.reader(io.StringIO(files[prefix + "RECORD"].decode("utf-8"))))
    if len(rows) != len(files) or any(len(row) != 3 for row in rows) or len({row[0] for row in rows}) != len(rows):
        raise ValueError(_ERROR)
    for name, digest, size in rows:
        if name not in files:
            raise ValueError(_ERROR)
        if name == prefix + "RECORD":
            if digest or size:
                raise ValueError(_ERROR)
        else:
            expected = base64.urlsafe_b64encode(hashlib.sha256(files[name]).digest()).rstrip(b"=").decode()
            if digest != "sha256=" + expected or size != str(len(files[name])):
                raise ValueError(_ERROR)
    return version, {name: sha256(value) for name, value in sorted(sources.items())}


def build_distribution(root, wheelhouse, wheel, output, revision):
    """Validate everything before exclusive output creation. No repair/retry."""
    if sys.version_info[:2] != (3, 12) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError(_ERROR)
    root, wheelhouse, wheel, output = (Path(item) for item in (root, wheelhouse, wheel, output))
    raw_lock, artifacts = dependency_artifacts(root)
    if wheelhouse.is_symlink() or not wheelhouse.is_dir() or {item.name for item in wheelhouse.iterdir()} != {item["filename"] for item in artifacts.values()}:
        raise ValueError(_ERROR)
    wheel_bytes = read_regular(wheel)
    version, sources = validate_first_party(root, wheel, wheel_bytes)
    files = {"wheels/" + wheel.name: wheel_bytes}
    for item in artifacts.values():
        data = read_regular(wheelhouse / item["filename"])
        if len(data) != item["size"] or sha256(data) != item["sha256"]:
            raise ValueError(_ERROR)
        files["wheels/" + item["filename"]] = data
    requirements = dependency_requirements(artifacts) + f"devpilot=={version} --hash=sha256:{sha256(wheel_bytes)}\n"
    files["requirements.lock"] = requirements.encode()
    files["LICENSE"] = read_regular(root / "LICENSE")
    files["README.md"] = read_regular(root / "devpilot/distribution/README.md")
    for name in ("manifest.json", "values.json", "inputs.json"):
        files["examples/" + name] = read_regular(root / "devpilot/distribution/examples" / name)
    manifest = {
        "schema": "local-qa-distribution.v1",
        "scope": "software_only_not_platform_export",
        "python": "3.12",
        "declared_source_revision": revision,
        "source_revision_authenticated": False,
        "platform_provenance_verified": False,
        "execution_authorized": False,
        "backend_lock_sha256": sha256(raw_lock),
        "package_version": version,
        "source_members_sha256": sources,
        "dependencies": artifacts,
        "files": {name: {"sha256": sha256(value), "size": len(value)} for name, value in sorted(files.items())},
    }
    files["distribution.json"] = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    # A partial file is deliberately retained on uncertain I/O. Never overwrite.
    with output.open("xb") as stream:
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, value in sorted(files.items()):
                info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, value, compresslevel=9)
        stream.flush()
        os.fsync(stream.fileno())
    return {"schema": manifest["schema"], "sha256": sha256(read_regular(output, 16 * _LIMIT)), "file_count": len(files), "platform_provenance_verified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependency-lock", action="store_true", help="Print exact requirements from tracked backend lock; no download")
    parser.add_argument("--describe-dependencies", action="store_true", help="Print locked official wheel metadata; no download")
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-revision")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        if sys.version_info[:2] != (3, 12):
            raise ValueError(_ERROR)
        if args.dependency_lock or args.describe_dependencies:
            if args.dependency_lock and args.describe_dependencies or any((args.wheelhouse, args.wheel, args.output, args.source_revision)):
                raise ValueError(_ERROR)
            _, artifacts = dependency_artifacts(root)
            print(dependency_requirements(artifacts), end="") if args.dependency_lock else print(json.dumps(artifacts, sort_keys=True))
        else:
            if not all((args.wheelhouse, args.wheel, args.output, args.source_revision)):
                raise ValueError(_ERROR)
            print(json.dumps(build_distribution(root, args.wheelhouse, args.wheel, args.output, args.source_revision), sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, zipfile.BadZipFile, csv.Error):
        print(_ERROR + "; no download/install/send was attempted; preserve partial output and do not overwrite", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
