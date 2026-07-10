import asyncio
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sa_delete, outerjoin, text

from ..db.session import get_db
from ..db.models import ResearchTask, Question, User, Report, GateResult, PendingDocument
from ..auth.handler import get_current_user

router = APIRouter()

# task_id → running asyncio.Task
_running: dict[int, asyncio.Task] = {}

# 任务终态：到达这些状态即结束，不参与孤儿恢复
_TERMINAL_STATUSES = ["done", "failed", "cancelled"]
# 单个任务跨重启自动重跑的上限，防止「确定性崩溃」的任务无限重启
_MAX_RECOVERY_ATTEMPTS = 3


@router.get("/questions")
async def list_questions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role == "admin":
        result = await db.execute(
            select(Question, Report.id.label("report_id"), ResearchTask.id.label("task_id"), User.name.label("user_name"), User.id.label("user_id"))
            .outerjoin(ResearchTask, Question.id == ResearchTask.question_id)
            .outerjoin(Report, ResearchTask.id == Report.task_id)
            .outerjoin(User, Question.user_id == User.id)
            .where(Question.hidden.is_(False))
            .order_by(Question.created_at.desc())
            .limit(200)
        )
        return [
            {
                "id": q.id,
                "raw_text": q.raw_text,
                "tier": q.tier,
                "status": q.status,
                "created_at": q.created_at,
                "report_id": report_id,
                "task_id": task_id,
                "user_name": user_name,
                "user_id": uid,
            }
            for q, report_id, task_id, user_name, uid in result.all()
        ]
    else:
        result = await db.execute(
            select(Question, Report.id.label("report_id"), ResearchTask.id.label("task_id"))
            .outerjoin(ResearchTask, Question.id == ResearchTask.question_id)
            .outerjoin(Report, ResearchTask.id == Report.task_id)
            .where(Question.user_id == user.id)
            .where(Question.hidden.is_(False))
            .order_by(Question.created_at.desc())
            .limit(100)
        )
        return [
            {
                "id": q.id,
                "raw_text": q.raw_text,
                "tier": q.tier,
                "status": q.status,
                "created_at": q.created_at,
                "report_id": report_id,
                "task_id": task_id,
            }
            for q, report_id, task_id in result.all()
        ]


@router.get("/questions/{question_id}")
async def get_question(
    question_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Question).where(Question.id == question_id))
    q = result.scalar_one_or_none()
    if q is None:
        raise HTTPException(status_code=404)
    if user.role != "admin" and q.user_id != user.id:
        raise HTTPException(status_code=403)

    # also fetch associated task + report
    t_result = await db.execute(
        select(ResearchTask, Report.id.label("report_id"))
        .outerjoin(Report, ResearchTask.id == Report.task_id)
        .where(ResearchTask.question_id == question_id)
    )
    row = t_result.first()
    task_info = None
    report_id = None
    if row:
        t, report_id = row
        task_info = {
            "id": t.id,
            "status": t.status,
            "current_step": t.current_step,
            "keywords": json.loads(t.keywords_json) if t.keywords_json else [],
        }

    return {
        "id": q.id,
        "raw_text": q.raw_text,
        "clarified_text": q.clarified_text,
        "tier": q.tier,
        "report_type": q.report_type,
        "research_params": json.loads(q.research_params_json) if q.research_params_json else {},
        "status": q.status,
        "sub_questions": json.loads(q.sub_questions_json) if q.sub_questions_json else [],
        "keywords_draft": json.loads(q.keywords_draft_json) if q.keywords_draft_json else [],
        "created_at": q.created_at,
        "task": task_info,
        "report_id": report_id,
    }


