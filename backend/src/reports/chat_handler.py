"""Report chat — streaming Q&A grounded in the report and all its cited sources."""
from __future__ import annotations

import base64
import json
import os
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.handler import get_current_user
from ..db.models import Report, ReportChatMessage, ResearchTask, Question, User
from ..db.session import get_db, AsyncSessionLocal
from ..integrations.llm_client import LLMClient

router = APIRouter()

WILSON_LIB = Path(os.environ.get("COMPANY_LIB_PATH", os.environ.get("WILSON_LIB_PATH", str(Path.home() / "company_lib"))))

_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".gif": "image/gif", ".webp": "image/webp"}

_CHAT_SYSTEM = """你是针对该调研报告的专家问答助手。

你能访问以下内容：
1. 完整的调研报告正文（已在下方提供）
2. 报告引用的所有论文/专利/Web 素材（通过工具按需获取）
3. 报告中嵌入的架构图和示意图（图片已随消息发送）

可用工具：
- list_sources()：列出本报告所有引用素材的 stem 和标题
- get_source(stem)：获取指定素材的完整内容

工作方式：先阅读报告正文，如需了解某篇素材的细节，先调用 list_sources 确认 stem，再调用 get_source 获取全文。

【严格约束——必须遵守，不得违反】
1. 所有数据、参数、结论、技术陈述必须来自报告正文或通过工具获取的素材原文，必须注明来源文件名。
2. 素材中没有明确记载的数据、概念或陈述，一律不得推断、补全或编造。
3. 不确定或素材中未涉及的内容，必须直接回答"素材中未涉及，无法确认"，不得用"可能""一般来说""通常"等模糊表述替代。
4. 禁止使用任何训练知识补充素材中没有的内容，即使你认为该内容是常识或行业共识。
5. 引用具体数字时，必须同时给出来源文件名和所在章节或上下文，确保可溯源。

回答格式要求：
- 回答用中文，技术术语保留英文原文
- 每条关键陈述后标注来源，格式：（来源：文件名）
- 可以结合图片内容回答关于电路结构、架构设计的问题"""

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_sources",
            "description": "列出本报告所有引用素材的 stem 和标题，用于确认可以调用 get_source 的参数。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_source",
            "description": "获取指定素材的完整 Markdown 内容（论文/专利/Web 页面）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "stem": {
                        "type": "string",
                        "description": "素材的 stem（文件名不含扩展名），从 list_sources 的返回中获取。",
                    }
                },
                "required": ["stem"],
            },
        },
    },
]


def _find_md(stem_or_path: str) -> Path | None:
    p = Path(stem_or_path)
    for candidate in [p, WILSON_LIB / stem_or_path, WILSON_LIB / (stem_or_path + ".md")]:
        if candidate.exists():
            return candidate
    # Strip .md suffix if present, otherwise treat the whole input as the stem.
    # Do NOT use Path.stem — filenames like "paper_97.0%_Buck.md" have an
    # intermediate dot that makes Path.stem truncate at the wrong position.
    bare = stem_or_path[:-3] if stem_or_path.lower().endswith(".md") else stem_or_path
    bare_lower = bare.lower()
    for match in WILSON_LIB.rglob("*.md"):
        if match.stem.lower() == bare_lower and "/images/" not in str(match) and "\\images\\" not in str(match):
            return match
    return None


def _find_image(img_ref: str, md_dir: Path | None = None) -> Path | None:
    img_ref = re.sub(r'^/api/obsidian/img/', '', img_ref)
    img_ref = re.sub(r'\?.*$', '', img_ref)
    candidates = []
    if md_dir:
        candidates.append(md_dir / img_ref)
    candidates += [WILSON_LIB / img_ref, Path(img_ref)]
    for c in candidates:
        if c.exists() and c.suffix.lower() in _IMG_EXTS:
            return c
    name = Path(img_ref).name
    if name:
        for match in WILSON_LIB.rglob(name):
            if match.suffix.lower() in _IMG_EXTS:
                return match
    return None


def _img_to_block(img_path: Path) -> dict | None:
    try:
        from PIL import Image
        with Image.open(img_path) as im:
            w, h = im.size
            if w < 50 or h < 50:
                return None
    except Exception:
        if img_path.stat().st_size < 1024:
            return None
    mime = _MIME.get(img_path.suffix.lower(), "image/png")
    data = base64.b64encode(img_path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}


