"""Builds the keyword-confirmation interactive card for Feishu."""
from __future__ import annotations


def build_keyword_card(
    question_id: int,
    raw_text: str,
    sub_questions: list[dict],
    keywords: list[str],
    tier: str = "normal",
    report_type: str = "market",
) -> dict:
    """Return the Feishu card JSON for keyword confirmation."""

    sub_q_lines = "\n".join(
        f"  {q.get('id', f'Q{i+1}')}: {q.get('text', '')}"
        for i, q in enumerate(sub_questions)
    )
    kw_display = "、".join(keywords) if keywords else "（无）"

    report_labels = {"market": "📊 市场研究", "product": "📦 产品研究", "competitive": "⚔️ 竞品分析", "technology": "🔬 技术研究"}
    card_content = (
        f"**原始问题：** {raw_text}\n\n"
        f"**报告类型：** {report_labels.get(report_type, report_type)}\n\n"
        f"**分解子问题：**\n{sub_q_lines}\n\n"
        f"**提取关键词：** {kw_display}"
    )

    tier_options = [
        {"text": {"tag": "plain_text", "content": "⚡ quick（快速）"}, "value": "quick"},
        {"text": {"tag": "plain_text", "content": "🔍 normal（标准）"}, "value": "normal"},
        {"text": {"tag": "plain_text", "content": "🔬 deep（深度）"}, "value": "deep"},
    ]

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "🔍 关键词确认", "tag": "plain_text"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"content": card_content, "tag": "lark_md"},
            },
            {
                "tag": "div",
                "text": {"content": "**选择调研档位：**", "tag": "lark_md"},
            },
            {
                "tag": "select_static",
                "placeholder": {"content": "选择档位（默认 normal）", "tag": "plain_text"},
                "value": {"action": "set_tier", "question_id": str(question_id)},
                "options": tier_options,
                "initial_option": tier,
            },
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"content": "✅ 确认", "tag": "plain_text"},
                        "type": "primary",
                        "value": {
                            "action": "confirm",
                            "question_id": str(question_id),
                            "tier": tier,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"content": "✏️ 修改关键词", "tag": "plain_text"},
                        "type": "default",
                        "value": {
                            "action": "revise",
                            "question_id": str(question_id),
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"content": "❌ 取消", "tag": "plain_text"},
                        "type": "danger",
                        "value": {
                            "action": "cancel",
                            "question_id": str(question_id),
                        },
                    },
                ],
            },
        ],
    }
