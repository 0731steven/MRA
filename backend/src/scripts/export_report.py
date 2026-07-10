#!/usr/bin/env python3
"""
导出研究报告及全部引用素材为自包含 Obsidian vault ZIP。

输出结构（解压后用 Obsidian 直接打开该文件夹）：
  <slug>/
    wiki/research/<report>.md          ← 报告，wikilink 不变
    ieee_paper_md/<Field>/<stem>/
      <stem>.md
      images/                          ← 图片随目录一起打包
    patent_md/<ipc>/<stem>/
      <stem>.md
      images/
    raw/web/<topic>/<slug>/
      <slug>.md
    .obsidian/app.json                 ← 最简配置，让 Obsidian 认识 vault

用法:
  python export_report.py wiki/research/<slug>.md
  python export_report.py <path> --dry-run
"""

import argparse
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime

VAULT = pathlib.Path(os.environ.get("WILSON_LIB_PATH", str(pathlib.Path.home() / "Documents" / "wilson_lib")))
STAGING = pathlib.Path(os.environ.get("EXTRA_SEARCH_PATHS", "")).split(os.pathsep)[0] if os.environ.get("EXTRA_SEARCH_PATHS") else None


# ── wikilink extraction ────────────────────────────────────────────────────────

def _extract_wikilink_stems(text: str) -> list[str]:
    """从 MD 文本提取所有 [[stem]] / [[stem|alias]] / [[stem\\|alias]] 的 stem 部分。"""
    stems = []
    i = 0
    while True:
        start = text.find("[[", i)
        if start < 0:
            break
        pos = start + 2
        depth = 1
        while pos < len(text) and depth > 0:
            if text[pos:pos+2] == "]]":
                depth -= 1
                pos += 2
            elif text[pos] == "[":
                depth += 1
                pos += 1
            elif text[pos] == "]":
                depth -= 1
                pos += 1
            else:
                pos += 1
        inner = text[start+2:pos-2]
        # split alias
        if "\\|" in inner:
            stem = inner.split("\\|", 1)[0].strip()
        elif "|" in inner:
            stem = inner.split("|", 1)[0].strip()
        else:
            stem = inner.strip()
        if stem:
            # 跳过图片路径（images/ 子目录已随论文目录整体打包）
            if re.search(r'\.(png|jpg|jpeg|gif|svg|webp|pdf)$', stem, re.IGNORECASE):
                i = pos
                continue
            stems.append(stem)
        i = pos
    return stems


# ── source file lookup ─────────────────────────────────────────────────────────

def _find_source_dir(stem: str) -> pathlib.Path | None:
    """
    给定 wikilink stem（如 2023_Power_xxx 或 CN111525824B_-____CN111525824B），
    在 VAULT 和 staging 里找到包含该 MD 的目录并返回整个目录路径（带 images/）。
    返回目录，调用者负责整个目录的复制。
    """
    search_roots = [VAULT]
    if STAGING and pathlib.Path(STAGING).exists():
        search_roots.append(pathlib.Path(STAGING))

    for root in search_roots:
        # 精确：<any>/<stem>/<stem>.md
        for md in root.rglob(f"{stem}.md"):
            if md.parent.name == stem:
                return md.parent
        # 宽松：<any>/<stem>.md（无子目录结构，返回其父目录）
        for md in root.rglob(f"{stem}.md"):
            return md.parent

    return None


def _find_web_md(stem: str) -> pathlib.Path | None:
    """在 raw/web/ 下找 <stem>.md，返回文件路径。"""
    web_root = VAULT / "raw" / "web"
    if not web_root.exists():
        return None
    for md in web_root.rglob(f"{stem}.md"):
        return md
    return None


# ── vault structure detection ──────────────────────────────────────────────────

def _vault_rel(path: pathlib.Path) -> pathlib.Path | None:
    """返回 path 相对于 VAULT 的路径；若不在 VAULT 内返回 None。"""
    try:
        return path.relative_to(VAULT)
    except ValueError:
        return None


def _source_vault_rel(src_dir: pathlib.Path) -> pathlib.Path:
    """
    把源目录映射到 ZIP 内的相对路径，保持原始 vault 层级。
    - 在 VAULT 内：直接用相对路径
    - 在 staging 内：根据目录名推断（ieee/ → ieee_paper_md/, patent_md/ → patent_md/）
    """
    rel = _vault_rel(src_dir)
    if rel:
        return rel

    # staging 路径推断
    parts = src_dir.parts
    # 找 staging 段之后的结构
    for i, p in enumerate(parts):
        if p in ("ieee", "ieee_paper_md"):
            # staging/task_N/ieee/<Field>/<stem>/ → ieee_paper_md/<Field>/<stem>/
            return pathlib.Path("ieee_paper_md") / pathlib.Path(*parts[i+1:])
        if p == "patent_md":
            return pathlib.Path("patent_md") / pathlib.Path(*parts[i+1:])
        if p == "web":
            return pathlib.Path("raw") / "web" / pathlib.Path(*parts[i+1:])

    # 兜底：按目录名放到 others/
    return pathlib.Path("others") / src_dir.name


# ── export core ────────────────────────────────────────────────────────────────