def _extract_images_from_md(content: str, md_path: Path | None = None) -> list[dict]:
    md_dir = md_path.parent if md_path else None
    seen: set[str] = set()
    blocks: list[dict] = []
    for m in re.finditer(r'!\[\[([^\]]+\.(png|jpg|jpeg|gif|webp))\]\]', content, re.IGNORECASE):
        ref = m.group(1).split("|")[0].strip()
        if ref in seen:
            continue
        seen.add(ref)
        img = _find_image(ref, md_dir)
        if img:
            block = _img_to_block(img)
            if block:
                blocks.append(block)
    for m in re.finditer(r'!\[[^\]]*\]\(([^)]+)\)', content):
        ref = m.group(1).strip()
        if ref in seen:
            continue
        seen.add(ref)
        img = _find_image(ref, md_dir)
        if img:
            block = _img_to_block(img)
            if block:
                blocks.append(block)
    return blocks


def _extract_wikilink_stems(content: str) -> list[str]:
    stems: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r'\[\[([^\]|\\]+?)(?:[\\|][^\]]+)?\]\]', content):
        stem = m.group(1).strip().rstrip("\\")
        if stem and stem not in seen and not stem.startswith("http"):
            seen.add(stem)
            stems.append(stem)
    return stems


def _get_source_title(md_path: Path) -> str:
    """从 MD frontmatter 或首行提取标题。"""
    try:
        text = md_path.read_text(encoding="utf-8", errors="ignore")
        # frontmatter title
        m = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', text, re.MULTILINE)
        if m:
            return m.group(1).strip()
        # 首个 # 标题
        m = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return md_path.stem


def _build_source_index(report_content: str) -> dict[str, Path]:
    """返回 stem -> Path 的映射，用于工具调用时快速查找。"""
    stems = _extract_wikilink_stems(report_content)
    index: dict[str, Path] = {}
    for stem in stems:
        md = _find_md(stem)
        if md:
            index[stem] = md
    return index


async def _get_report_and_check(report_id: int, user: User, db: AsyncSession) -> Report:
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if user.role != "admin":
        check = await db.execute(
            select(ResearchTask)
            .join(Question, ResearchTask.question_id == Question.id)
            .where(ResearchTask.id == report.task_id, Question.user_id == user.id)
        )
        if check.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Not your report")
    return report


# ── GET history ────────────────────────────────────────────────────────────────