async def list_tasks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role == "admin":
        result = await db.execute(
            select(ResearchTask).order_by(ResearchTask.started_at.desc()).limit(50)
        )
    else:
        result = await db.execute(
            select(ResearchTask)
            .join(Question, ResearchTask.question_id == Question.id)
            .where(Question.user_id == user.id)
            .order_by(ResearchTask.started_at.desc())
            .limit(50)
        )
    return [
        {
            "id": t.id,
            "question_id": t.question_id,
            "status": t.status,
            "current_step": t.current_step,
            "started_at": t.started_at,
            "finished_at": t.finished_at,
        }
        for t in result.scalars().all()
    ]


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ResearchTask).where(ResearchTask.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404)
    return {
        "id": task.id,
        "question_id": task.question_id,
        "status": task.status,
        "current_step": task.current_step,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "error_trace": task.error_trace,
    }


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ResearchTask).where(ResearchTask.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404)
    return {
        "id": task.id,
        "question_id": task.question_id,
        "status": task.status,
        "current_step": task.current_step,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "error_trace": task.error_trace,
    }


@router.get("/tasks/{task_id}/context")
async def get_task_context(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a structured summary of pipeline progress from context_json."""
    result = await db.execute(select(ResearchTask).where(ResearchTask.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404)

    ctx: dict = {}
    if task.context_json:
        try:
            ctx = json.loads(task.context_json)
        except Exception:
            pass

    steps = []
    local = ctx.get("local_candidates") or []
    steps.append({"step": "step3_local_search", "label": "公司知识库检索", "done": True, "summary": f"命中 {len(local)} 份文档", "detail": {"titles": [p.get("title", "") for p in local[:10]]}})
    me_stats = ctx.get("me_fetch_stats") or {}
    steps.append({"step": "step3b_me_fetch", "label": "Market Engine", "done": True, "summary": f"获取 {me_stats.get('total', 0)} 个数据块（{me_stats.get('mode', 'unknown')}）", "detail": me_stats})
    coverage = ctx.get("section_coverage") or []
    if coverage:
        steps.append({"step": "step4_coverage", "label": "章节覆盖度", "done": True, "summary": f"{sum(r.get('status') == '✅' for r in coverage)} 个章节充分，{sum(r.get('status') == '❌' for r in coverage)} 个缺口", "detail": {"coverage": coverage}})
    web = ctx.get("web_archived") or []
    if web:
        steps.append({"step": "step5_web_search", "label": "Web 补充搜索", "done": True, "summary": f"归档 {len(web)} 条", "detail": {"urls": [w.get("url") or w.get("title") or "" for w in web[:5]]}})
    blocks = ctx.get("context_blocks") or []
    if blocks:
        steps.append({"step": "step6_qc", "label": "证据组装", "done": True, "summary": f"形成 {len(blocks)} 个证据块", "detail": ctx.get("prewrite_coverage") or {}})
    if ctx.get("report_path"):
        steps.append({"step": "step9_report", "label": "生成报告", "done": True, "summary": f"{ctx.get('report_type')} / {ctx.get('report_status')}", "detail": {"report_path": ctx.get("report_path"), "eval_scores": ctx.get("eval_scores") or {}, "qc_warnings": ctx.get("qc_warnings") or []}})

    return {
        "task_id": task_id,
        "status": task.status,
        "current_step": task.current_step,
        "keywords": json.loads(task.keywords_json) if task.keywords_json else [],
        "steps": steps,
    }

async def ask(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()
    payload = json.loads(body.decode("utf-8"))
    """Web API: submit a question with pre-confirmed keywords and start pipeline.

    Body: {"question": "...", "keywords": ["k1","k2"], "tier": "normal",
           "clarified_text": "...", "sub_questions": [{"id":"Q1","text":"..."}]}
    """
    raw_text = (payload.get("question") or "").strip()
    keywords = payload.get("keywords") or []
    tier = payload.get("tier", "normal")
    clarified = payload.get("clarified_text") or raw_text
    sub_qs = payload.get("sub_questions") or []
    if not raw_text or not keywords:
        raise HTTPException(status_code=400, detail="question and keywords required")

    q = Question(
        user_id=user.id,
        tier=tier,
        raw_text=raw_text,
        clarified_text=clarified,
        sub_questions_json=json.dumps(sub_qs, ensure_ascii=False) if sub_qs else None,
        report_type=payload.get("report_type", "market"),
        research_params_json=json.dumps(payload.get("research_params", {}), ensure_ascii=False),
        status="running",
    )
    db.add(q)
    await db.flush()

    task = ResearchTask(
        question_id=q.id,
        status="step3_local_search",
        current_step="step3_local_search",
        keywords_json=json.dumps(keywords, ensure_ascii=False),
        started_at=datetime.now(timezone.utc),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    from . import orchestrator
    atask = asyncio.create_task(orchestrator.run(task.id, keywords))
    _running[task.id] = atask

    return {"question_id": q.id, "task_id": task.id, "status": "started"}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ResearchTask).where(ResearchTask.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404)

    task.status = "cancelled"
    task.finished_at = datetime.now(timezone.utc)
    await db.commit()

    running = _running.pop(task_id, None)
    if running and not running.done():
        running.cancel()

    return {"status": "cancelled"}


@router.delete("/questions/{question_id}/session")
async def delete_question_session(
    question_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a question from the chat history list only (soft delete).
    Sets `hidden=True` rather than deleting the row, so the associated task,
    report, and on-disk files stay intact and the report remains viewable.
    A hard delete is impossible here anyway: the task/report rows reference the
    question via FKs (enforced), so the row cannot be removed while they exist.
    """
    result = await db.execute(select(Question).where(Question.id == question_id))
    question = result.scalar_one_or_none()
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    if user.role != "admin" and question.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your question")

    question.hidden = True
    await db.commit()
    return {"hidden": question_id}


@router.delete("/questions/{question_id}")
async def delete_question(
    question_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a question (and its task/files) that has no report — i.e. failed/cancelled."""
    result = await db.execute(select(Question).where(Question.id == question_id))
    question = result.scalar_one_or_none()
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    if user.role != "admin" and question.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your question")

    # A question may have accumulated multiple tasks (e.g. one retry run).
    # If ANY task has a report, refuse — use DELETE /api/reports/{id} instead.
    tasks_result = await db.execute(
        select(ResearchTask).where(ResearchTask.question_id == question_id)
    )
    tasks = tasks_result.scalars().all()
    for task in tasks:
        report_result = await db.execute(
            select(Report).where(Report.task_id == task.id)
        )
        if report_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Use DELETE /api/reports/{id} for questions with a report")

    wilson_lib = Path(
        __import__("os").environ.get("WILSON_LIB_PATH", str(Path.home() / "Documents" / "wilson_lib"))
    )
    for task in tasks:
        # Cancel any running asyncio task
        running = _running.pop(task.id, None)
        if running and not running.done():
            running.cancel()

        # Delete staging dir for this task
        staging = wilson_lib / "staging" / f"task_{task.id}"
        if staging.exists():
            try:
                shutil.rmtree(staging)
            except Exception:
                pass

        await db.execute(text("DELETE FROM pending_documents WHERE task_id = :tid"), {"tid": task.id})
        await db.execute(text("DELETE FROM gate_results WHERE task_id = :tid"), {"tid": task.id})
        await db.execute(text("DELETE FROM research_tasks WHERE id = :tid"), {"tid": task.id})

    await db.execute(text("DELETE FROM questions WHERE id = :qid"), {"qid": question_id})
    await db.commit()
    return {"deleted": question_id}


async def start_pipeline(question_id: int, confirmed_keywords: list[str]) -> ResearchTask:
    """Create ResearchTask and launch pipeline. Called from feishu_keyword_card callback."""
    from . import orchestrator  # lazy to avoid circular deps
    from ..db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        task = ResearchTask(
            question_id=question_id,
            status="step3_local_search",
            current_step="step3_local_search",
            keywords_json=json.dumps(confirmed_keywords, ensure_ascii=False),
            started_at=datetime.now(timezone.utc),
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

    atask = asyncio.create_task(orchestrator.run(task.id, confirmed_keywords))
    _running[task.id] = atask
    return task


async def recover_orphaned_tasks() -> None:
    """重启后恢复未完成的 ResearchTask。

    `_running` 只存在进程内存，进程重启 / worker 协程崩溃后会丢失。届时所有
    `finished_at IS NULL` 且状态非终态的 task 都是孤儿：DB 行冻结在最后一个 step，
    前端轮询 `current_step` 永远拿到同一个值 → spinner 永转。

    这里在 lifespan 启动、对外服务之前调用一次：把孤儿任务重新跑起来（orchestrator
    会从 `context_json` 恢复上下文）。用 `retry_counters_json` 里的 `_recover` 计数封顶，
    超过上限的任务直接标记 `failed`，避免「一崩就重启、重启又崩」的死循环。
    """
    from . import orchestrator  # lazy to avoid circular deps
    from ..db.session import AsyncSessionLocal

    to_resume: list[tuple[int, list[str]]] = []
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ResearchTask).where(
                ResearchTask.finished_at.is_(None),
                ResearchTask.status.not_in(_TERMINAL_STATUSES),
            )
        )
        for task in result.scalars().all():
            if task.id in _running:
                continue  # 启动时 _running 必为空，防御性判断

            try:
                counters = json.loads(task.retry_counters_json) if task.retry_counters_json else {}
            except Exception:
                counters = {}
            attempts = int(counters.get("_recover", 0))

            # 超过 2 小时的孤儿不恢复（大概率是确定性失败或数据已过期）
            age = datetime.now(timezone.utc) - (task.started_at.replace(tzinfo=timezone.utc) if task.started_at.tzinfo is None else task.started_at)
            if age.total_seconds() > 7200:
                task.status = "failed"
                task.finished_at = datetime.now(timezone.utc)
                task.error_trace = (task.error_trace or "") + "\n[recover] 孤儿任务超过 2 小时未完成，标记为 failed"
                q = await db.get(Question, task.question_id)
                if q and q.status not in _TERMINAL_STATUSES:
                    q.status = "failed"
                print(f"[Scheduler] orphaned task {task.id} too old ({age}) → failed", flush=True)
                continue

            if attempts >= _MAX_RECOVERY_ATTEMPTS:
                # 反复恢复仍未完成 → 判失败，让前端停止空转
                task.status = "failed"
                task.finished_at = datetime.now(timezone.utc)
                task.error_trace = (
                    (task.error_trace or "")
                    + f"\n[recover] 超过最大恢复次数({_MAX_RECOVERY_ATTEMPTS})，标记为 failed"
                )
                q = await db.get(Question, task.question_id)
                if q and q.status not in _TERMINAL_STATUSES:
                    q.status = "failed"
                print(f"[Scheduler] orphaned task {task.id} exceeded recovery cap → failed", flush=True)
                continue

            counters["_recover"] = attempts + 1
            task.retry_counters_json = json.dumps(counters, ensure_ascii=False)
            try:
                keywords = json.loads(task.keywords_json) if task.keywords_json else []
            except Exception:
                keywords = []
            to_resume.append((task.id, keywords))

        await db.commit()

    # 在 DB session 之外启动协程（orchestrator.run 会自己开 session）
    for task_id, keywords in to_resume:
        atask = asyncio.create_task(orchestrator.run(task_id, keywords))
        _running[task_id] = atask
        print(f"[Scheduler] recovered orphaned task {task_id} → re-running pipeline", flush=True)
    # 让出 event loop，确保 create_task 创建的协程有机会开始调度
    if to_resume:
        await asyncio.sleep(0)


async def cleanup_stale_questions() -> None:
    """Hourly background housekeeping.

    1. Cancel Questions stuck in awaiting_clarify/awaiting_keyword for >24 hours.
    2. Expire PendingDocuments unreviewed for >30 days (delete staging file).

    Called once from main.py lifespan; runs forever in the background.
    """
    from ..db.session import AsyncSessionLocal
    from ..document_review.service import cleanup_expired_documents

    while True:
        await asyncio.sleep(3600)  # check every hour
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Question).where(
                        Question.status.in_(["awaiting_clarify", "awaiting_keyword"]),
                        Question.created_at < cutoff,
                    )
                )
                stale = result.scalars().all()
                for q in stale:
                    q.status = "cancelled"
                if stale:
                    await db.commit()

                await cleanup_expired_documents(db)
        except Exception as exc:
            print(f"[Scheduler] cleanup error: {exc}")
