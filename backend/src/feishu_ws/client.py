"""Feishu WebSocket long-connection client.

Registers two event handlers:
  - im.message.receive_v1  → message handler (user text messages)
  - card.action.trigger    → card action handler (button callbacks)

The WS client runs in a background thread via asyncio.to_thread so it does not
block the FastAPI event loop.
"""
from __future__ import annotations

import asyncio
import os
from typing import Callable, Awaitable, Any

import lark_oapi as lark

_client: lark.ws.Client | None = None


_main_loop: asyncio.AbstractEventLoop | None = None


def build_client(
    message_handler: Callable[..., Awaitable[None]],
    card_handler: Callable[..., Awaitable[None]],
) -> lark.ws.Client:
    """Build a WS client with both event handlers registered."""

    def _wrap(async_fn: Callable[..., Awaitable[None]]) -> Callable[..., None]:
        """Wrap an async handler so lark-oapi (sync) can call it."""
        def _inner(data: Any) -> None:
            if _main_loop is not None and _main_loop.is_running():
                asyncio.run_coroutine_threadsafe(async_fn(data), _main_loop)
            else:
                print(f"[FeishuWS] main loop not available, dropping event")
        return _inner

    dispatcher = (
        lark.EventDispatcherHandler.builder("", "", lark.LogLevel.ERROR)
        .register_p2_im_message_receive_v1(_wrap(message_handler))
        .register_p2_card_action_trigger(_wrap(card_handler))
        .build()
    )

    return lark.ws.Client(
        app_id=os.environ.get("FEISHU_APP_ID", ""),
        app_secret=os.environ.get("FEISHU_APP_SECRET", ""),
        event_handler=dispatcher,
        log_level=lark.LogLevel.ERROR,
    )


async def start(
    message_handler: Callable[..., Awaitable[None]],
    card_handler: Callable[..., Awaitable[None]],
) -> None:
    """Start the WS client in a background thread with its own event loop."""
    import threading
    global _client, _main_loop

    _main_loop = asyncio.get_running_loop()
    _client = build_client(message_handler, card_handler)

    def _run_in_thread() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            _client.start()
        finally:
            loop.close()

    t = threading.Thread(target=_run_in_thread, daemon=True, name="feishu-ws")
    t.start()
