"""Keep-from-reaping. Archiving a chat sets its API-chat ``lifetime_hours`` to 0, so Agent Zero's
hourly "expired API chat" cleanup (extensions/python/job_loop/_20_cleanup_expired_api_chats.py)
SKIPS it — the framework already treats ``lifetime_hours <= 0`` (and ``None``) as "never reap". We
only flip that data field through the framework's own ``AgentContext`` API; NO core code is changed.

Coordinated with the favorite_chats plugin via SHARED context-data keys, so a chat protected by BOTH
archive AND favorite keeps its protection until the LAST mark is removed (un-doing one never strips
the other). Web-UI chats (which carry no ``lifetime_hours``) are already never reaped; this matters
for API-created chats, which default to a 24h lifetime. Best-effort: never raises into the caller."""
from __future__ import annotations

REASON = "archive"
# Shared with favorite_chats (same string keys on the context) so the two plugins coordinate.
# NB: NO leading underscore — Agent Zero's chat serializer (persist_chat._serialize_context) drops
# every data key starting with "_", so an underscore-prefixed key would never survive a restart.
KEEP_REASONS = "keep_reap_reasons"        # list of active protections, e.g. ["favorite", "archive"]
KEEP_ORIG = "keep_reap_orig_lifetime"     # the lifetime to restore once the LAST mark is removed
LIFETIME = "lifetime_hours"


def _ctx(chat_id: str):
    try:
        from agent import AgentContext
        return AgentContext.get(chat_id)
    except Exception:
        return None


def _persist(ctx) -> None:
    try:
        from helpers import persist_chat
        persist_chat.save_tmp_chat(ctx)
    except Exception:
        pass


def protect(chat_id: str) -> None:
    """Add this chat's <REASON> mark: on the FIRST mark, stash the original lifetime; then set
    lifetime to 0 so the reaper skips it."""
    try:
        ctx = _ctx(chat_id)
        if ctx is None:
            return
        reasons = list(ctx.get_data(KEEP_REASONS) or [])
        if not reasons:
            ctx.set_data(KEEP_ORIG, ctx.get_data(LIFETIME))   # remember to restore later
        if REASON not in reasons:
            reasons.append(REASON)
        ctx.set_data(KEEP_REASONS, reasons)
        ctx.set_data(LIFETIME, 0)
        _persist(ctx)
    except Exception:
        pass


def unprotect(chat_id: str) -> None:
    """Remove this chat's <REASON> mark. Re-arm the reaper (restore the original lifetime) ONLY when
    no other mark remains, so un-doing one protection never strips the other."""
    try:
        ctx = _ctx(chat_id)
        if ctx is None:
            return
        reasons = list(ctx.get_data(KEEP_REASONS) or [])
        if REASON in reasons:
            reasons.remove(REASON)
        if reasons:
            ctx.set_data(KEEP_REASONS, reasons)               # still protected by the other mark
        else:
            ctx.set_data(LIFETIME, ctx.get_data(KEEP_ORIG))   # restore (None, or the original hours)
            ctx.set_data(KEEP_REASONS, None)
            ctx.set_data(KEEP_ORIG, None)
        _persist(ctx)
    except Exception:
        pass
