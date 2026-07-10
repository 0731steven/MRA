"""Step 10 — 推送飞书完成通知卡片（含 Web 报告链接）。"""
from __future__ import annotations
import os

from ..context import PipelineContext

FEISHU_ENABLED = os.environ.get("FEISHU_ENABLED", "false").lower() == "true"
APP_HOST = os.environ.get("APP_HOST", "localhost")
APP_PORT = os.environ.get("APP_PORT", "8101")


async def run(ctx: PipelineContext, feishu_user_id: str | None = None) -> None:
    if not ctx.report_path:
        return

    kb_count = sum(1 for b in ctx.context_blocks if str(b.get("source_type", "")).startswith("kb"))
    me_count = sum(1 for b in ctx.context_blocks if b.get("source_type") == "me")
    web_count = sum(1 for b in ctx.context_blocks if b.get("source_type") == "web")

    report_url = f"http://{APP_HOST}:{APP_PORT}/reports/{ctx.report_id or ctx.task_id}"

    if FEISHU_ENABLED and feishu_user_id:
        await _push_feishu(feishu_user_id, ctx, report_url, kb_count, me_count, web_count)
    else:
        # 开发模式：仅打印
        print(f"[Step 10] 报告已生成: {ctx.report_path}")
        print(f"[Step 10] KB {kb_count} 块 / ME {me_count} 块 / Web {web_count} 块")
        print(f"[Step 10] Web 查看: {report_url}")


async def _push_feishu(
    feishu_user_id: str,
    ctx: PipelineContext,
    report_url: str,
    kb_count: int,
    me_count: int,
    web_count: int,
) -> None:
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        card_json = {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"content": "✅ 调研报告已生成", "tag": "plain_text"}},
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": (
                            f"**问题：** {ctx.clarified_text or ' '.join(ctx.keywords)}\n"
                            f"**报告类型：** {ctx.report_type}\n"
                            f"**证据：** KB {kb_count} 块 / ME {me_count} 块 / Web {web_count} 块\n"
                            f"**档位：** {ctx.tier}"
                        ),
                        "tag": "lark_md",
                    },
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"content": "📄 查看报告", "tag": "plain_text"},
                            "type": "primary",
                            "url": report_url,
                        }
                    ],
                },
            ],
        }

        import json
        client = lark.Client.builder() \
            .app_id(os.environ.get("FEISHU_APP_ID", "")) \
            .app_secret(os.environ.get("FEISHU_APP_SECRET", "")) \
            .build()

        req = (
            CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(feishu_user_id)
                .msg_type("interactive")
                .content(json.dumps(card_json))
                .build()
            )
            .build()
        )
        await client.im.v1.message.acreate(req)
    except Exception as e:
        print(f"[Step 10] 飞书推送失败: {e}")
