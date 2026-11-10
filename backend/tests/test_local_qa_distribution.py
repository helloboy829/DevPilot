"""Strict software-only distribution, wholly synthetic artifacts, no network."""

import base64
import csv
import hashlib
import importlib.util
import io
import json
import os
import socket
import stat
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("local_qa_distribution_builder", ROOT / "scripts/build_local_qa_distribution.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def make_wheel(sources, *, metadata=None, wheel=None, extra=None):
    prefix = "devpilot-0.1.0.dist-info/"
    summary = builder.tomllib.loads((ROOT / "devpilot/pyproject.toml").read_text())["project"]["description"]
    files = {
        **sources,
        prefix + "METADATA": metadata or f"Metadata-Version: 2.5\nName: devpilot\nVersion: 0.1.0\nSummary: {summary}\nRequires-Python: >=3.12\nRequires-Dist: cryptography\nRequires-Dist: httpx\nRequires-Dist: openpyxl\n\n".encode(),
        prefix + "WHEEL": wheel or b"Wheel-Version: 1.0\nGenerator: hatchling 1.33.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n",
        **(extra or {}),
    }
    record = io.StringIO(newline="")
    rows = csv.writer(record, lineterminator="\n")
    for name, data in files.items():
        value = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        rows.writerow([name, "sha256=" + value, len(data)])
    rows.writerow([prefix + "RECORD", "", ""])
    files[prefix + "RECORD"] = record.getvalue().encode()
    return zip_bytes(files)


def zip_bytes(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return data.getvalue()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Real network forbidden")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, denied)


@pytest.fixture
def inputs(tmp_path):
    root = tmp_path / "source"
    (root / "backend").mkdir(parents=True)
    (root / "devpilot/src/devpilot").mkdir(parents=True)
    (root / "devpilot/distribution/examples").mkdir(parents=True)
    (root / "LICENSE").write_text("Synthetic license\n")
    (root / "devpilot/pyproject.toml").write_bytes((ROOT / "devpilot/pyproject.toml").read_bytes())
    (root / "devpilot/distribution/README.md").write_text("Synthetic offline instructions\n")
    for name in ("manifest", "values", "inputs"):
        (root / f"devpilot/distribution/examples/{name}.json").write_text('{"synthetic": true}\n')
    sources = {"devpilot/__init__.py": b"", "devpilot/local_qa_cli.py": b"# synthetic cli\n", "devpilot/local_qa_reconcile.py": b"# synthetic reconcile\n", "devpilot/another.py": b"# all members\n"}
    for name, data in sources.items():
        (root / "devpilot/src" / name).write_bytes(data)
    (root / "devpilot/distribution/source-members.txt").write_text("\n".join(sorted(sources)) + "\n")
    text = (ROOT / "backend/uv.lock").read_text()
    _, locked = builder.dependency_artifacts(ROOT)
    house = tmp_path / "wheels"
    house.mkdir()
    for name, item in locked.items():
        content = ("SYNTHETIC_WHEEL_" + name).encode()
        (house / item["filename"]).write_bytes(content)
        text = text.replace("sha256:" + item["sha256"], "sha256:" + digest(content)).replace("size = " + str(item["size"]) + ", upload-time", "size = " + str(len(content)) + ", upload-time")
    (root / "backend/uv.lock").write_text(text)
    wheel = tmp_path / "devpilot-0.1.0-py3-none-any.whl"
    wheel.write_bytes(make_wheel(sources))
    return {"root": root, "wheelhouse": house, "wheel": wheel, "output": tmp_path / "delivery.zip", "revision": "a" * 40}, sources


def test_real_tracked_closure_is_complete_and_exactly_pinned():
    raw, artifacts = builder.dependency_artifacts(ROOT)
    assert set(artifacts) == set(builder._GRAPH) and len(artifacts) == 12
    assert builder.sha256(raw) == digest((ROOT / "backend/uv.lock").read_bytes())
    requirements = builder.dependency_requirements(artifacts)
    assert len(requirements.splitlines()) == 12
    assert all("==" in line and " --hash=sha256:" in line for line in requirements.splitlines())
    assert not any(token in requirements for token in ("http:", "https:", ";", "--extra-index", ">="))


def test_all_members_hash_lock_not_source_authority_and_reproducible(inputs, tmp_path):
    args, sources = inputs
    result = builder.build_distribution(**args)
    data = args["output"].read_bytes()
    files = builder.archive_entries(data)
    manifest = json.loads(files.pop("distribution.json"))
    assert result == {"schema": "local-qa-distribution.v2", "sha256": digest(data), "file_count": 20, "platform_provenance_verified": False}
    assert manifest["scope"] == "software_only_not_platform_export" and manifest["python"] == "3.12"
    assert manifest["declared_source_revision"] == "a" * 40 and manifest["source_revision_authenticated"] is False
    assert manifest["platform_provenance_verified"] is manifest["execution_authorized"] is False
    assert manifest["source_members_sha256"] == {name: digest(value) for name, value in sources.items()}
    assert set(manifest["files"]) == set(files)
    for name, value in files.items():
        assert manifest["files"][name] == {"sha256": digest(value), "size": len(value)}
    assert len(files["requirements.lock"].splitlines()) == 13
    assert "LICENSE" in files and set(name for name in files if name.startswith("examples/")) == {"examples/manifest.json", "examples/values.json", "examples/inputs.json"}
    again = tmp_path / "second.zip"
    builder.build_distribution(**{**args, "output": again})
    assert again.read_bytes() == data
    with pytest.raises(FileExistsError):
        builder.build_distribution(**args)
    assert args["output"].read_bytes() == data


@pytest.mark.parametrize("change", ["missing", "extra", "tamper", "wrong-size", "symlink", "directory"])
def test_wheelhouse_rejects_every_unknown_or_uncertain_artifact(inputs, change):
    args, _ = inputs
    file = next(args["wheelhouse"].iterdir())
    if change == "missing":
        file.unlink()
    elif change == "extra":
        (file.parent / "unrequested.whl").write_bytes(b"extra")
    elif change == "tamper":
        file.write_bytes(file.read_bytes()[::-1])
    elif change == "wrong-size":
        file.write_bytes(file.read_bytes() + b"X")
    elif change == "symlink":
        target = file.with_suffix(".saved")
        file.rename(target)
        # Keep only the expected member in the dedicated wheelhouse.
        saved = file.parent.parent / "saved-wheel"
        target.rename(saved)
        file.symlink_to(saved)
    else:
        file.unlink()
        file.mkdir()
    with pytest.raises((ValueError, OSError)):
        builder.build_distribution(**args)
    assert not args["output"].exists()


@pytest.mark.parametrize("name", ["extra.py", "devpilot/injected.py", "evil.pth", "devpilot-0.1.0.dist-info/entry_points.txt", "../escape.py", "/absolute.py", "C:/escape.py", "devpilot\\escape.py"])
def test_first_party_whole_member_set_rejects_injection_even_valid_record(inputs, name):
    args, sources = inputs
    args["wheel"].write_bytes(make_wheel(sources, extra={name: b"raise RuntimeError('NEVER_EXECUTE')"}))
    with pytest.raises(ValueError):
        builder.build_distribution(**args)
    assert not args["output"].exists()


@pytest.mark.parametrize("change", ["untracked", "changed-non-core", "missing-core", "metadata-dependency", "metadata-summary", "metadata-script", "metadata-duplicate", "wheel-tag", "record-hash", "record-duplicate"])
def test_first_party_source_metadata_and_record_are_all_verified(inputs, change):
    args, sources = inputs
    files = builder.archive_entries(args["wheel"].read_bytes())
    prefix = "devpilot-0.1.0.dist-info/"
    if change == "untracked":
        (args["root"] / "devpilot/src/devpilot/untracked.py").write_text("# not part of selected source\n")
        sources["devpilot/untracked.py"] = b"# not part of selected source\n"
        args["wheel"].write_bytes(make_wheel(sources))
    elif change == "changed-non-core":
        sources["devpilot/another.py"] += b"raise RuntimeError('NEVER_EXECUTE')\n"
        args["wheel"].write_bytes(make_wheel(sources))
    elif change == "missing-core":
        del sources["devpilot/local_qa_cli.py"]
        args["wheel"].write_bytes(make_wheel(sources))
    else:
        if change == "metadata-dependency":
            files[prefix + "METADATA"] = files[prefix + "METADATA"].replace(b"Requires-Dist: httpx", b"Requires-Dist: httpx[unsafe]")
        elif change == "metadata-summary":
            files[prefix + "METADATA"] = files[prefix + "METADATA"].replace(b"Summary: ", b"Summary: ALTERED_DESCRIPTION ")
        elif change == "metadata-script":
            files[prefix + "METADATA"] = files[prefix + "METADATA"].replace(b"\n\n", b"\nEntry-Points: injected\n\n")
        elif change == "metadata-duplicate":
            files[prefix + "METADATA"] = files[prefix + "METADATA"].replace(b"Name: devpilot", b"Name: devpilot\nName: devpilot")
        elif change == "wheel-tag":
            files[prefix + "WHEEL"] = files[prefix + "WHEEL"].replace(b"py3-none-any", b"cp312-win_amd64")
        elif change == "record-hash":
            files[prefix + "RECORD"] = files[prefix + "RECORD"].replace(b"sha256=", b"sha512=", 1)
        else:
            files[prefix + "RECORD"] += files[prefix + "RECORD"].splitlines(keepends=True)[0]
        # Metadata tests carry consistent RECORDs, so metadata itself must fail.
        if change.startswith("metadata") or change == "wheel-tag":
            args["wheel"].write_bytes(make_wheel(sources, metadata=files[prefix + "METADATA"], wheel=files[prefix + "WHEEL"]))
        else:
            args["wheel"].write_bytes(zip_bytes(files))
    with pytest.raises(ValueError):
        builder.build_distribution(**args)
    assert not args["output"].exists()


@pytest.mark.parametrize("change", ["source", "marker", "closure", "hash", "url", "version", "size", "duplicate"])
def test_lock_drift_fails_closed_without_resolution(inputs, change):
    args, _ = inputs
    file = args["root"] / "backend/uv.lock"
    text = file.read_text()
    start = text.index('\n[[package]]\nname = "anyio"')
    before, block = text[:start], text[start:]
    if change == "source":
        block = block.replace('registry = "https://pypi.org/simple"', 'registry = "https://untrusted.invalid/simple"', 1)
    elif change == "marker":
        block = block.replace("python_full_version < '3.13'", "python_full_version < '3.12'", 1)
    elif change == "closure":
        block = block.replace('{ name = "idna" },', '{ name = "unexpected" },', 1)
    elif change == "hash":
        index = block.index("wheels = [")
        block = block[:index] + block[index:].replace('hash = "sha256:', 'hash = "sha512:', 1)
    elif change == "url":
        index = block.index("wheels = [")
        block = block[:index] + block[index:].replace("https://files.pythonhosted.org/", "https://untrusted.invalid/", 1)
    elif change == "version":
        block = block.replace('version = "4.13.0"', 'version = "4.13.0+unreviewed"', 1)
    elif change == "size":
        index = block.index("wheels = [")
        block = block[:index] + block[index:].replace("size = ", "size = -", 1)
    else:
        block += '\n[[package]]\nname = "anyio"\nversion = "0.0"\n'
    file.write_text(before + block)
    with pytest.raises((ValueError, KeyError)):
        builder.build_distribution(**args)
    assert not args["output"].exists()


@pytest.mark.parametrize("name", ["a/../b", "./relative", "a//b", "a/", "/root", "C:/root", "a\\b"])
def test_archive_paths_fail_closed(name):
    with pytest.raises(ValueError):
        builder.archive_entries(zip_bytes({name: b"not code"}))


@pytest.mark.parametrize("kind", ["duplicate", "case", "symlink", "fifo", "too-many", "large"])
def test_archive_nonregular_ambiguous_or_unbounded_members_rejected(kind):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if kind in {"symlink", "fifo"}:
            info = zipfile.ZipInfo("member")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK if kind == "symlink" else stat.S_IFIFO) << 16
            archive.writestr(info, b"target")
        elif kind == "too-many":
            for index in range(513):
                archive.writestr(str(index), b"x")
        elif kind == "large":
            archive.writestr("large", b"x" * (builder._LIMIT + 1))
        else:
            archive.writestr("member", b"first")
            if kind == "duplicate":
                with pytest.warns(UserWarning, match="Duplicate name"):
                    archive.writestr("member", b"second")
            else:
                archive.writestr("MEMBER", b"second")
    with pytest.raises(ValueError):
        builder.archive_entries(stream.getvalue())


def test_fsync_uncertainty_preserves_partial_output_no_repair(inputs, monkeypatch):
    args, _ = inputs
    calls = []

    def fail(fd):
        calls.append(fd)
        raise OSError("SYNTHETIC_SENSITIVE_ERROR")

    monkeypatch.setattr(builder.os, "fsync", fail)
    with pytest.raises(OSError):
        builder.build_distribution(**args)
    data = args["output"].read_bytes()
    assert data and len(calls) == 1
    with pytest.raises(FileExistsError):
        builder.build_distribution(**args)
    assert args["output"].read_bytes() == data and len(calls) == 1


def test_nonempty_regular_file_restriction_has_no_fifo_block(inputs):
    args, _ = inputs
    empty = args["wheel"].parent / "empty"
    empty.touch()
    with pytest.raises(ValueError):
        builder.read_regular(empty)
    if hasattr(os, "mkfifo"):
        fifo = empty.with_suffix(".fifo")
        os.mkfifo(fifo)
        with pytest.raises(ValueError):
            builder.read_regular(fifo)


def test_cli_error_is_generic_no_sensitive_paths_or_implicit_actions(inputs, monkeypatch, capsys):
    args, _ = inputs
    monkeypatch.setattr(builder.sys, "version_info", (3, 12))
    assert builder.main(["--wheel", "SENSITIVE_PATH"]) == 2
    result = capsys.readouterr()
    assert not result.out and "SENSITIVE" not in result.err and "no download/install/send" in result.err
    assert builder.main(["--dependency-lock", "--describe-dependencies"]) == 2
    capsys.readouterr()
    assert builder.main(["--dependency-lock"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 12
    assert builder.main(["--describe-dependencies"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 12
    monkeypatch.setattr(builder.sys, "version_info", (3, 13))
    assert builder.main(["--dependency-lock"]) == 2


def test_shipped_examples_are_synthetic_offline_and_match_real_cli(capsys):
    from devpilot.local_qa_cli import main

    directory = ROOT / "devpilot/distribution/examples"
    assert main([value for name in ("manifest", "values", "inputs") for value in ("--" + name, str(directory / (name + ".json")))]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema"] == "local-qa-preflight.v1" and result["mode"] == "execute_only" and result["network_performed"] is False and result["verdict"] == "NOT_EVALUATED"
    assert result["input_count"] == 2 and result["request_count"] == 5


def test_public_source_allowlist_covers_entire_package_not_only_qa_entry():
    names = set((ROOT / "devpilot/distribution/source-members.txt").read_text().splitlines())
    actual = {file.relative_to(ROOT / "devpilot/src").as_posix() for file in (ROOT / "devpilot/src/devpilot").rglob("*") if file.is_file() and file.suffix in {".py", ".md"} and "__pycache__" not in file.parts}
    assert names == actual and len(names) >= 35
    assert "devpilot/toolkit/report.py" in names and "devpilot/evaluation/runner.py" in names


def test_build_only_lock_is_complete_pinned_and_not_runtime_distribution():
    import re

    rows = (ROOT / "devpilot/distribution/build-requirements.lock").read_text().splitlines()
    records = [re.fullmatch(r"([a-z-]+)==([0-9.]+) --hash=sha256:([0-9a-f]{64})", line) for line in rows if line and not line.startswith("#")]
    assert all(records) and len(records) == 6
    assert {row[1] for row in records} == {"hatchling", "packaging", "pathspec", "pluggy", "tomlkit", "trove-classifiers"}
    assert all(row[1] not in builder._GRAPH for row in records)


@pytest.mark.parametrize("change", ["hash", "traversal", "member-hash", "existing-directory"])
def test_ci_checker_rejects_before_install_or_existing_output_change(inputs, tmp_path, monkeypatch, change):
    import sys

    monkeypatch.setitem(sys.modules, "build_local_qa_distribution", builder)
    check_spec = importlib.util.spec_from_file_location("local_qa_distribution_check", ROOT / "scripts/check_local_qa_distribution.py")
    checker = importlib.util.module_from_spec(check_spec)
    check_spec.loader.exec_module(checker)
    args, _ = inputs
    builder.build_distribution(**args)
    data = args["output"].read_bytes()
    if change == "traversal":
        data = zip_bytes({"../escape": b"never extract"})
    elif change == "member-hash":
        files = builder.archive_entries(data)
        files["LICENSE"] += b"tampered"
        data = zip_bytes(files)
    args["output"].write_bytes(data)
    work = tmp_path / "fresh-verification"
    if change == "existing-directory":
        work.mkdir()
        (work / "preserve").write_bytes(b"sentinel")

    def denied(*args, **kwargs):
        raise AssertionError("Installer must not be called")

    monkeypatch.setattr(checker.subprocess, "run", denied)
    with pytest.raises((ValueError, FileExistsError)):
        checker.verify(args["output"], "0" * 64 if change == "hash" else digest(data), work)
    assert not (tmp_path / "escape").exists()
    if change == "existing-directory":
        assert list(work.iterdir()) == [work / "preserve"] and (work / "preserve").read_bytes() == b"sentinel"
    else:
        assert not work.exists()


@pytest.mark.parametrize("kind", ["nul", "bzip2", "encrypted"])
def test_ambiguous_original_name_and_unexpected_zip_encoding_rejected(kind):
    import struct

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_BZIP2 if kind == "bzip2" else zipfile.ZIP_STORED) as archive:
        archive.writestr("member", b"bounded synthetic bytes")
    data = bytearray(stream.getvalue())
    if kind == "nul":
        data = bytes(data).replace(b"member", b"mem\x00er")
    elif kind == "encrypted":
        central = data.index(b"PK\x01\x02")
        struct.pack_into("<H", data, central + 8, 1)
    with pytest.raises(ValueError):
        builder.archive_entries(data)


def test_workflow_independently_builds_and_installs_with_hashes_without_backend_fallback():
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/backend-unit-tests.yml").read_text())
    job = workflow["jobs"]["local-qa-distribution"]
    assert job["runs-on"] == "ubuntu-latest"
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "build-requirements.lock" in commands and "--no-build-isolation" in commands
    assert 'python -I -m venv "$RUNNER_TEMP/local-qa-build"' in commands
    assert commands.count("--require-hashes --only-binary=:all:") == 2
    assert "--dependency-lock" in commands and "check_local_qa_distribution.py" in commands
    assert "--no-deps" not in commands and "uv sync" not in commands and "--system-site-packages" not in commands


@pytest.mark.parametrize("target", sorted(builder._NATIVE_TAGS))
def test_native_crypto_wheels_are_exact_locked_cpython312_profiles(target):
    _, artifacts = builder.dependency_artifacts(ROOT, target=target)
    crypto, ffi = builder._NATIVE_TAGS[target]
    assert len(artifacts) == 12
    assert artifacts["cryptography"]["filename"].endswith("-" + crypto + ".whl")
    assert artifacts["cffi"]["filename"].endswith("-" + ffi + ".whl")
    assert artifacts["pycparser"]["filename"].endswith("-py3-none-any.whl")
    assert all(len(item["sha256"]) == 64 and item["size"] > 0 for item in artifacts.values())


@pytest.mark.parametrize("target", ["linux-musl", "windows-arm64", "macos-x86_64", "", True])
def test_unknown_native_profile_never_falls_back_to_any_wheel(target):
    with pytest.raises(ValueError):
        builder.dependency_artifacts(ROOT, target=target)


def test_native_target_rejects_pypy_instead_of_dropping_crypto_closure(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(builder.sys, "implementation", SimpleNamespace(name="pypy"))
    with pytest.raises(ValueError):
        builder.native_target()


def test_checker_runs_isolated_without_script_path_import_fallback(tmp_path):
    import subprocess
    import sys

    # A namesake in cwd must never be imported, even without script-dir sys.path.
    (tmp_path / "build_local_qa_distribution.py").write_text("raise AssertionError('untrusted cwd import')")
    result = subprocess.run([sys.executable, "-I", str(ROOT / "scripts/check_local_qa_distribution.py"), "--help"], cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--archive" in result.stdout
