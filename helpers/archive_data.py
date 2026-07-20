import json
import os
import time
import threading
from typing import Any

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_PLUGIN_DIR, "data")
_ARCHIVE_FILE = os.path.join(_DATA_DIR, "archive.json")
_lock = threading.Lock()


def _ensure_data_dir() -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)


def _read_json(path: str) -> Any:
    """Read JSON from disk. Caller must hold _lock."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _write_json(path: str, data: Any) -> None:
    """Atomically write JSON to disk. Caller must hold _lock."""
    _ensure_data_dir()
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


# ── Archive operations ────────────────────────────────────────────


def _chat_exists(chat_id: str) -> bool:
    """True if the chat still exists on disk. Used to prune ghost archive records whose chat was
    deleted/reaped elsewhere — otherwise a stale entry reappears in the archive list after a delete."""
    try:
        from helpers.persist_chat import get_chat_folder_path
        return os.path.isdir(get_chat_folder_path(chat_id))
    except Exception:
        return os.path.isdir(os.path.join("/a0", "usr", "chats", chat_id))


def get_archived() -> dict[str, dict[str, Any]]:
    """Return dict of {chat_id: {archived_at: float, name: str}}. Self-healing: entries whose chat no
    longer exists are pruned (and the file rewritten) so a deleted chat can't reappear as a ghost."""
    with _lock:
        raw = _read_json(_ARCHIVE_FILE)
        if not isinstance(raw, dict):
            return {}
        live = {cid: meta for cid, meta in raw.items() if _chat_exists(cid)}
        if len(live) != len(raw):
            _write_json(_ARCHIVE_FILE, live)
        return live


def _apply_reap_protect(chat_id: str, archived: bool) -> None:
    """Archive = keep the chat from the 24h API-chat reaper; unarchive = restore normal lifetime.
    Lazy import so this helper stays standalone-importable; best-effort (never breaks archiving)."""
    try:
        from usr.plugins.chat_archive.helpers import reap_protect
        (reap_protect.protect if archived else reap_protect.unprotect)(chat_id)
    except Exception:
        pass


def archive_chat(chat_id: str, name: str = "") -> float:
    """Archive a chat. Returns the archived_at timestamp."""
    with _lock:
        raw = _read_json(_ARCHIVE_FILE)
        if not isinstance(raw, dict):
            raw = {}
        ts = time.time()
        raw[chat_id] = {"archived_at": ts, "name": name}
        _write_json(_ARCHIVE_FILE, raw)
    _apply_reap_protect(chat_id, True)   # archived -> keep from the reaper
    return ts


def unarchive_chat(chat_id: str) -> bool:
    """Remove a chat from the archive. Returns True if it was archived."""
    with _lock:
        raw = _read_json(_ARCHIVE_FILE)
        found = isinstance(raw, dict) and chat_id in raw
        if found:
            del raw[chat_id]
            _write_json(_ARCHIVE_FILE, raw)
    if found:
        _apply_reap_protect(chat_id, False)   # unarchived -> restore normal lifetime
    return found


def is_archived(chat_id: str) -> bool:
    """Check if a chat is archived."""
    return chat_id in get_archived()


def delete_archived(chat_id: str) -> bool:
    """Permanently remove a chat from archive records. Returns True if found."""
    return unarchive_chat(chat_id)
