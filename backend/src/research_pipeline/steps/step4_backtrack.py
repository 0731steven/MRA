"""Step 4 — 反向追踪：读素材 intro 建技术全景表。

全景表三分类：
  核心  — 研究对象与用户问题处于同一抽象层级
  约束  — 直接约束/驱动用户研究对象的设计参数
  邻域  — 共享关键词但不影响设计决策

可在 Step 3 后立即调用（Path A），也可在 Step 6 下载后调用（Path B 补建）。
"""
from __future__ import annotations
import os
from pathlib import Path

from ..context import PipelineContext, PanoramaRow
from ...integrations.llm_client import LLMClient, ChatMessage

WILSON_LIB = Path(os.environ.get("WILSON_LIB_PATH", str(Path.home() / "Documents" / "wilson_lib")))

_SYSTEM = """你是 IC 设计领域的研究助手，擅长从论文 introduction 中归纳技术全景。

阅读提供的论文/专利 introduction 段落，为用户问题建立技术全景表。

分类规则：
- 核心：研究对象与用户问题处于同一抽象层级（如用户问 LDO PSRR → "LDO PSRR 提升技术"属核心）
- 约束：直接约束/驱动研究对象的设计参数（如电源噪声、负载电流、工艺参数）
- 邻域：共享关键词但不影响设计决策（如同样用到运放，但研究方向不同）

注意：
- 每个技术方向独立一行
- 若素材中已有覆盖，coverage 填 ✅；有提及但不充分填 ⚠️；完全没有填 ❌
- 初始建表时素材就是已有文献，covering_papers 填来源文件名（不含路径）

输出 JSON（不加 markdown 代码块）：
{
  "panorama": [
    {
      "direction": "技术方向名称",
      "category": "核心",
      "mentioned_sources": ["paper1.md", "paper2.md"],
      "coverage": "✅",
      "covering_papers": ["paper1.md"]
    }
  ]
}"""


def _read_intro(path: str) -> str:
    """读取文档的 introduction 部分（取前 3000 字符）。"""
    try:
        full_path = WILSON_LIB / path if not Path(path).is_absolute() else Path(path)
        text = full_path.read_text(encoding="utf-8", errors="ignore")
        lower = text.lower()
        # find() returns -1 when not found; -1 is truthy so `or` short-circuits incorrectly
        idx = lower.find("## introduction")
        if idx == -1:
            idx = lower.find("# introduction")
        start = max(0, idx)  # Use 0 (beginning) when header not found
        return text[start: start + 3000]
    except Exception:
        return ""


async def run(ctx: PipelineContext) -> None:
    # 收集所有有路径的素材
    sources = ctx.local_candidates + ctx.ieee_downloaded + ctx.patent_downloaded

    intros: list[str] = []
    for s in sources[:12]:  # 最多读 12 篇 intro
        path = s.get("path", "")
        if not path:
            continue
        # staging 目录里的文件用绝对路径
        if ctx.staging_dir and not Path(path).is_absolute():
            full = Path(ctx.staging_dir) / path
            if full.exists():
                path = str(full)
        text = _read_intro(path)
        if text:
            fname = Path(path).name
            intros.append(f"### {fname}\n{text}")

    if not intros:
        ctx.panorama_built = False
        return

    user_msg = (
        f"用户问题：{ctx.clarified_text or ' '.join(ctx.keywords)}\n\n"
        + "\n\n---\n\n".join(intros)
    )
    llm = LLMClient(step=4)
    try:
        result = await llm.chat_json(
            [ChatMessage(role="user", content=user_msg)],
            system=_SYSTEM,
            max_tokens=4096,
        )
        rows = result.get("panorama", [])
        ctx.panorama_table = [PanoramaRow(**r) for r in rows]
        ctx.panorama_built = True
    except Exception:
        ctx.panorama_built = False
