"""Step 1 — MRA 意图澄清、报告分类与参数提取。

handle_question() 流程（操作 Question，不创建 ResearchTask）：
  1. clarify()   — LLM 判断问题是否清晰，返回追问内容
  2. extract()   — 问题清晰后，LLM 提取关键词 + 分解子问题
"""
from __future__ import annotations

from ...integrations.llm_client import LLMClient, ChatMessage

_CLARIFY_SYSTEM = """你是南芯半导体 Market Research Assistant，只处理半导体市场、产品、竞品和技术调研请求。

首先判断用户输入是否为有效的技术调研请求：

无效输入（满足任一条即为无效）：
- 闲聊、问候、测试（如"你好"、"你能做什么"、"hello"、"test"）
- 与半导体、电子产品、应用市场、竞品或相关技术无关的问题
- 纯粹的概念解释请求（如"什么是电容"），而非调研方向

有效输入：有明确市场、产品、公司、应用或技术研究对象的问题。

若为无效输入，输出：
{
  "is_valid": false,
  "reply": "简短友好的提示（告知只能处理IC设计调研问题，请重新提问）"
}

若为有效输入，再评估清晰度，输出：
{
  "is_valid": true,
  "is_clear": true/false,
  "reason": "简短说明",
  "clarification_questions": []
}

清晰标准：
- 有明确研究对象（如 LDO、ADC、GaN HEMT 驱动）
- 有目标参数或研究方向（如 PSRR、功耗、线性度）
- 简单问题不要求工艺节点等细节

is_clear=false 时，clarification_questions 给出 1-3 条追问（中文）。
输出纯 JSON，不加 markdown 代码块。"""

_KEYWORDS_SYSTEM = """你是南芯半导体的市场研究助手。

根据用户问题（含澄清补充），判断报告类型、提取研究参数和关键词，并分解子问题。

报告类型只能是：market、product、competitive、technology。

关键词要求：
- 英文为主（IEEE 搜索需要英文）
- 3-8 个，覆盖核心概念、关键参数、电路类型
- 不含停用词

子问题要求：
- 分解为 2-4 个具体可检索的子问题
- ID 格式：Q1, Q2, Q3 ...

输出 JSON（不加 markdown 代码块）：
{
  "report_type": "competitive",
  "params": {
    "target_company": "MPS",
    "target_market": "电源管理",
    "competitors": ["MPS"],
    "time_range": "近两年",
    "focus_keywords": ["AI服务器", "电源管理"]
  },
  "sub_questions": [
    {"id": "Q1", "text": "子问题描述（中文）"},
    {"id": "Q2", "text": "子问题描述（中文）"}
  ],
  "keywords": ["keyword1", "keyword2", "keyword3"]
}"""


def classify_by_rules(text: str) -> str:
    lower = text.lower()
    if any(k in lower for k in ("市场规模", "tam", "sam", "cagr", "市场空间", "行业分析", "渗透率")):
        return "market"
    if any(k in lower for k in ("参数对比", "产品参数", "datasheet", "规格", "料号", "选型")):
        return "product"
    if any(k in lower for k in ("竞品", "竞争对手", "vs", "对比", "财报", "竞争格局", "最新动作")):
        return "competitive"
    return "technology"


def _fallback_extract(text: str) -> dict:
    import re
    report_type = classify_by_rules(text)
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9+._/-]*|[\u4e00-\u9fff]{2,8}", text)
    stop = {"帮我", "一下", "分析", "研究", "报告", "最新", "如何", "什么", "是否", "以及"}
    keywords = [t for t in tokens if t.lower() not in stop][:8]
    if not keywords:
        keywords = [text[:30]]
    defaults = {
        "market": ["市场规模、增速和边界是什么？", "主要应用与竞争格局如何？", "南芯有哪些进入机会和风险？"],
        "product": ["目标产品的关键规格和应用定位是什么？", "与南芯及主要竞品相比有哪些功能差距？", "南芯应如何定位或补齐产品？"],
        "competitive": ["目标公司的财务与经营走势如何？", "近期新品、技术和市场动作是什么？", "这些变化对南芯有何影响，应如何应对？"],
        "technology": ["技术路线和关键指标是什么？", "产业成熟度、采用节奏及竞品布局如何？", "该技术与南芯产品线有何关联？"],
    }
    return {
        "report_type": report_type,
        "params": {"focus_keywords": keywords, "time_range": "近两年"},
        "sub_questions": [{"id": f"Q{i + 1}", "text": q} for i, q in enumerate(defaults[report_type])],
        "keywords": keywords,
    }


async def clarify(question_text: str, history: list[dict] | None = None) -> dict:
    """
    评估问题有效性和清晰度。
    history: accumulated conversation so far (without current question_text, which is appended here).
    返回 {"is_valid": bool, "reply": str, "is_clear": bool, "reason": str, "clarification_questions": list[str]}
    """
    llm = LLMClient(step=1)
    messages: list[ChatMessage] = []

    if history:
        for h in history:
            role = h.get("role", "user")
            content = h.get("content", "")
            if isinstance(content, list):
                content = "\n".join(content)
            messages.append(ChatMessage(role=role, content=str(content)))

    # Only append question_text if it's not already the last user message
    if not messages or messages[-1].role != "user" or messages[-1].content != question_text:
        messages.append(ChatMessage(role="user", content=question_text))

    try:
        result = await llm.chat_json(messages, system=_CLARIFY_SYSTEM, max_tokens=4096)
    except Exception:
        result = {"is_valid": True, "is_clear": True, "reason": "parse error fallback", "clarification_questions": []}

    cqs = result.get("clarification_questions", [])
    if isinstance(cqs, str):
        cqs = [cqs] if cqs else []

    return {
        "is_valid": bool(result.get("is_valid", True)),
        "reply": result.get("reply", ""),
        "is_clear": bool(result.get("is_clear", True)),
        "reason": result.get("reason", ""),
        "clarification_questions": cqs,
    }


async def extract_keywords(question_text: str, clarification_context: str = "") -> dict:
    """
    提取关键词 + 分解子问题。
    question_text: 原始或澄清后的完整问题
    clarification_context: 澄清对话的补充内容（纯文本）
    返回 {"sub_questions": [...], "keywords": [...]}
    """
    llm = LLMClient(step=1)
    if clarification_context:
        full_text = f"原始问题：{question_text}\n澄清补充：{clarification_context}"
    else:
        full_text = question_text

    messages = [ChatMessage(role="user", content=full_text)]
    try:
        result = await llm.chat_json(messages, system=_KEYWORDS_SYSTEM, max_tokens=2048)
    except Exception:
        result = {
            "sub_questions": [{"id": "Q1", "text": question_text}],
            "keywords": question_text.split()[:6],
        }

    fallback = _fallback_extract(full_text)
    report_type = result.get("report_type")
    if report_type not in {"market", "product", "competitive", "technology"}:
        report_type = fallback["report_type"]
    params = result.get("params") if isinstance(result.get("params"), dict) else fallback["params"]
    sub_questions = result.get("sub_questions") if isinstance(result.get("sub_questions"), list) else []
    keywords = result.get("keywords") if isinstance(result.get("keywords"), list) else []
    return {
        "report_type": report_type,
        "params": params,
        "sub_questions": sub_questions or fallback["sub_questions"],
        "keywords": [str(k) for k in keywords if str(k).strip()] or fallback["keywords"],
    }
