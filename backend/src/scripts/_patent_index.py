#!/usr/bin/env python3
"""专利本地索引缓存。

被 patent_search.py / patent_convert.py 共用。
避免每次扫描 2362 个 PDF 文件名，改为读取缓存 JSON。

用法:
    from _patent_index import load_index, save_index, add_to_index
    idx = load_index()       # 返回 {patent_number: ipc_class}
    save_index(idx)          # 写入缓存
"""

import json
import os
import pathlib
import re

PATENT_SRC = pathlib.Path(os.environ.get("PATENT_PDF_SRC", str(pathlib.Path.home() / "Downloads" / "patents")))
PATENT_MD = pathlib.Path(os.environ.get("WILSON_LIB_PATH", str(pathlib.Path.home() / "Documents" / "wilson_lib"))) / "patent_md"
INDEX_FILE = PATENT_SRC / "_patent_index.json"

_FILENAME_RE = re.compile(
    r"^(?P<number>[A-Z]{2}\d{6,12}[A-Z]?\d?)\s*-\s*\[(?P<assignee>[^\]]+)\]\s*(?P<title>.+)\.pdf$"
)


def _scan_pdf_src() -> dict:
    """全量扫描 PDF 源目录，返回 {patent_number: ipc_class}。"""
    idx = {}
    if not PATENT_SRC.exists():
        return idx
    for ipc_dir in PATENT_SRC.iterdir():
        if not ipc_dir.is_dir() or ipc_dir.name == "inbox":
            continue
        for pdf in ipc_dir.glob("*.pdf"):
            m = _FILENAME_RE.match(pdf.name)
            if m:
                idx[m.group("number")] = ipc_dir.name
    return idx


def _scan_patent_md() -> dict:
    """全量扫描已转换 MD 目录。"""
    idx = {}
    if not PATENT_MD.exists():
        return idx
    for ipc_dir in PATENT_MD.iterdir():
        if not ipc_dir.is_dir():
            continue
        for d in ipc_dir.iterdir():
            if not d.is_dir():
                continue
            md_file = d / f"{d.name}.md"
            if md_file.exists():
                pn = d.name.split("_")[0] if "_" in d.name else d.name
                if re.match(r'^[A-Z]{2}\d{6,}', pn):
                    idx[pn] = ipc_dir.name
    return idx


def build_fresh() -> dict:
    """全量扫描并写入缓存。返回完整索引。"""
    pdf_idx = _scan_pdf_src()
    md_idx = _scan_patent_md()
    # merge: PDF source takes priority for ipc_class
    merged = {**md_idx, **pdf_idx}
    save_index(merged)
    return merged


def _index_is_stale(idx: dict) -> bool:
    """Check if any indexed patent no longer exists on disk (PDF src or MD)."""
    if not idx:
        return False
    for pn, ipc in idx.items():
        found = False
        if PATENT_SRC.exists():
            ipc_dir = PATENT_SRC / ipc
            if ipc_dir.is_dir() and any(True for _ in ipc_dir.glob(f"{pn}*.pdf")):
                found = True
        if not found and PATENT_MD.exists():
            ipc_dir = PATENT_MD / ipc
            if ipc_dir.is_dir() and any(True for _ in ipc_dir.glob(f"{pn}*")):
                found = True
        if not found:
            return True
    return False


def load_index() -> dict:
    """读取缓存索引。不存在或发现 stale 条目则全量重建。"""
    if INDEX_FILE.exists():
        try:
            with open(INDEX_FILE) as f:
                idx = json.load(f)
            if not _index_is_stale(idx):
                return idx
            # Stale — rebuild from disk
        except (json.JSONDecodeError, OSError):
            pass
    return build_fresh()


def save_index(idx: dict) -> None:
    """写入缓存。"""
    PATENT_SRC.mkdir(parents=True, exist_ok=True)
    with open(INDEX_FILE, "w") as f:
        json.dump(idx, f, ensure_ascii=False, sort_keys=True)


def add_to_index(patent_number: str, ipc_class: str) -> None:
    """向缓存追加一条。"""
    idx = load_index()
    idx[patent_number] = ipc_class
    save_index(idx)


def get_patent_numbers() -> set:
    """返回已有专利号集合（快，只加载缓存）。"""
    return set(load_index().keys())
