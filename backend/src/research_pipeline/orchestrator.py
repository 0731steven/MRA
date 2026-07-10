"""MRA deterministic pipeline orchestrator.

IC-RA's browser/IEEE/patent chain is intentionally not imported here. The
pipeline is now: company KB -> Market Engine -> coverage -> optional Web ->
evidence assembly -> report -> quality/format checks -> delivery/fact card.
"""
from __future__ import annotations

import asyncio
import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from .context import PipelineContext, SubQuestion
from .steps import (
    step3_mra_search, step3b_me_fetch, step4_coverage, step5_web_search,
    step6_qc, step6b_prewrite_check, step8_validate, step9_mra_report,
    step9b_evaluate, step10_reply, step10b_factcard,
)
from ..db.models import Question, Report, ResearchTask, User
from ..db.session import AsyncSessionLocal

COMPANY_LIB = Path(os.environ.get("COMPANY_LIB_PATH", str(Path.home() / "company_lib"))).expanduser()
FEISHU_ENABLED = os.environ.get("FEISHU_ENABLED", "false").lower() == "true"

_ctx_locks: dict[int, asyncio.Lock] = {}
_STEP_LABELS = {
    "step3_local_search": "正在检索公司知识库…",
    "step3b_me_fetch": "正在读取 Market Engine 情报…",
    "step4_coverage": "正在评估报告章节覆盖度…",
    "step5_web_search": "正在针对数据缺口补充 Web 来源…",
    "step6_qc": "正在组装和排序证据…",
    "step6b_prewrite_check": "正在检查写作数据基础…",
    "step9_report": "正在生成市场研究报告…",
    "step9b_evaluate": "正在评估报告质量…",
    "step8_validate": "正在校验格式与引用…",
    "step10_reply": "正在推送报告…",
}


class _Cancelled(Exception):
    pass


def _push_ws(question_id: int | None, payload: dict) -> None:
    if question_id is None:
        return
    try:
        from ..web_ask.handler import get_ws_queue
        queue = get_ws_queue(question_id)
        if queue is not None:
            queue.put_nowait(payload)
    except Exception:
        pass


async def _check_cancelled(task_id: int) -> None:
    async with AsyncSessionLocal() as db:
        task = await db.get(ResearchTask, task_id)
        if task and task.status == "cancelled":
            raise _Cancelled()


async def _save_ctx(task_id: int, ctx: PipelineContext, current_step: str) -> None:
    lock = _ctx_locks.setdefault(task_id, asyncio.Lock())
    async with lock, AsyncSessionLocal() as db:
        task = await db.get(ResearchTask, task_id)
        if task:
            task.context_json = ctx.to_json()
            task.current_step = current_step
            if task.status not in {"done", "failed", "cancelled"}:
                task.status = current_step
            await db.commit()


async def _set_status(task_id: int, status: str, error: str | None = None) -> None:
    async with AsyncSessionLocal() as db:
        task = await db.get(ResearchTask, task_id)
        if not task:
            return
        task.status = status
        task.finished_at = datetime.now(timezone.utc)
        task.error_trace = error
        question = await db.get(Question, task.question_id)
        if question:
            question.status = status
        await db.commit()


async def _owner_feishu_id(task_id: int) -> str | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User.feishu_user_id)
            .join(Question, Question.user_id == User.id)
            .join(ResearchTask, ResearchTask.question_id == Question.id)
            .where(ResearchTask.id == task_id)
        )
        row = result.first()
        return row[0] if row else None


