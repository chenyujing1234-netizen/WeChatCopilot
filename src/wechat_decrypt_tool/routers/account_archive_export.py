import html
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, SecretStr

from ..account_identity import resolve_account_self_username
from ..chat_export_service import (
    _iter_rows_for_conversation,
    _load_export_contact_usernames,
    _load_export_session_targets,
    _load_message_backed_export_targets,
)
from ..chat_helpers import (
    _load_contact_rows,
    _pick_display_name,
    _resolve_account_dir,
    _should_keep_session,
)
from ..export_integrity import IntegrityZipWriter, write_zip_integrity_sidecars
from ..native_core_export import (
    decode_export_content_key,
    encrypt_export_file_and_remove_source,
    erase_export_content_key,
)
from ..native_core_telemetry import record_product_event
from ..path_fix import PathFixRoute

router = APIRouter(route_class=PathFixRoute)


class AccountArchiveExportRequest(BaseModel):
    account: Optional[str] = Field(None, description="Account directory name. Defaults to the first available account.")
    output_dir: Optional[str] = Field(None, description="Absolute output directory. Defaults to output/exports/{account}.")
    include_databases: bool = Field(True, description="Whether to include decrypted database files.")
    include_resources: bool = Field(True, description="Whether to include resource folders.")
    include_structured: bool = Field(False, description="Whether to include structured JSON data exports (e.g. chat messages).")
    file_name: Optional[str] = Field(None, description="Optional zip file name, with or without .zip.")
    encrypt: bool = Field(False, description="Encrypt the completed archive as a WEC1 file.")
    content_key_base64: Optional[SecretStr] = Field(
        None,
        description="Base64-encoded 32-byte WEC1 content key; used only when encrypt=true.",
    )


class AccountArchiveCancelled(Exception):
    pass


@dataclass(frozen=True)
class AccountArchiveFile:
    path: Path
    arcname: str
    kind: str
    size: int
    mtime: float
    mode: int


@dataclass
class AccountArchiveExportJob:
    export_id: str
    account: str = ""
    status: str = "queued"
    progress: int = 0
    message: str = "Waiting to start..."
    detail: str = ""
    error: str = ""
    zip_path: str = ""
    file_name: str = ""
    database_count: int = 0
    resource_file_count: int = 0
    structured_file_count: int = 0
    total_bytes: int = 0
    processed_bytes: int = 0
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))
    cancel_requested: bool = False
    encrypted: bool = False
    content_key: Optional[bytearray] = field(default=None, repr=False)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "exportId": self.export_id,
            "account": self.account,
            "status": self.status,
            "progress": max(0, min(100, int(self.progress or 0))),
            "message": self.message,
            "detail": self.detail,
            "error": self.error,
            "zipPath": self.zip_path,
            "fileName": self.file_name,
            "databaseCount": int(self.database_count or 0),
            "resourceFileCount": int(self.resource_file_count or 0),
            "structuredFileCount": int(self.structured_file_count or 0),
            "totalBytes": int(self.total_bytes or 0),
            "processedBytes": int(self.processed_bytes or 0),
            "createdAt": int(self.created_at or 0),
            "updatedAt": int(self.updated_at or 0),
            "cancelRequested": bool(self.cancel_requested),
            "encrypted": bool(self.encrypted),
        }


_SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z._-]+")
# 账号归档以账号目录为边界。数据库通常在账号目录顶层，资源文件通常在子目录中。
_DB_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".db3"}
_META_FILE_NAMES = {"_source.json", "_media_keys.json", "_sns_realtime_sync_state.json"}
_SQLITE_HEADER = b"SQLite format 3\x00"
_JOBS: dict[str, AccountArchiveExportJob] = {}
_JOBS_LOCK = threading.RLock()


def _safe_file_name(value: object, fallback: str) -> str:
    text = str(value or "").strip().replace("\\", "/").split("/")[-1]
    text = _SAFE_NAME_RE.sub("_", text).strip("._-")
    return text or fallback


