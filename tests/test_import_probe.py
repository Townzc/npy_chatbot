import io
import json
import stat
import struct
import zipfile

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from chattwin.api import create_app
from chattwin.cli import app
from chattwin.domain import DomainError
from chattwin.importers.parsers import detect, inspect, parse
from chattwin.importers.probe import MAX_CENTRAL_BYTES, MAX_ENTRIES, probe
from chattwin.storage import imports, messages


def synthetic_database(marker=b"MSG0"):
    """A made-up header and zero page, never an actual private/encrypted database."""
    header = bytearray(1024)
    header[:16] = b"SQLite header 3\0"
    header[16:18] = (1024).to_bytes(2, "big")
    header[32 : 32 + len(marker)] = marker
    return bytes(header) + bytes(4096)


def archive_bytes(entries, compression=zipfile.ZIP_STORED):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return output.getvalue()


def test_msg0_archive_probe_is_read_only_and_redacts_all_names(tmp_path):
    path = tmp_path / "fictional_account_and_name.bak"
    content = archive_bytes(
        [(f"fictional-private-name/{i}", synthetic_database()) for i in range(4)]
    )
    path.write_bytes(content)
    result = probe(path)
    assert result["kind"] == "qq_msg0_backup"
    assert result["member_kinds"] == {"qq_msg0_database": 4}
    assert result["files"] == 4
    assert result["full_crc_verified"] is False
    assert not result["chat_content_parsed"] and not result["extracted"]
    serialized = json.dumps(result)
    assert "fictional" not in serialized
    assert "sender" not in serialized and "sha256" not in serialized
    assert path.read_bytes() == content
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    ("content", "kind"),
    [
        (synthetic_database(), "qq_msg0_database"),
        (synthetic_database(b"QQ_NT DB"), "qq_nt_database"),
        (b"SQLite format 3\0" + bytes(100), "sqlite_database"),
        (b"\xff\0\xff", "binary"),
        (b' {"not": "a supported schema"}', "text_candidate"),
        (b"a" * 1023 + "你".encode(), "text_candidate"),
    ],
)
def test_magic_precedes_extension_and_keeps_ntqq_distinct(tmp_path, content, kind):
    path = tmp_path / "renamed.json"
    path.write_bytes(content)
    assert probe(path)["kind"] == kind


@pytest.mark.parametrize("format", ["auto", "csv", "canonical", "qce", "chatlab"])
def test_explicit_importer_and_renaming_cannot_bypass_backup_diagnosis(tmp_path, format):
    path = tmp_path / "misnamed.csv"
    path.write_bytes(archive_bytes([("fictional-name", synthetic_database())]))
    for operation in (lambda: inspect(path, format), lambda: list(parse(path, format))):
        with pytest.raises(DomainError) as error:
            operation()
        assert error.value.code == "QQ_BACKUP_REQUIRES_CONVERSION"
        assert "fictional-name" not in str(error.value)


def test_invalid_utf8_after_probe_prefix_becomes_domain_error(tmp_path):
    path = tmp_path / "broken.json"
    path.write_bytes(b" " * 2048 + b"\xff")
    with pytest.raises(DomainError) as error:
        detect(path)
    assert error.value.code == "INVALID_FILE"


@pytest.mark.parametrize(
    "variant", ["count", "directory_size", "truncated", "traversal", "symlink"]
)
def test_archive_limits_and_paths_are_checked_without_extraction(tmp_path, variant):
    name = "../fictional-secret" if variant == "traversal" else "fictional-secret"
    if variant == "symlink":
        info = zipfile.ZipInfo(name)
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        content = bytearray(archive_bytes([(info, b"/fictional/target")]))
    else:
        content = bytearray(archive_bytes([(name, synthetic_database())]))
    end = content.rfind(b"PK\x05\x06")
    if variant == "count":
        struct.pack_into("<HH", content, end + 8, MAX_ENTRIES + 1, MAX_ENTRIES + 1)
    elif variant == "directory_size":
        struct.pack_into("<L", content, end + 12, MAX_CENTRAL_BYTES + 1)
    elif variant == "truncated":
        del content[-12:]
    path = tmp_path / "source.bak"
    path.write_bytes(content)
    result = probe(path)
    assert result["archive_status"] == "unsupported_or_invalid"
    assert "fictional" not in json.dumps(result)
    assert list(tmp_path.iterdir()) == [path]


def test_encrypted_and_expansion_limited_members_are_not_read(tmp_path):
    for variant in ("encrypted", "expansion"):
        content = bytearray(archive_bytes([("private-name", b"a" * 200_000)], zipfile.ZIP_DEFLATED))
        if variant == "encrypted":
            central = content.find(b"PK\x01\x02")
            struct.pack_into("<H", content, 6, 1)
            struct.pack_into("<H", content, central + 8, 1)
        path = tmp_path / f"{variant}.bak"
        path.write_bytes(content)
        report = probe(path)
        key = "encrypted_zip_member" if variant == "encrypted" else "expansion_limit"
        assert report["member_kinds"] == {key: 1}
        assert not report["chat_content_parsed"]


def test_authenticated_upload_returns_422_without_persisting_private_upload(tmp_path):
    application = create_app(tmp_path / "store", token="synthetic-test")
    with TestClient(application) as client:
        client.headers["Authorization"] = "Bearer synthetic-test"
        for data in (
            archive_bytes([("fictional-private-name", synthetic_database())]),
            b"\xff\xfe\x00",
        ):
            response = client.post(
                "/api/v1/imports/inspect",
                files={"file": ("fictional-account.bak", data, "application/octet-stream")},
            )
            assert response.status_code == 422
            assert "fictional" not in response.text
        assert not list((tmp_path / "store" / "uploads").iterdir())
        assert not application.state.store.rows(imports)
        assert not application.state.store.rows(messages)


def test_probe_cli_never_initializes_store_or_prints_private_path(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime-must-not-be-created"
    monkeypatch.setenv("CHATTWIN_DATA_DIR", str(runtime))
    path = tmp_path / "fictional-account.bak"
    path.write_bytes(archive_bytes([("fictional-member", synthetic_database())]))
    result = CliRunner().invoke(app, ["import", "probe", str(path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["kind"] == "qq_msg0_backup"
    assert "fictional" not in result.output
    assert not runtime.exists()
    missing = CliRunner().invoke(app, ["import", "probe", str(tmp_path / "private-missing")])
    assert missing.exit_code == 2
    assert "private-missing" not in missing.output
