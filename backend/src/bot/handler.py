"""Bot message router — routes Feishu events to the appropriate handlers."""
from __future__ import annotations

import json
from typing import Any


def _extract_text(data: Any) -> str:
    """Extract plain text from a Feishu message event."""
    try:
        msg = data.event.message
        if msg.message_type == "text":
            content = json.loads(msg.content)
            return content.get("text", "").strip()
        # For other types (image, file, etc.) return empty string
        return ""
    except Exception:
        return ""


async def on_message(data: Any) -> None:
    """Handle im.message.receive_v1 events."""
    try:
        sender_id = data.event.sender.sender_id
        feishu_user_id = sender_id.open_id or sender_id.user_id or ""
        msg_id = data.event.message.message_id or ""
        text = _extract_text(data)

        if not feishu_user_id or not text:
            return

        from ..feishu_bot_ask.handler import handle_message
        await handle_message(feishu_user_id, text, msg_id)
    except Exception as exc:
        print(f"[BotHandler] on_message error: {exc}")


async def on_card_action(data: Any) -> None:
    """Handle card.action.trigger events."""
    try:
        open_id = data.event.operator.open_id or ""
        action_value = data.event.action.value or {}

        if not open_id:
            return

        from ..feishu_keyword_card.card_handler import handle_card_action
        await handle_card_action(open_id, action_value)
    except Exception as exc:
        print(f"[BotHandler] on_card_action error: {exc}")
