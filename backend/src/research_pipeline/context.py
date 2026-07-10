"""PipelineContext — 贯穿全流水线的共享状态 dataclass。"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class SubQuestion:
    id: str
    text: str
    coverage: str = "❌"  # ✅ / ⚠️ / ❌


@dataclass
class PanoramaRow:
    direction: str
    category: str               # 核心 / 约束 / 邻域
    mentioned_sources: list[str] = field(default_factory=list)
    coverage: str = "❌"
    covering_papers: list[str] = field(default_factory=list)


@dataclass
class PipelineContext:
    task_id: int

    # ── Step 1 ────────────────────────────────────────────────────────────
    clarified_text: str = ""
    sub_questions: list[SubQuestion] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    tier: str = "normal"

    # MRA intent contract
    report_type: str = "market"       # market / product / competitive / technology
    research_params: dict[str, Any] = field(default_factory=dict)

    # ── Step 3 ────────────────────────────────────────────────────────────
    local_candidates: list[dict] = field(default_factory=list)
    existing_report_path: str | None = None
    initial_coverage: dict[str, str] = field(default_factory=dict)
    has_core_materials: bool = False
    kb_candidates: list[dict] = field(default_factory=list)

    # ── Step 3b: Market Engine ───────────────────────────────────────────
    me_data_blocks: list[dict] = field(default_factory=list)
    me_fetch_stats: dict[str, Any] = field(default_factory=dict)
    pipeline_warnings: list[str] = field(default_factory=list)

    # ── Step 4: report-section coverage ─────────────────────────────────
    section_coverage: list[dict] = field(default_factory=list)
    trigger_web_search: bool = False
    web_search_targets: list[str] = field(default_factory=list)

    # ── Step 4 ────────────────────────────────────────────────────────────
    panorama_table: list[PanoramaRow] = field(default_factory=list)
    panorama_built: bool = False

    # ── Step 5 ────────────────────────────────────────────────────────────
    decision_path: str = "step6"        # step8 = 全覆盖 | step6 = 有缺口
    gaps: list[dict] = field(default_factory=list)

    # ── Step 6 ────────────────────────────────────────────────────────────
    ieee_candidates: list[dict] = field(default_factory=list)
    ieee_downloaded: list[dict] = field(default_factory=list)
    ieee_new_papers: list[dict] = field(default_factory=list)

    # ── Step 7 ────────────────────────────────────────────────────────────
    patent_candidates: list[dict] = field(default_factory=list)
    patent_downloaded: list[dict] = field(default_factory=list)

    # ── Step 7b ───────────────────────────────────────────────────────────
    web_archived: list[dict] = field(default_factory=list)

    # ── Step 6: evidence assembly / pre-write checks ─────────────────────
    context_blocks: list[dict] = field(default_factory=list)
    prewrite_coverage: dict[str, Any] = field(default_factory=dict)
    retrieval_gaps: list[str] = field(default_factory=list)

    # ── Step 8 ────────────────────────────────────────────────────────────
    gate_results: dict[str, dict] = field(default_factory=dict)
    reading_scores: list[dict] = field(default_factory=list)
    frontmatter_status: dict[str, Any] = field(default_factory=dict)
    bounce_count: int = 0
    bounce_needed: bool = False

    # ── Step 9 ────────────────────────────────────────────────────────────
    preflight_passed: bool = False
    report_path: str = ""
    report_id: int | None = None
    report_status: str = "complete"     # complete / insufficient
    qc_warnings: list[str] = field(default_factory=list)
    eval_scores: dict[str, Any] = field(default_factory=dict)

    # ── Global ────────────────────────────────────────────────────────────
    staging_dir: str = ""
    retry_counters: dict[str, int] = field(default_factory=lambda: {"ieee": 0, "patent": 0, "web": 0})
    cancelled: bool = False
    cdp_port: int | None = None          # Chrome 实例端口，由 orchestrator 从 chrome_pool 分配

    # ── Serialization ─────────────────────────────────────────────────────

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str, task_id: int) -> "PipelineContext":
        d = json.loads(s)
        ctx = cls(task_id=task_id)
        # Restore simple fields
        for k, v in d.items():
            if k == "sub_questions":
                ctx.sub_questions = [SubQuestion(**q) for q in v]
            elif k == "panorama_table":
                ctx.panorama_table = [PanoramaRow(**r) for r in v]
            elif hasattr(ctx, k):
                setattr(ctx, k, v)
        return ctx