def _normalize_zip_name(value: object, fallback: str) -> str:
    name = _safe_file_name(value, fallback)
    if not name.lower().endswith(".zip"):
        name += ".zip"
    return name


def _is_valid_sqlite(path: Path) -> bool:
    try:
        if not path.is_file():
            return False
        with path.open("rb") as source:
            return source.read(len(_SQLITE_HEADER)) == _SQLITE_HEADER
    except OSError:
        return False


def _require_portable_database_pair(account_dir: Path) -> None:
    required_names = ("contact.db", "session.db")
    missing = [name for name in required_names if not _is_valid_sqlite(account_dir / name)]
    if not missing:
        return
    raise FileNotFoundError(
        "所选账号缺少可迁移的已解密数据库（需要有效的 contact.db 和 session.db）。"
        "实时读取可用不代表已有可导入备份，请先在原电脑完成数据库解密，再重新导出。"
    )


def _resolve_output_dir(account_dir: Path, output_dir_raw: object) -> Path:
    raw = str(output_dir_raw or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (account_dir.parents[1] / "exports" / account_dir.name).resolve()


def _iter_database_files(account_dir: Path) -> list[Path]:
    return sorted(
        (
            item
            for item in account_dir.iterdir()
            if item.is_file()
            and (
                item.suffix.lower() in _DB_SUFFIXES
                or item.name in _META_FILE_NAMES
            )
        ),
        key=lambda p: p.name.lower(),
    )


def _get_job(export_id: str) -> Optional[AccountArchiveExportJob]:
    key = str(export_id or "").strip()
    if not key:
        return None
    with _JOBS_LOCK:
        return _JOBS.get(key)


def _update_job(export_id: str, **changes: Any) -> Optional[AccountArchiveExportJob]:
    with _JOBS_LOCK:
        job = _JOBS.get(str(export_id or "").strip())
        if not job:
            return None
        for key, value in changes.items():
            if hasattr(job, key):
                setattr(job, key, value)
        job.updated_at = int(time.time())
        return job


def _check_cancel(job: AccountArchiveExportJob, tmp_path: Optional[Path] = None) -> None:
    with _JOBS_LOCK:
        cancelled = bool(job.cancel_requested)
    if not cancelled:
        return
    if tmp_path is not None:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
    raise AccountArchiveCancelled()


def _add_file(zip_file: zipfile.ZipFile, item: AccountArchiveFile) -> Optional[int]:
    try:
        modified = time.localtime(item.mtime)[:6]
        if modified[0] < 1980:
            modified = (1980, 1, 1, 0, 0, 0)
        info = zipfile.ZipInfo(item.arcname, modified)
        info.compress_type = zipfile.ZIP_STORED
        info.file_size = item.size
        info.external_attr = (item.mode & 0xFFFF) << 16
        with item.path.open("rb") as source, zip_file.open(info, "w", force_zip64=True) as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        return int(item.size)
    except (FileNotFoundError, OSError):
        return None


def _is_database_or_meta_file(path: Path) -> bool:
    return path.is_file() and (path.suffix.lower() in _DB_SUFFIXES or path.name in _META_FILE_NAMES)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _iter_selected_account_files(
    *,
    job: AccountArchiveExportJob,
    account_dir: Path,
    include_databases: bool,
    include_resources: bool,
    tmp_path: Optional[Path],
    zip_path: Optional[Path],
    output_dir: Optional[Path],
):
    """Fast metadata scan for selected account files.

    Folder size is not stored as one reliable value by the filesystem. To show an
    accurate total before packing, we still have to enumerate files, but os.scandir
    reuses directory-entry metadata and avoids the heavier Path/os.walk/resolve path.
    """

    account_prefix = _safe_file_name(account_dir.name, "account")
    pack_whole_account_folder = include_databases and include_resources
    account_dir_str = os.path.abspath(os.fspath(account_dir))
    excluded_files = set()
    for candidate in (tmp_path, zip_path):
        if candidate is None:
            continue
        try:
            excluded_files.add(os.path.normcase(os.path.abspath(os.fspath(candidate))))
        except OSError:
            pass

    skipped_output_dir: Optional[str] = None
    if output_dir is not None:
        try:
            output_dir_str = os.path.abspath(os.fspath(output_dir))
            # 如果用户把导出目录选在账号目录内部，避免把正在生成的导出文件再次打包进去。
            if output_dir_str != account_dir_str and os.path.commonpath([account_dir_str, output_dir_str]) == account_dir_str:
                skipped_output_dir = os.path.normcase(output_dir_str)
        except (OSError, ValueError):
            skipped_output_dir = None

    stack: list[tuple[str, bool]] = [(account_dir_str, True)]
    while stack:
        root, is_account_root = stack.pop()
        _check_cancel(job, tmp_path)
        normalized_root = os.path.normcase(os.path.abspath(root))
        if skipped_output_dir is not None and normalized_root == skipped_output_dir:
            continue

        try:
            with os.scandir(root) as entries:
                entry_list = list(entries)
        except OSError:
            continue

        for entry in entry_list:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if is_account_root and not pack_whole_account_folder and not include_resources:
                        continue
                    stack.append((entry.path, False))
                    continue

                if not entry.is_file(follow_symlinks=False):
                    continue

                file_path_str = entry.path
                if os.path.normcase(os.path.abspath(file_path_str)) in excluded_files:
                    continue

                name = entry.name
                suffix = os.path.splitext(name)[1].lower()
                is_top_level_database = is_account_root and (suffix in _DB_SUFFIXES or name in _META_FILE_NAMES)
                if pack_whole_account_folder:
                    kind = "database" if is_top_level_database else "resource"
                elif include_databases and is_top_level_database:
                    kind = "database"
                elif include_resources and not is_account_root:
                    kind = "resource"
                else:
                    continue

                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue

                try:
                    rel = os.path.relpath(file_path_str, account_dir_str).replace(os.sep, "/")
                except ValueError:
                    continue

                yield AccountArchiveFile(
                    path=Path(file_path_str),
                    arcname=f"{account_prefix}/{rel}",
                    kind=kind,
                    size=int(st.st_size),
                    mtime=float(st.st_mtime),
                    mode=int(st.st_mode),
                )
            except OSError:
                continue

_STRUCTURED_CHAT_TYPE_NAMES = {
    1: "文本",
    3: "图片",
    34: "语音",
    37: "好友申请",
    42: "名片",
    43: "视频",
    47: "表情",
    48: "位置",
    49: "复合消息",
    50: "通话",
    51: "状态通知",
    62: "小视频",
    66: "微信红包",
    10000: "系统消息",
    10002: "撤回消息",
}


def _structured_type_name(local_type: int) -> str:
    if local_type in _STRUCTURED_CHAT_TYPE_NAMES:
        return _STRUCTURED_CHAT_TYPE_NAMES[local_type]
    if 10000 <= local_type < 20000:
        return "系统消息"
    return "未知"


def _structured_time_text(ts: int) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts or 0)))
    except (ValueError, OverflowError, OSError):
        return ""