def create_export_zip(report_path: pathlib.Path, dry_run: bool = False) -> pathlib.Path:
    """
    构建自包含 Obsidian vault ZIP，返回 ZIP 文件路径。

    ZIP 内结构：
      <slug>/
        wiki/research/<report>.md
        ieee_paper_md/.../<stem>/  (含 images/)
        patent_md/.../<stem>/      (含 images/)
        raw/web/.../               (含 images/ 若有)
        .obsidian/app.json
    """
    slug = report_path.stem
    content = report_path.read_text(encoding="utf-8", errors="replace")
    stems = _extract_wikilink_stems(content)

    # 去重（保留顺序）
    seen: set[str] = set()
    unique_stems: list[str] = []
    for s in stems:
        if s not in seen:
            seen.add(s)
            unique_stems.append(s)

    # 报告自身的 vault 相对路径
    report_rel = _vault_rel(report_path)
    if report_rel is None:
        report_rel = pathlib.Path("wiki") / "research" / report_path.name

    found: list[tuple[str, pathlib.Path, pathlib.Path]] = []  # (stem, src_dir, zip_rel_dir)
    missing: list[str] = []

    for stem in unique_stems:
        # 跳过 wiki/ 内部链接（概念页等，不是素材）
        if stem.startswith("wiki/"):
            continue

        src_dir = _find_source_dir(stem)
        if src_dir:
            zip_rel = _source_vault_rel(src_dir)
            found.append((stem, src_dir, zip_rel))
        else:
            # 尝试 raw/web
            web_md = _find_web_md(stem)
            if web_md:
                src_dir = web_md.parent
                zip_rel = _source_vault_rel(src_dir)
                found.append((stem, src_dir, zip_rel))
            else:
                missing.append(stem)

    # 统计（全部到 stderr，stdout 只留最终 JSON）
    print(f"📄 报告: {report_path.name}", file=sys.stderr)
    print(f"🔗 wikilink: {len(unique_stems)} 个，找到 {len(found)}，缺失 {len(missing)}", file=sys.stderr)
    for stem, src_dir, _ in found:
        print(f"  ✅ {stem}  ({src_dir})", file=sys.stderr)
    for stem in missing:
        print(f"  ❌ {stem}", file=sys.stderr)

    if dry_run:
        return report_path  # dry-run 不生成文件

    # 构建 ZIP
    zip_dir = VAULT / "wiki" / "output"
    zip_dir.mkdir(parents=True, exist_ok=True)
    zip_path = zip_dir / f"{slug}_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        root_prefix = pathlib.PurePosixPath(slug)

        # 1. 报告 MD
        _zip_add_file(zf, report_path, root_prefix / report_rel.as_posix())

        # 2. 各引用素材目录（整个目录含 images/）
        for _stem, src_dir, zip_rel in found:
            _zip_add_dir(zf, src_dir, root_prefix / zip_rel.as_posix())

        # 3. 最简 .obsidian/app.json（让 Obsidian 识别为 vault，不强制任何设置）
        obsidian_cfg = json.dumps({
            "legacyEditor": False,
            "livePreview": True,
        }, ensure_ascii=False, indent=2)
        zf.writestr(str(root_prefix / ".obsidian" / "app.json"), obsidian_cfg)

        # 4. README
        lines = [
            f"# {slug}",
            "",
            f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "## 使用方法",
            "1. 解压本 ZIP",
            f"2. 用 Obsidian 打开解压后的 `{slug}/` 文件夹作为 vault",
            "3. 点击报告中的 [[wikilink]] 可直接跳转到引用的论文/专利详情",
            "",
            f"## 内容",
            f"- 报告：{report_rel}",
            f"- 引用素材：{len(found)} 篇（论文/专利/Web）",
        ]
        if missing:
            lines += ["", "## 未找到的引用（素材可能尚未入库）"] + [f"- {s}" for s in missing]
        zf.writestr(str(root_prefix / "README.md"), "\n".join(lines))

    print(f"\n📦 ZIP: {zip_path}  ({zip_path.stat().st_size // 1024} KB)", file=sys.stderr)
    return zip_path


def _zip_add_file(zf: zipfile.ZipFile, src: pathlib.Path, arc_name: str | pathlib.PurePosixPath) -> None:
    zf.write(src, str(arc_name))


def _zip_add_dir(zf: zipfile.ZipFile, src_dir: pathlib.Path, arc_prefix: str | pathlib.PurePosixPath) -> None:
    """递归把 src_dir 下所有文件写入 ZIP 的 arc_prefix/ 下。"""
    arc_prefix = pathlib.PurePosixPath(arc_prefix)
    for fpath in src_dir.rglob("*"):
        if fpath.is_file():
            rel = fpath.relative_to(src_dir)
            zf.write(fpath, str(arc_prefix / rel.as_posix()))


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="导出报告为自包含 Obsidian vault ZIP")
    parser.add_argument("report", help="报告路径（相对 vault 或绝对路径）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不生成 ZIP")
    args = parser.parse_args()

    rpath = pathlib.Path(args.report)
    if not rpath.is_absolute():
        rpath = VAULT / args.report
    if not rpath.exists():
        print(f"文件不存在: {rpath}", file=sys.stderr)
        sys.exit(1)

    zip_path = create_export_zip(rpath, dry_run=args.dry_run)
    if not args.dry_run:
        # 输出 JSON 供 cad_tools.export_report() 解析
        print(json.dumps({"zip_path": str(zip_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