@router.get("/reports/{report_id}/chat/history")
async def get_chat_history(
    report_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_report_and_check(report_id, user, db)
    result = await db.execute(
        select(ReportChatMessage)
        .where(
            ReportChatMessage.report_id == report_id,
            ReportChatMessage.user_id == user.id,
        )
        .order_by(ReportChatMessage.created_at)
    )
    msgs = result.scalars().all()
    return [{"role": m.role, "content": m.content, "created_at": m.created_at} for m in msgs]


# ── DELETE history ─────────────────────────────────────────────────────────────

@router.delete("/reports/{report_id}/chat/history")
async def clear_chat_history(
    report_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_report_and_check(report_id, user, db)
    from sqlalchemy import delete
    await db.execute(
        delete(ReportChatMessage).where(
            ReportChatMessage.report_id == report_id,
            ReportChatMessage.user_id == user.id,
        )
    )
    await db.commit()
    return {"ok": True}


# ── POST chat (SSE streaming) ──────────────────────────────────────────────────

# ── PDF parse ─────────────────────────────────────────────────────────────────

@router.post("/chat/parse-pdf")
async def parse_pdf(
    file: UploadFile = File(...),
    _user: User = Depends(get_current_user),
):
    """接收上传的 PDF，用 pymupdf4llm 转成 Markdown 文本返回。"""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只支持 PDF 文件")
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件过大（上限 50MB）")
    try:
        import pymupdf4llm
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        md_text = pymupdf4llm.to_markdown(tmp_path)
        Path(tmp_path).unlink(missing_ok=True)
        return {"text": md_text, "filename": file.filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF 解析失败: {e}")


class ChatRequest(BaseModel):
    message: str
    extra_images: list[dict] = []  # [{mime, data}] user-uploaded images


@router.post("/reports/{report_id}/chat")
async def report_chat(
    report_id: int,
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await _get_report_and_check(report_id, user, db)

    report_content = ""
    report_md_path = None
    if report.vault_path:
        rpath = Path(report.vault_path)
        if not rpath.is_absolute():
            rpath = WILSON_LIB / report.vault_path
        try:
            report_content = rpath.read_text(encoding="utf-8")
            report_md_path = rpath
        except Exception:
            pass

    # 构建素材索引（stem -> Path）
    source_index = _build_source_index(report_content)

    # 提取报告中的图片
    image_blocks = _extract_images_from_md(report_content, report_md_path)

    system = _CHAT_SYSTEM + "\n\n" + "═" * 60 + "\n【调研报告正文】\n" + "═" * 60 + "\n" + report_content

    # 加载历史
    hist_result = await db.execute(
        select(ReportChatMessage)
        .where(
            ReportChatMessage.report_id == report_id,
            ReportChatMessage.user_id == user.id,
        )
        .order_by(ReportChatMessage.created_at)
    )
    history = hist_result.scalars().all()

    oai_history: list[dict] = [
        {"role": m.role, "content": m.content} for m in history
    ]

    # 当前用户消息（多模态）
    # 用户上传的额外图片
    extra_image_blocks = [
        {"type": "image_url", "image_url": {"url": f"data:{img['mime']};base64,{img['data']}"}}
        for img in body.extra_images
        if img.get("mime") and img.get("data")
    ]

    if image_blocks or extra_image_blocks:
        user_content: list[dict] | str = (
            [{"type": "text", "text": body.message}] + image_blocks + extra_image_blocks
        )
    else:
        user_content = body.message

    # 持久化用户消息
    db.add(ReportChatMessage(
        report_id=report_id,
        user_id=user.id,
        role="user",
        content=body.message,
    ))
    await db.commit()

    llm = LLMClient(name="chat")

    async def stream_and_save():
        # DeepSeek 按用户要求使用 stream=False。SSE 仍保留，但每轮一次性
        # 返回完整文本，而不是伪造 token 流。
        messages: list[dict] = [{"role": "system", "content": system}]
        messages.extend(oai_history)
        messages.append({"role": "user", "content": user_content})
        full_reply = ""

        for _ in range(10):  # 最多 10 轮 tool call
            try:
                response = await llm.complete_response(
                    messages,
                    max_tokens=4096,
                    tools=_TOOLS,
                    tool_choice="auto",
                )
                if not response.choices:
                    raise RuntimeError("DeepSeek 返回空 choices")
                message = response.choices[0].message
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
                return

            text_reply = message.content or ""
            if text_reply:
                full_reply += text_reply
                yield f"data: {json.dumps({'delta': text_reply}, ensure_ascii=False)}\n\n"

            tool_calls = message.tool_calls or []
            if not tool_calls:
                yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
                async with AsyncSessionLocal() as save_db:
                    save_db.add(ReportChatMessage(
                        report_id=report_id,
                        user_id=user.id,
                        role="assistant",
                        content=full_reply,
                    ))
                    await save_db.commit()
                return

            assistant_tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ]

            messages.append({
                "role": "assistant",
                "content": text_reply or None,
                "tool_calls": assistant_tool_calls,
            })

            for tc in assistant_tool_calls:
                fn = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except Exception:
                    args = {}

                if fn == "list_sources":
                    entries = []
                    for stem, md_path in source_index.items():
                        title = _get_source_title(md_path)
                        entries.append(f"- stem: `{stem}`  标题: {title}")
                    result_text = "本报告引用素材列表：\n" + "\n".join(entries) if entries else "（无引用素材）"
                    yield f"data: {json.dumps({'tool': 'list_sources'}, ensure_ascii=False)}\n\n"

                elif fn == "get_source":
                    stem = args.get("stem", "")
                    md_path = source_index.get(stem)
                    if md_path is None:
                        # 模糊匹配
                        for s, p in source_index.items():
                            if stem in s or s in stem:
                                md_path = p
                                break
                    if md_path:
                        try:
                            result_text = md_path.read_text(encoding="utf-8", errors="ignore")
                        except Exception as e:
                            result_text = f"读取失败: {e}"
                    else:
                        result_text = f"未找到素材: {stem}"
                    yield f"data: {json.dumps({'tool': 'get_source', 'stem': stem}, ensure_ascii=False)}\n\n"

                else:
                    result_text = f"未知工具: {fn}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_text,
                })

        # 超过最大轮次
        yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
        if full_reply:
            async with AsyncSessionLocal() as save_db:
                save_db.add(ReportChatMessage(
                    report_id=report_id,
                    user_id=user.id,
                    role="assistant",
                    content=full_reply,
                ))
                await save_db.commit()

    return StreamingResponse(
        stream_and_save(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
