from helpers.api import ApiHandler, Input, Output, Request, Response
from usr.plugins.chat_archive.helpers.archive_data import unarchive_chat


class UnarchiveChat(ApiHandler):
    """Restore an archived chat back to the sidebar."""

    async def process(self, input: Input, request: Request) -> Output:
        chat_id = input.get("chat_id", "")
        if not chat_id:
            return Response("Missing chat_id", 400)

        found = unarchive_chat(chat_id)

        # Trigger sidebar refresh so the restored chat reappears
        if found:
            try:
                from helpers.state_monitor_integration import mark_dirty_all
                mark_dirty_all(reason="chat_archive.unarchive")
            except ImportError:
                pass

        return {
            "ok": True,
            "chat_id": chat_id,
            "was_archived": found,
        }