async def _save_report(task_id: int, ctx: PipelineContext) -> int:
    summary = ""
    if ctx.report_path and Path(ctx.report_path).exists():
        text = Path(ctx.report_path).read_text(encoding="utf-8", errors="ignore")
        marker = "## 执行摘要"
        summary = text.split(marker, 1)[-1].split("## ", 1)[0].strip()[:3000] if marker in text else text[:1000]
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Report).where(Report.task_id == task_id))
        report = result.scalar_one_or_none()
        values = {
            "vault_path": ctx.report_path,
            "summary_text": summary,
            "citations_json": json.dumps([b.get("source_id") for b in ctx.context_blocks], ensure_ascii=False),
            "report_type": ctx.report_type,
            "research_params_json": json.dumps(ctx.research_params, ensure_ascii=False),
            "me_data_stats_json": json.dumps(ctx.me_fetch_stats, ensure_ascii=False),
            "coverage_json": json.dumps(ctx.section_coverage, ensure_ascii=False),
            "qc_warnings_json": json.dumps(ctx.qc_warnings, ensure_ascii=False),
            "eval_scores_json": json.dumps(ctx.eval_scores, ensure_ascii=False),
        }
        if report is None:
            report = Report(task_id=task_id, **values)
            db.add(report)
        else:
            for key, value in values.items():
                setattr(report, key, value)
        await db.commit()
        await db.refresh(report)
        return report.id


async def _run_step(task_id: int, question_id: int, ctx: PipelineContext, name: str, func) -> None:
    await _check_cancelled(task_id)
    await _save_ctx(task_id, ctx, name)
    message = _STEP_LABELS[name]
    _push_ws(question_id, {"type": "progress", "question_id": question_id, "task_id": task_id, "step": name, "message": message})
    print(f"[MRA] task={task_id} {message}", flush=True)
    await func(ctx)
    await _save_ctx(task_id, ctx, name)


async def run(task_id: int, keywords: list[str]) -> None:
    question_id: int | None = None
    ctx = PipelineContext(task_id=task_id, keywords=keywords)
    try:
        async with AsyncSessionLocal() as db:
            task = await db.get(ResearchTask, task_id)
            if not task:
                return
            question_id = task.question_id
            if task.context_json:
                try:
                    ctx = PipelineContext.from_json(task.context_json, task_id)
                except Exception:
                    pass
            question = await db.get(Question, task.question_id)
            if question:
                ctx.tier = question.tier or "normal"
                ctx.clarified_text = question.clarified_text or question.raw_text
                ctx.report_type = question.report_type or ctx.report_type
                if question.research_params_json:
                    try:
                        ctx.research_params = json.loads(question.research_params_json)
                    except json.JSONDecodeError:
                        pass
                if question.sub_questions_json:
                    try:
                        ctx.sub_questions = [SubQuestion(**q) for q in json.loads(question.sub_questions_json)]
                    except Exception:
                        pass
        ctx.keywords = keywords or ctx.keywords
        ctx.staging_dir = str(COMPANY_LIB / "staging" / f"task_{task_id}")
        Path(ctx.staging_dir).mkdir(parents=True, exist_ok=True)

        await _run_step(task_id, question_id, ctx, "step3_local_search", step3_mra_search.run)
        await _run_step(task_id, question_id, ctx, "step3b_me_fetch", step3b_me_fetch.run)
        await _run_step(task_id, question_id, ctx, "step4_coverage", step4_coverage.run)
        if ctx.trigger_web_search and ctx.tier != "quick":
            await _run_step(task_id, question_id, ctx, "step5_web_search", step5_web_search.run)
        await _run_step(task_id, question_id, ctx, "step6_qc", step6_qc.run)
        await _run_step(task_id, question_id, ctx, "step6b_prewrite_check", step6b_prewrite_check.run)
        await _run_step(task_id, question_id, ctx, "step9_report", step9_mra_report.run)
        await _run_step(task_id, question_id, ctx, "step9b_evaluate", step9b_evaluate.run)
        await _run_step(task_id, question_id, ctx, "step8_validate", step8_validate.run)

        report_id = await _save_report(task_id, ctx)
        ctx.report_id = report_id
        await _save_ctx(task_id, ctx, "step10_reply")
        feishu_uid = await _owner_feishu_id(task_id)
        await asyncio.gather(step10_reply.run(ctx, feishu_uid), step10b_factcard.run(ctx))
        await _set_status(task_id, "done")
        _push_ws(question_id, {"type": "done", "question_id": question_id, "task_id": task_id, "report_id": report_id})
    except (_Cancelled, asyncio.CancelledError):
        await _set_status(task_id, "cancelled")
    except Exception:
        await _set_status(task_id, "failed", traceback.format_exc())
    finally:
        _ctx_locks.pop(task_id, None)
