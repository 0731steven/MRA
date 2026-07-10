"""Tests for bot/handler.py routing logic.

Verifies that:
- on_message extracts text and dispatches to feishu_bot_ask.handler.handle_message
- on_card_action extracts action_value and dispatches to feishu_keyword_card.card_handler.handle_card_action

Both tests use simple mock objects instead of real lark_oapi event payloads.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def _make_message_event(open_id: str, text: str, msg_id: str = "msg_001") -> MagicMock:
    """Build a minimal im.message.receive_v1 event mock."""
    import json

    event = MagicMock()
    event.event.sender.sender_id.open_id = open_id
    event.event.sender.sender_id.user_id = ""
    event.event.message.message_id = msg_id
    event.event.message.message_type = "text"
    event.event.message.content = json.dumps({"text": text})
    return event


def _make_card_event(open_id: str, action_value: dict) -> MagicMock:
    """Build a minimal card.action.trigger event mock."""
    event = MagicMock()
    event.event.operator.open_id = open_id
    event.event.action.value = action_value
    return event


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_on_message_routes_to_handle_message() -> None:
    """on_message should call feishu_bot_ask.handler.handle_message with correct args."""
    from src.bot.handler import on_message

    mock_handle = AsyncMock()
    event = _make_message_event("ou_user_abc", "LDO PSRR 怎么提高", "msg_123")

    with patch("src.feishu_bot_ask.handler.handle_message", mock_handle):
        await on_message(event)

    mock_handle.assert_awaited_once_with("ou_user_abc", "LDO PSRR 怎么提高", "msg_123")


async def test_on_message_ignores_empty_text() -> None:
    """on_message should not call handle_message when text is empty."""
    from src.bot.handler import on_message

    mock_handle = AsyncMock()
    import json
    event = _make_message_event("ou_user_abc", "", "msg_124")

    with patch("src.feishu_bot_ask.handler.handle_message", mock_handle):
        await on_message(event)

    mock_handle.assert_not_called()


async def test_on_card_action_routes_to_handle_card_action() -> None:
    """on_card_action should call feishu_keyword_card.card_handler.handle_card_action."""
    from src.bot.handler import on_card_action

    mock_handle = AsyncMock()
    action_value = {"action": "confirm", "question_id": "42", "tier": "normal"}
    event = _make_card_event("ou_user_abc", action_value)

    with patch("src.feishu_keyword_card.card_handler.handle_card_action", mock_handle):
        await on_card_action(event)

    mock_handle.assert_awaited_once_with("ou_user_abc", action_value)
