"""Web Ask — WebSocket-based interactive ask endpoint.

消息协议（均为 JSON，type 字段区分）：

Client → Server:
  ask              { text, tier? }
  clarify_reply    { question_id, text }
  confirm_keywords { question_id, keywords, tier }
  revise_keywords  { question_id, keywords, tier }   # 修改后直接确认
  cancel           { question_id }

Server → Client:
  clarify          { question_id, message }
  mra_params       { question_id, report_type, research_params, sub_questions, keywords, tier }
  progress         { question_id, task_id, step, message }
  done             { question_id, task_id, report_id }
  error            { question_id?, message }
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select

from ..auth.handler import SECRET_KEY, ALGORITHM
from ..db.session import AsyncSessionLocal, get_db
from ..db.models import Question, ResearchTask, Report, User
from ..research_pipeline.steps.step1_clarify import clarify, extract_keywords

router = APIRouter()

# question_id → asyncio.Queue  (orchestrator 写进度，WS handler 读出推送)
_ws_queues: dict[int, asyncio.Queue] = {}


def get_ws_queue(question_id: int) -> asyncio.Queue | None:
    return _ws_queues.get(question_id)


async def _auth_token(token: str) -> User | None:
    import jwt as _jwt
    try:
        payload = _jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except Exception:
        return None
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()


async def _send(ws: WebSocket, msg: dict) -> None:
    try:
        await ws.send_text(json.dumps(msg, ensure_ascii=False, default=str))
    except Exception:
        pass


async def _get_report_id(task_id: int) -> int | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Report).where(Report.task_id == task_id))
        r = result.scalar_one_or_none()
        return r.id if r else None


@router.websocket("/ws/ask")
async def ws_ask(ws: WebSocket, token: str = Query(default="")):
    user = await _auth_token(token)
    if user is None:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()

    question_id: int | None = None
    clarify_history: list[dict] = []  # accumulated multi-turn: [{role, content}, ...]
    queue: asyncio.Queue | None = None

    async def _pump_queue():
        """Forward progress messages from orchestrator to this WebSocket."""
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                if msg is None:
                    break
                await _send(ws, msg)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break

    pump_task: asyncio.Task | None = None

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                await _send(ws, {"type": "error", "message": "Invalid JSON"})
                continue

            mtype = msg.get("type")

            # ── ask: 首次提问 ─────────────────────────────────────────────
            if mtype == "ask":
                text = (msg.get("text") or "").strip()
                tier = msg.get("tier") or "normal"
                if not text:
                    await _send(ws, {"type": "error", "message": "text required"})
                    continue

                # 创建 Question 记录
                async with AsyncSessionLocal() as db:
                    q = Question(
                        user_id=user.id,
                        tier=tier,
                        raw_text=text,
                        status="created",
                    )
                    db.add(q)
                    await db.commit()
                    await db.refresh(q)
                    question_id = q.id

                clarify_history = []

                # 注册进度队列
                queue = asyncio.Queue()
                _ws_queues[question_id] = queue

                # LLM 判断清晰度
                async with AsyncSessionLocal() as db:
                    q_obj = await db.get(Question, question_id)
                    if q_obj:
                        q_obj.status = "step1_clarify"
                        await db.commit()

                # Build history with user's first message
                clarify_history.append({"role": "user", "content": text})
                result = await clarify(text, [])

                if not result.get("is_valid", True):
                    # 无效输入：回复提示，删除刚创建的 Question，不进入流水线
                    async with AsyncSessionLocal() as db:
                        q_obj = await db.get(Question, question_id)
                        if q_obj:
                            await db.delete(q_obj)
                            await db.commit()
                    _ws_queues.pop(question_id, None)
                    question_id = None
                    clarify_history = []
                    await _send(ws, {
                        "type": "invalid",
                        "message": result.get("reply", "请输入 IC 设计相关的调研问题。"),
                    })
                elif not result.get("is_clear"):
                    clarify_qs = result.get("clarification_questions", [])
                    clarify_msg = "\n".join(clarify_qs) if isinstance(clarify_qs, list) else str(clarify_qs)
                    clarify_history.append({"role": "assistant", "content": clarify_msg})
                    async with AsyncSessionLocal() as db:
                        q_obj = await db.get(Question, question_id)
                        if q_obj:
                            q_obj.status = "awaiting_clarify"
                            await db.commit()
                    await _send(ws, {
                        "type": "clarify",
                        "question_id": question_id,
                        "message": clarify_msg,
                    })
                else:
                    await _proceed_to_keywords(ws, question_id, text, clarify_history, tier)

            # ── clarify_reply: 用户回复追问 ───────────────────────────────
            elif mtype == "clarify_reply":
                qid = msg.get("question_id") or question_id
                reply_text = (msg.get("text") or "").strip()
                if not qid or not reply_text:
                    await _send(ws, {"type": "error", "message": "question_id and text required"})
                    continue

                # Append user reply to accumulated history
                clarify_history.append({"role": "user", "content": reply_text})

                # 读原始问题
                async with AsyncSessionLocal() as db:
                    q_obj = await db.get(Question, qid)
                    if q_obj is None:
                        await _send(ws, {"type": "error", "message": "question not found"})
                        continue
                    raw_text = q_obj.raw_text
                    tier = q_obj.tier

                # Build full clarified text from accumulated user turns
                user_turns = [h["content"] for h in clarify_history if h["role"] == "user"]
                full_text = raw_text
                if len(user_turns) > 1:
                    # additional replies beyond the first question
                    extras = user_turns[1:]
                    full_text = raw_text + "\n补充信息：" + "；".join(extras)

                is_skip = reply_text in ("跳过", "skip", "跳过，直接继续")

                if not is_skip:
                    # Pass only assistant turns as context; full_text already aggregates all user input
                    assistant_history = [h for h in clarify_history if h["role"] == "assistant"]
                    result = await clarify(full_text, assistant_history)
                else:
                    result = {"is_clear": True}

                if not result.get("is_clear"):
                    clarify_qs = result.get("clarification_questions", [])
                    clarify_msg = "\n".join(clarify_qs) if isinstance(clarify_qs, list) else str(clarify_qs)
                    clarify_history.append({"role": "assistant", "content": clarify_msg})
                    await _send(ws, {
                        "type": "clarify",
                        "question_id": qid,
                        "message": clarify_msg,
                    })
                else:
                    async with AsyncSessionLocal() as db:
                        q_obj = await db.get(Question, qid)
                        if q_obj:
                            q_obj.clarified_text = full_text
                            q_obj.status = "step1_keywords"
                            await db.commit()
                    await _proceed_to_keywords(ws, qid, full_text, clarify_history, tier)

            # ── confirm_keywords / revise_keywords: 用户确认关键词 ────────
            elif mtype in ("confirm_keywords", "revise_keywords"):
                qid = msg.get("question_id") or question_id
                keywords = msg.get("keywords") or []
                tier = msg.get("tier") or "normal"
                sub_questions = msg.get("sub_questions")  # may be None if not edited
                report_type = msg.get("report_type")
                research_params = msg.get("research_params")
                if not qid or not keywords:
                    await _send(ws, {"type": "error", "message": "question_id and keywords required"})
                    continue

                async with AsyncSessionLocal() as db:
                    q_obj = await db.get(Question, qid)
                    if q_obj is None:
                        await _send(ws, {"type": "error", "message": "question not found"})
                        continue
                    q_obj.tier = tier
                    q_obj.status = "running"
                    if sub_questions is not None:
                        q_obj.sub_questions_json = json.dumps(sub_questions, ensure_ascii=False)
                    if report_type in {"market", "product", "competitive", "technology"}:
                        q_obj.report_type = report_type
                    if isinstance(research_params, dict):
                        q_obj.research_params_json = json.dumps(research_params, ensure_ascii=False)
                    await db.commit()

                # 确保进度队列已存在
                if qid not in _ws_queues:
                    queue = asyncio.Queue()
                    _ws_queues[qid] = queue
                else:
                    queue = _ws_queues[qid]

                # 启动进度泵（如未启动）
                if pump_task is None or pump_task.done():
                    pump_task = asyncio.create_task(_pump_queue())

                # 启动流水线
                from ..research_pipeline.scheduler import start_pipeline
                task = await start_pipeline(qid, keywords)

                await _send(ws, {
                    "type": "progress",
                    "question_id": qid,
                    "task_id": task.id,
                    "step": "step3_local_search",
                    "message": "流水线已启动，正在搜索本地文献...",
                })

            # ── cancel ───────────────────────────────────────────────────
            elif mtype == "cancel":
                qid = msg.get("question_id") or question_id
                if not qid:
                    continue
                async with AsyncSessionLocal() as db:
                    q_obj = await db.get(Question, qid)
                    if q_obj:
                        q_obj.status = "cancelled"
                        await db.commit()
                    # 找到对应 task 并取消
                    t_result = await db.execute(
                        select(ResearchTask).where(ResearchTask.question_id == qid)
                    )
                    task = t_result.scalar_one_or_none()
                    if task:
                        task.status = "cancelled"
                        task.finished_at = datetime.now(timezone.utc)
                        await db.commit()
                        from ..research_pipeline.scheduler import _running
                        running = _running.pop(task.id, None)
                        if running and not running.done():
                            running.cancel()

                _ws_queues.pop(qid, None)
                await _send(ws, {"type": "error", "question_id": qid, "message": "已取消"})

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await _send(ws, {"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        if pump_task and not pump_task.done():
            pump_task.cancel()
        if question_id:
            _ws_queues.pop(question_id, None)


async def _proceed_to_keywords(
    ws: WebSocket,
    question_id: int,
    text: str,
    history: list[dict],
    tier: str,
) -> None:
    """提取关键词并发送 keywords 消息让用户确认。"""
    async with AsyncSessionLocal() as db:
        q_obj = await db.get(Question, question_id)
        if q_obj:
            q_obj.status = "step1_keywords"
            await db.commit()

    # Build clarification context from all user turns after the first (original) question
    user_turns = [h["content"] for h in history if h.get("role") == "user"]
    context_str = "；".join(user_turns[1:]) if len(user_turns) > 1 else ""
    result = await extract_keywords(text, context_str)

    sub_questions = result.get("sub_questions", [])
    keywords = result.get("keywords", [])
    report_type = result.get("report_type", "market")
    research_params = result.get("params", {})

    async with AsyncSessionLocal() as db:
        q_obj = await db.get(Question, question_id)
        if q_obj:
            q_obj.sub_questions_json = json.dumps(sub_questions, ensure_ascii=False)
            q_obj.keywords_draft_json = json.dumps(keywords, ensure_ascii=False)
            q_obj.report_type = report_type
            q_obj.research_params_json = json.dumps(research_params, ensure_ascii=False)
            q_obj.status = "awaiting_keyword"
            await db.commit()

    await _send(ws, {
        "type": "mra_params",
        "question_id": question_id,
        "report_type": report_type,
        "research_params": research_params,
        "sub_questions": sub_questions,
        "keywords": keywords,
        "tier": tier,
    })