# Matches real markup tags only; plain text like "1<2 and a>b" is left untouched.
_TAG_RE = re.compile(r"<[a-zA-Z/!][^>]*>")
_APPMSG_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_FILENAME_INVALID_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_TXT_TYPE_FALLBACK_LABELS = {
    3: "[图片]",
    34: "[语音]",
    37: "[好友申请]",
    42: "[名片]",
    43: "[视频]",
    47: "[表情]",
    48: "[位置]",
    49: "[消息]",
    50: "[通话]",
    51: "[状态通知]",
    62: "[小视频]",
    66: "[红包]",
}


def _structured_plain_text(local_type: int, raw_text: str) -> str:
    """Readable plain text for the txt transcript: strips HTML/XML markup."""
    text = str(raw_text or "")
    if not _TAG_RE.search(text):
        return text.strip()

    plain = ""
    if local_type == 49:
        match = _APPMSG_TITLE_RE.search(text)
        if match:
            plain = match.group(1)
    if not plain:
        plain = _TAG_RE.sub(" ", text)
    plain = html.unescape(plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        plain = _TXT_TYPE_FALLBACK_LABELS.get(local_type, "[消息]")
    return plain


def _structured_display_file_stem(display_name: str, username: str, used_names: set[str]) -> str:
    """Filesystem-safe, case-insensitively unique file stem from a conversation name."""
    stem = _FILENAME_INVALID_RE.sub("_", str(display_name or "").strip()).strip(" .")
    if not stem:
        stem = _FILENAME_INVALID_RE.sub("_", str(username or "").strip()).strip(" .")
    if not stem:
        stem = "未命名会话"
    stem = stem[:60]
    candidate = stem
    counter = 2
    while candidate.lower() in used_names:
        candidate = f"{stem}_{counter}"
        counter += 1
    used_names.add(candidate.lower())
    return candidate


def _load_structured_display_names(account_dir: Path) -> dict[str, str]:
    """One-shot username -> display name map from contact.db (contact + stranger)."""
    contact_db_path = account_dir / "contact.db"
    usernames = _load_export_contact_usernames(contact_db_path.parent)
    rows = _load_contact_rows(contact_db_path, list(usernames))
    out: dict[str, str] = {}
    for username, row in rows.items():
        out[username] = _pick_display_name(row, username)
    return out


def _resolve_structured_conversation_targets(account_dir: Path, self_username: str) -> list[tuple[str, int]]:
    """Union of session.db conversations and conversations found in message databases."""
    targets: dict[str, int] = {}

    sessions, _hidden = _load_export_session_targets(account_dir)
    for username, sort_ts in sessions:
        u = str(username or "").strip()
        if not u or u == self_username:
            continue
        if not _should_keep_session(u, include_official=False):
            continue
        targets[u] = max(int(sort_ts or 0), int(targets.get(u, 0)))

    try:
        backed = _load_message_backed_export_targets(account_dir=account_dir, seed_usernames=set(targets.keys()))
    except Exception:
        backed = {}
    for username, latest_ts in backed.items():
        u = str(username or "").strip()
        if not u or u == self_username:
            continue
        targets[u] = max(int(latest_ts or 0), int(targets.get(u, 0)))

    return sorted(targets.items(), key=lambda kv: kv[1], reverse=True)


def _flatten_text_for_line(text: str) -> str:
    return (
        str(text or "")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _generate_structured_chat_data(
    *,
    job: AccountArchiveExportJob,
    account_dir: Path,
    staging_dir: Path,
    account_prefix: str,
) -> list[AccountArchiveFile]:
    """Generate structured JSON chat data under staging_dir/structured_data.

    Each conversation is written to structured_data/chat/<idx>_<username>.json with
    per-message fields: sender, time, content, receiver, type, etc. A plain-text
    transcript named after the conversation (<会话名>.txt, one line per message:
    time + sender + plain-text content, no HTML/XML markup) is generated alongside
    for quick human reading.
    """
    _update_job(
        job.export_id,
        message="Generating structured data...",
        detail="Reading decrypted chat databases and writing JSON/TXT files.",
    )

    self_username = resolve_account_self_username(account_dir)
    display_names = _load_structured_display_names(account_dir)
    targets = _resolve_structured_conversation_targets(account_dir, self_username)
    if not targets:
        raise FileNotFoundError(
            "No chat conversations found for structured export (are decrypted message databases available?)."
        )

    def display_name_of(username: str) -> str:
        return display_names.get(username) or username

    def checkpoint() -> None:
        _check_cancel(job)

    chat_dir = staging_dir / "structured_data" / "chat"
    chat_dir.mkdir(parents=True, exist_ok=True)

    index_conversations: list[dict[str, Any]] = []
    generated: list[AccountArchiveFile] = []
    total_messages = 0
    self_display = display_name_of(self_username) if self_username else account_dir.name
    used_txt_names: set[str] = set()

    for idx, (conv_username, _sort_ts) in enumerate(targets, start=1):
        _check_cancel(job)
        is_group = conv_username.endswith("@chatroom")
        conv_display = display_name_of(conv_username)
        json_file_stem = f"{idx:04d}_{_safe_file_name(conv_username, f'chat_{idx}')}"
        out_path = staging_dir / "structured_data" / "chat" / f"{json_file_stem}.json"
        txt_stem = _structured_display_file_stem(conv_display, conv_username, used_txt_names)
        out_txt_path = staging_dir / "structured_data" / "chat" / f"{txt_stem}.txt"

        message_count = 0
        try:
            with open(out_path, "w", encoding="utf-8", newline="\n") as out, open(
                out_txt_path, "w", encoding="utf-8", newline="\n"
            ) as txt_out:
                txt_out.write(f"会话: {conv_display} ({conv_username})\n")
                txt_out.write(f"账号: {account_dir.name}\n")
                txt_out.write(f"导出时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                txt_out.write("\n")

                out.write("{\n")
                out.write('  "schemaVersion": 1,\n')
                out.write('  "kind": "wechat_structured_data",\n')
                out.write('  "dataType": "chat_messages",\n')
                out.write(f"  \"exportedAt\": {json.dumps(time.strftime('%Y-%m-%dT%H:%M:%S'), ensure_ascii=False)},\n")
                out.write(f"  \"account\": {json.dumps(account_dir.name, ensure_ascii=False)},\n")
                out.write(
                    "  \"conversation\": "
                    + json.dumps(
                        {
                            "username": conv_username,
                            "displayName": conv_display,
                            "isGroup": is_group,
                        },
                        ensure_ascii=False,
                    )
                    + ",\n"
                )
                out.write('  "messages": [\n')

                rows = _iter_rows_for_conversation(
                    account_dir=account_dir,
                    conv_username=conv_username,
                    start_time=None,
                    end_time=None,
                    local_types=None,
                    source="decrypted",
                    checkpoint=checkpoint,
                )
                first = True
                for row in rows:
                    sender = str(row.sender_username or "").strip()
                    if row.is_sent:
                        sender = self_username
                        receiver = conv_username if is_group else conv_username
                    else:
                        if not sender:
                            sender = conv_username if is_group else conv_username
                        receiver = conv_username if is_group else self_username
                    sender_display = self_display if row.is_sent else display_name_of(sender)
                    local_type = int(row.local_type or 0)

                    item = {
                        "sender": sender,
                        "senderDisplayName": sender_display,
                        "isSelf": bool(row.is_sent),
                        "timestamp": int(row.create_time or 0),
                        "time": _structured_time_text(row.create_time),
                        "type": local_type,
                        "typeName": _structured_type_name(local_type),
                        "content": row.raw_text,
                        "receiver": receiver,
                        "conversation": conv_username,
                        "messageId": int(row.server_id or 0),
                        "localId": int(row.local_id or 0),
                    }
                    line = json.dumps(item, ensure_ascii=False, default=str)
                    if first:
                        out.write(f"    {line}")
                        first = False
                    else:
                        out.write(f",\n    {line}")
                    message_count += 1

                    content_flat = _flatten_text_for_line(_structured_plain_text(local_type, row.raw_text))
                    if sender_display and sender and sender_display != sender:
                        sender_label = f"{sender_display}({sender})"
                    else:
                        sender_label = sender_display or sender or "未知"
                    if 10000 <= local_type < 20000:
                        txt_line = f"[{item['time']}] [系统] {content_flat}"
                    else:
                        txt_line = f"[{item['time']}] {sender_label}: {content_flat}"
                    txt_out.write(txt_line + "\n")

                out.write("\n  ]\n}\n")
        except AccountArchiveCancelled:
            try:
                out_path.unlink(missing_ok=True)
                out_txt_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        except Exception:
            # A single broken conversation should not abort the whole export.
            try:
                out_path.unlink(missing_ok=True)
                out_txt_path.unlink(missing_ok=True)
            except OSError:
                pass
            continue

        if message_count <= 0:
            try:
                out_path.unlink(missing_ok=True)
                out_txt_path.unlink(missing_ok=True)
            except OSError:
                pass
            continue

        total_messages += message_count
        index_conversations.append(
            {
                "username": conv_username,
                "displayName": conv_display,
                "isGroup": is_group,
                "messageCount": message_count,
                "file": f"chat/{json_file_stem}.json",
                "fileTxt": f"chat/{txt_stem}.txt",
            }
        )
        for out_file, rel_name in (
            (out_path, f"chat/{json_file_stem}.json"),
            (out_txt_path, f"chat/{txt_stem}.txt"),
        ):
            try:
                stat_result = out_file.stat()
                generated.append(
                    AccountArchiveFile(
                        path=out_file,
                        arcname=f"{account_prefix}/structured_data/{rel_name}",
                        kind="structured",
                        size=int(stat_result.st_size),
                        mtime=float(stat_result.st_mtime),
                        mode=int(stat_result.st_mode),
                    )
                )
            except OSError:
                continue

    index_payload = {
        "schemaVersion": 1,
        "kind": "wechat_structured_data",
        "exportedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "account": account_dir.name,
        "selfUsername": self_username,
        "selfDisplayName": self_display,
        "dataTypes": {
            "chatMessages": {
                "conversationCount": len(index_conversations),
                "messageCount": total_messages,
                "fields": [
                    "sender",
                    "senderDisplayName",
                    "isSelf",
                    "timestamp",
                    "time",
                    "type",
                    "typeName",
                    "content",
                    "receiver",
                    "conversation",
                    "messageId",
                    "localId",
                ],
                "conversations": index_conversations,
            }
        },
    }
    index_path = staging_dir / "structured_data" / "index.json"
    index_path.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        stat_result = index_path.stat()
        generated.append(
            AccountArchiveFile(
                path=index_path,
                arcname=f"{account_prefix}/structured_data/index.json",
                kind="structured",
                size=int(stat_result.st_size),
                mtime=float(stat_result.st_mtime),
                mode=int(stat_result.st_mode),
            )
        )
    except OSError:
        pass

    if not generated:
        raise FileNotFoundError("No chat messages could be exported as structured data.")
    return generated


def _run_account_archive_export(export_id: str, payload: dict[str, Any]) -> None:
    job = _update_job(export_id, status="running", progress=1, message="Preparing export...", detail="")
    if not job:
        return

    zip_path: Optional[Path] = None
    tmp_path: Optional[Path] = None
    staging_ctx: Optional[tempfile.TemporaryDirectory] = None

    try:
        include_databases = bool(payload.get("include_databases"))
        include_resources = bool(payload.get("include_resources"))
        include_structured = bool(payload.get("include_structured"))
        if not include_databases and not include_resources and not include_structured:
            raise ValueError("Please select at least one export option.")

        _check_cancel(job)
        account_dir = _resolve_account_dir(payload.get("account"))
        account_name = account_dir.name
        _update_job(export_id, account=account_name)
        if include_databases:
            _require_portable_database_pair(account_dir)
        output_dir = _resolve_output_dir(account_dir, payload.get("output_dir"))
        output_dir.mkdir(parents=True, exist_ok=True)

        account_prefix = _safe_file_name(account_name, "account")
        structured_files: list[AccountArchiveFile] = []
        if include_structured:
            _check_cancel(job)
            staging_ctx = tempfile.TemporaryDirectory(prefix="wechat_structured_export_")
            structured_files = _generate_structured_chat_data(
                job=job,
                account_dir=account_dir,
                staging_dir=Path(staging_ctx.name),
                account_prefix=account_prefix,
            )

        stamp = time.strftime("%Y%m%d_%H%M%S")
        fallback_name = f"wechat_archive_{account_prefix}_{stamp}.zip"
        zip_name = _normalize_zip_name(payload.get("file_name"), fallback_name)
        zip_path = (output_dir / zip_name).resolve()
        final_path = zip_path.with_name(zip_path.name + ".wec") if job.content_key is not None else zip_path
        tmp_path = zip_path.with_suffix(zip_path.suffix + ".tmp")

        _update_job(
            export_id,
            account=account_name,
            file_name=final_path.name,
            zip_path=str(final_path),
            progress=1,
            message="Scanning export content...",
            detail="Calculating total archive size.",
            total_bytes=0,
            processed_bytes=0,
        )

        if tmp_path.exists():
            tmp_path.unlink()

        selected_files = list(_iter_selected_account_files(
            job=job,
            account_dir=account_dir,
            include_databases=include_databases,
            include_resources=include_resources,
            tmp_path=tmp_path,
            zip_path=zip_path,
            output_dir=output_dir,
        ))
        selected_files.extend(structured_files)
        if not selected_files:
            raise FileNotFoundError("No exportable files found for this account.")

        planned_db_count = sum(1 for item in selected_files if item.kind == "database")
        planned_structured_count = sum(1 for item in selected_files if item.kind == "structured")
        planned_resource_count = sum(
            1 for item in selected_files if item.kind not in ("database", "structured")
        )
        total_files = len(selected_files)
        total_bytes = sum(max(0, int(item.size or 0)) for item in selected_files)
        if include_databases and not include_resources and not include_structured and planned_db_count <= 0:
            raise FileNotFoundError("No database files found for this account.")
        if include_resources and not include_databases and not include_structured and planned_resource_count <= 0:
            raise FileNotFoundError("No resource files found for this account.")
        if include_structured and planned_structured_count <= 0:
            raise FileNotFoundError("No structured data could be generated for this account.")

        _update_job(
            export_id,
            progress=5,
            database_count=planned_db_count,
            resource_file_count=planned_resource_count,
            structured_file_count=planned_structured_count,
            total_bytes=total_bytes,
            processed_bytes=0,
            message="Writing ZIP archive...",
            detail=f"Ready to pack {total_files} files ({total_bytes / 1024 / 1024:.1f} MB).",
        )

        db_count = 0
        resource_file_count = 0
        structured_count = 0
        processed_bytes = 0
        processed = 0
        last_progress_at = time.monotonic()

        # Use ZIP_STORED intentionally: account archives are mostly SQLite,
        # images, videos and cache files. Re-compressing them is CPU-heavy and
        # often saves little space. This makes archive export behave like a fast
        # folder pack/copy operation.
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as raw_zf:
            zf = IntegrityZipWriter(raw_zf)
            for item in selected_files:
                _check_cancel(job, tmp_path)
                added_size = _add_file(zf, item)
                if added_size is not None:
                    zf.add_file_entry(item.path, item.arcname)
                    processed += 1
                    if item.kind == "database":
                        db_count += 1
                    elif item.kind == "structured":
                        structured_count += 1
                    else:
                        resource_file_count += 1
                    processed_bytes += added_size

                now = time.monotonic()
                if processed <= 5 or processed % 20 == 0 or (now - last_progress_at) >= 0.5:
                    last_progress_at = now
                    if total_bytes > 0:
                        progress = min(95, 5 + int((processed_bytes / total_bytes) * 90))
                    else:
                        progress = min(95, 5 + int((processed / max(1, total_files)) * 90))
                    _update_job(
                        export_id,
                        progress=progress,
                        database_count=db_count,
                        resource_file_count=resource_file_count,
                        structured_file_count=structured_count,
                        total_bytes=total_bytes,
                        processed_bytes=processed_bytes,
                        message="Writing ZIP archive...",
                        detail=(
                            f"Packed {processed}/{total_files} files "
                            f"({processed_bytes / 1024 / 1024:.1f}/{total_bytes / 1024 / 1024:.1f} MB)."
                        ),
                    )
            write_zip_integrity_sidecars(zf, export_id)

        _check_cancel(job, tmp_path)
        _update_job(export_id, progress=97, message="Finalizing ZIP archive...", detail="Moving archive to target folder.")
        if final_path.exists():
            final_path.unlink()
        if job.content_key is not None:
            encrypt_export_file_and_remove_source(
                tmp_path,
                final_path,
                export_id=export_id,
                content_key=job.content_key,
            )
        else:
            shutil.move(str(tmp_path), str(final_path))

        if structured_count > 0:
            done_detail = (
                f"Exported {db_count} database files, {resource_file_count} resource files "
                f"and {structured_count} structured data files."
            )
        else:
            done_detail = f"Exported {db_count} database files and {resource_file_count} resource files."
        _update_job(
            export_id,
            status="done",
            progress=100,
            message="Export completed.",
            detail=done_detail,
            database_count=db_count,
            resource_file_count=resource_file_count,
            structured_file_count=structured_count,
            total_bytes=total_bytes,
            processed_bytes=processed_bytes,
            zip_path=str(final_path),
            file_name=final_path.name,
        )
        record_product_event("export_completed")
    except AccountArchiveCancelled:
        try:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        _update_job(export_id, status="cancelled", message="Export cancelled.", detail="Temporary archive has been removed.")
    except Exception as exc:
        try:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        _update_job(export_id, status="error", error=str(exc), message="Export failed.", detail="")
        record_product_event("export_failed")
    finally:
        if staging_ctx is not None:
            try:
                staging_ctx.cleanup()
            except Exception:
                pass
        erase_export_content_key(job.content_key)
        job.content_key = None


@router.post("/api/account/archive_export", summary="Create account archive export job")
async def export_account_archive(req: AccountArchiveExportRequest):
    if not req.include_databases and not req.include_resources and not req.include_structured:
        raise HTTPException(status_code=400, detail="Please select at least one export option.")

    try:
        content_key = decode_export_content_key(
            req.content_key_base64.get_secret_value() if req.content_key_base64 else None,
            enabled=bool(req.encrypt),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload = {
        "account": req.account,
        "output_dir": req.output_dir,
        "include_databases": bool(req.include_databases),
        "include_resources": bool(req.include_resources),
        "include_structured": bool(req.include_structured),
        "file_name": req.file_name,
    }
    export_id = uuid.uuid4().hex
    job = AccountArchiveExportJob(
        export_id=export_id,
        encrypted=bool(req.encrypt),
        content_key=content_key,
    )
    with _JOBS_LOCK:
        _JOBS[export_id] = job

    thread = threading.Thread(target=_run_account_archive_export, args=(export_id, payload), daemon=True)
    try:
        thread.start()
    except Exception:
        with _JOBS_LOCK:
            _JOBS.pop(export_id, None)
        erase_export_content_key(content_key)
        raise
    return {"status": "success", "job": job.to_public_dict()}


@router.get("/api/account/archive_export/download", summary="Download account archive by file path")
async def download_account_archive(path: str):
    zip_path = Path(str(path or "").strip()).expanduser().resolve()
    if not zip_path.exists() or not zip_path.is_file():
        raise HTTPException(status_code=404, detail="Export file not found.")
    if zip_path.suffix.lower() not in {".zip", ".wec"}:
        raise HTTPException(status_code=400, detail="Invalid export file.")
    return FileResponse(
        str(zip_path),
        media_type="application/octet-stream" if zip_path.suffix.lower() == ".wec" else "application/zip",
        filename=zip_path.name,
    )


@router.get("/api/account/archive_export/{export_id}", summary="Get account archive export job")
async def get_account_archive_export(export_id: str):
    job = _get_job(export_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export not found.")
    return {"status": "success", "job": job.to_public_dict()}


@router.delete("/api/account/archive_export/{export_id}", summary="Cancel account archive export job")
async def cancel_account_archive_export(export_id: str):
    job = _get_job(export_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export not found.")

    with _JOBS_LOCK:
        if job.status in {"done", "error", "cancelled"}:
            return {"status": "success", "job": job.to_public_dict()}
        job.cancel_requested = True
        job.message = "Cancelling export..."
        job.detail = "Waiting for the current file operation to stop."
        job.updated_at = int(time.time())

    return {"status": "success", "job": job.to_public_dict()}
