"""Bounded, read-only format diagnosis; no extraction, keys, names or message previews."""

from __future__ import annotations

import stat
import struct
import zipfile
import zlib
from collections import Counter
from pathlib import Path, PurePosixPath

from chattwin.domain import DomainError

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 128
MAX_CENTRAL_BYTES = 256 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
PREFIX_BYTES = 1024


def _kind(head: bytes) -> str:
    if head.startswith(b"SQLite header 3\0"):
        if head[32:36] == b"MSG0":
            return "qq_msg0_database"
        if head[32:40] == b"QQ_NT DB":
            return "qq_nt_database"
        return "sqlite_custom_header"
    if head.startswith(b"SQLite format 3\0"):
        return "sqlite_database"
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "zip_archive"
    if b"\0" in head or head.startswith((b"\x1f\x8b", b"bplist00")):
        return "binary"
    try:
        # A bounded read can end inside a valid UTF-8 character.
        import codecs

        codecs.getincrementaldecoder("utf-8-sig")().decode(head, final=False)
    except UnicodeError:
        return "binary"
    return "text_candidate"


def _archive_directory_is_bounded(path: Path, size: int) -> bool:
    # Check the small end record before ZipFile allocates its central-directory list.
    with path.open("rb") as handle:
        handle.seek(max(0, size - 65557))
        tail = handle.read(65557)
    start = tail.rfind(b"PK\x05\x06")
    if start < 0 or len(tail) - start < 22:
        return False
    _, disk, directory_disk, disk_count, count, length, offset, comment = struct.unpack_from(
        "<4s4H2LH", tail, start
    )
    end_offset = size - len(tail) + start
    return (
        disk == directory_disk == 0
        and disk_count == count
        and count <= MAX_ENTRIES
        and length <= MAX_CENTRAL_BYTES
        and offset + length == end_offset
        and len(tail) - start == 22 + comment
    )


def _archive(path: Path, size: int) -> dict:
    report: dict = {"kind": "zip_archive", "archive_status": "unsupported_or_invalid"}
    if not _archive_directory_is_bounded(path, size):
        return report
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            # Check again: the end record may lie about the actual directory count.
            if len(entries) > MAX_ENTRIES:
                return report
            files = [entry for entry in entries if not entry.is_dir()]
            expanded = sum(entry.file_size for entry in files)
            unsafe = any(
                PurePosixPath(entry.filename).is_absolute()
                or ".." in PurePosixPath(entry.filename).parts
                or "\\" in entry.filename
                or ":" in entry.filename
                or stat.S_ISLNK(entry.external_attr >> 16)
                for entry in entries
            )
            if unsafe or expanded > MAX_EXPANDED_BYTES:
                return report
            kinds: Counter[str] = Counter()
            for entry in files:
                if entry.flag_bits & 1:
                    kinds["encrypted_zip_member"] += 1
                    continue
                if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    kinds["unsupported_compression"] += 1
                    continue
                if entry.file_size > max(entry.compress_size, 1) * 100:
                    kinds["expansion_limit"] += 1
                    continue
                with archive.open(entry) as handle:
                    kinds[_kind(handle.read(PREFIX_BYTES))] += 1
            report.update(
                archive_status="prefixes_checked",
                entries=len(entries),
                files=len(files),
                declared_expanded_bytes=expanded,
                member_kinds=dict(kinds),
                full_crc_verified=False,
            )
            if files and kinds["qq_msg0_database"] == len(files):
                report["kind"] = "qq_msg0_backup"
    except (
        zipfile.BadZipFile,
        OSError,
        EOFError,
        RuntimeError,
        ValueError,
        NotImplementedError,
        zlib.error,
    ):
        # Library errors may contain private member names; never return their text.
        report["archive_status"] = "unsupported_or_invalid"
    return report


def probe(path: Path | str) -> dict:
    """Return only structural metadata. Text candidate does not mean supported import."""
    path = Path(path)
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            raise DomainError("IMPORT_SIZE", "仅检查不超过 64 MiB 的普通文件", 422)
        with path.open("rb") as handle:
            kind = _kind(handle.read(PREFIX_BYTES))
        report = _archive(path, info.st_size) if kind == "zip_archive" else {"kind": kind}
    except OSError:
        raise DomainError("IMPORT_FILE", "无法读取所选普通文件", 422) from None
    return {
        "probe_version": "1",
        "bytes": info.st_size,
        **report,
        "chat_content_parsed": False,
        "history_completeness": "unknown",
        "extracted": False,
    }


def reject_unsupported_container(path: Path) -> None:
    result = probe(path)
    kind = result["kind"]
    if kind == "text_candidate":
        return
    if kind in {"qq_msg0_database", "qq_msg0_backup"}:
        code = "QQ_BACKUP_REQUIRES_CONVERSION"
        message = (
            "识别到 QQ MSG0 数据库备份，尚未解密或读取聊天。"
            "请在生成备份的 QQ 中核对可见历史，取得可读的 QCE/ChatLab JSON 或 CSV 后再导入；"
            "改后缀或直接解压不能完成转换。"
        )
    elif kind in {"qq_nt_database", "sqlite_custom_header", "sqlite_database"}:
        code = "DATABASE_REQUIRES_CONVERSION"
        message = "这是数据库文件，当前导入器需要可读的 QCE/ChatLab JSON、规范 JSONL 或 CSV。"
    elif kind == "zip_archive":
        code = "ARCHIVE_REQUIRES_CONVERSION"
        message = "这是归档文件，或归档结构无法在检查限制内识别；未提取或解析聊天。"
    else:
        code = "UNSUPPORTED_BINARY_FORMAT"
        message = "文件不是支持的 UTF-8 聊天导出；不能把二进制备份直接当作 JSON 或 CSV。"
    raise DomainError(code, message, 422)
