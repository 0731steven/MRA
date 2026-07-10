"""Proxy for Obsidian Local REST API (http://127.0.0.1:27123).

GET /api/obsidian/vault/{path}  — raw markdown text (Obsidian API or direct disk)
GET /api/obsidian/pdf/{stem}    — serve PDF file by stem name
GET /api/obsidian/img/{path}    — serve images referenced from MD files
GET /api/obsidian/search?q=...  — filename search across vault
"""
import os
import re
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, FileResponse

from ..auth.handler import get_current_user, get_current_user_query
from ..common.fuzzy import edit_distance_capped
from ..db.models import User

router = APIRouter()

_OBSIDIAN_BASE = os.environ.get("OBSIDIAN_BASE_URL", "http://127.0.0.1:27123")
_OBSIDIAN_KEY = os.environ.get("OBSIDIAN_API_KEY", "")
_WILSON_LIB = Path(os.environ.get("WILSON_LIB_PATH", str(Path.home() / "Documents" / "wilson_lib")))
_IEEE_PDF_SRC = Path(os.environ.get("IEEE_PDF_SRC", str(Path.home() / "Downloads" / "ieee_papers")))
_PATENT_PDF_SRC = Path(os.environ.get("PATENT_PDF_SRC", str(Path.home() / "Downloads" / "patents")))


def _obsidian_request(path: str) -> str:
    url = f"{_OBSIDIAN_BASE}/vault/{path}"
    req = urllib.request.Request(url)
    if _OBSIDIAN_KEY:
        req.add_header("Authorization", f"Bearer {_OBSIDIAN_KEY}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=e.code, detail=f"Obsidian API: {e.reason}")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Obsidian not reachable: {e}")


def _find_md(vault_path: str) -> Path | None:
    """Search for an .md file by path or stem across wilson_lib including staging."""
    stem = Path(vault_path).stem
    stem_lower = stem.lower()

    # 1. Exact path under wilson_lib
    candidate = _WILSON_LIB / vault_path
    if candidate.exists():
        return candidate

    # 2. With .md appended
    candidate_md = _WILSON_LIB / (vault_path + ".md")
    if candidate_md.exists():
        return candidate_md

    # 3. rglob("*.md") + exact stem match — avoids glob metacharacter issues
    #    (parens, brackets, $ signs in paper filenames break pattern-based rglob)
    for match in _WILSON_LIB.rglob("*.md"):
        if match.stem.lower() == stem_lower:
            return match

    return None


_IMG_MEDIA = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
}


def _resolve_image_fuzzy(img_path: str) -> Path | None:
    """Recover an image whose embedded filename was mis-transcribed (e.g. a
    dropped char in a 64-hex MinerU hash). The paper-dir component of the embed
    is reliable, so locate that dir and pick the nearest-stem image inside it.

    Distinct sha256 hashes differ in ~half their chars, so a tiny edit-distance
    threshold makes a false match effectively impossible.
    """
    name = Path(img_path).name
    suffix = Path(name).suffix.lower()
    if suffix not in _IMG_MEDIA:
        return None
    want_stem = Path(name).stem

    def nearest_in(files, cap: int) -> Path | None:
        """Pick the closest-stem file within `cap` edits. Distinct MinerU hashes
        differ by ~50 chars, so a small cap can never reach a wrong file."""
        best: Path | None = None
        best_d = cap + 1
        for f in files:
            if f.suffix.lower() != suffix:
                continue
            d = edit_distance_capped(f.stem, want_stem, cap)
            if d < best_d:
                best_d, best = d, f
                if d == 0:
                    break
        return best if best_d <= cap else None

    # Scope to the paper dir named just before the "images" segment, if present.
    # The dir name is transcribed reliably; only the hash drifts, so a generous
    # cap (well under the ~48-edit noise floor between distinct hashes) is safe.
    parts = [p for p in img_path.replace("\\", "/").split("/") if p]
    if "images" in parts:
        idx = parts.index("images")
        if idx >= 1:
            paper_dir = parts[idx - 1]
            cap = max(8, len(want_stem) // 6)
            for d in _WILSON_LIB.rglob(paper_dir):
                if not d.is_dir():
                    continue
                imgs = d / "images"
                hit = nearest_in((imgs if imgs.is_dir() else d).glob(f"*{suffix}"), cap)
                if hit:
                    return hit

    # Dir-less global fallback: only repair trivial (≤2) single-char slips to
    # avoid false matches when scanning the whole vault.
    return nearest_in(_WILSON_LIB.rglob(f"*{suffix}"), 2)


def _find_pdf(stem: str) -> Path | None:
    """Find a PDF by stem. Checks:
    1. wilson_lib (PDF copied alongside MD on approve)
    2. PATENT_PDF_SRC / IEEE_PDF_SRC download dirs
    3. staging / report_sources dirs
    """
    stem_lower = stem.lower()
    # 末尾数字 DOI（IEEE 文件名规范：..._<7-10位数字>）精确匹配
    doi_m = re.search(r'_(\d{7,10})$', stem)
    doi = doi_m.group(1) if doi_m else None
    # 专利号前缀
    patent_num: str | None = None
    pm = re.match(r'^([A-Z]{2}\d{6,}[A-Z]?\d?)', stem, re.IGNORECASE)
    if pm:
        patent_num = pm.group(1).upper()
    # 把安全化的 stem（_ 代替特殊字符）转成宽松匹配用的前缀
    # 取前 30 个字符作为稳定前缀，避免 % 编码导致子串匹配失败
    stem_prefix = stem_lower[:30]

    search_roots = [
        _WILSON_LIB,
        _PATENT_PDF_SRC,
        _IEEE_PDF_SRC,
        _WILSON_LIB / "staging",
    ]

    exact: Path | None = None
    doi_match: Path | None = None
    prefix_match: Path | None = None
    patent_match: Path | None = None

    for root in search_roots:
        if not root.exists():
            continue
        for match in root.rglob("*.pdf"):
            ms = match.stem.lower()
            if ms == stem_lower:
                return match  # 精确命中直接返回
            if doi and doi_match is None and ms.endswith(f"_{doi}"):
                doi_match = match
            if prefix_match is None and ms.startswith(stem_prefix):
                prefix_match = match
            if patent_num and patent_match is None and match.stem.upper().startswith(patent_num):
                patent_match = match

    # 优先级：DOI 精确 > 前缀匹配 > 专利号
    return doi_match or prefix_match or patent_match


@router.get("/obsidian/vault/{vault_path:path}", response_class=PlainTextResponse)
async def get_vault_file(
    vault_path: str,
    _user: User = Depends(get_current_user),
):
    clean = Path(vault_path).as_posix()
    if ".." in clean:
        raise HTTPException(status_code=400, detail="Invalid path")

    # Try Obsidian REST API first
    try:
        content = _obsidian_request(clean)
        return PlainTextResponse(content)
    except HTTPException:
        pass  # Obsidian not running or unreachable — fall through to disk

    # Obsidian not running — read from disk
    md_path = _find_md(clean)
    if md_path:
        content = md_path.read_text(encoding="utf-8", errors="ignore")
        # Return the file's parent dir relative to wilson_lib so the frontend
        # can resolve relative image paths (e.g. images/fig.png)
        try:
            rel_dir = md_path.parent.relative_to(_WILSON_LIB).as_posix()
        except ValueError:
            rel_dir = ""
        return PlainTextResponse(
            content,
            headers={
                "X-File-Dir": urllib.parse.quote(rel_dir, safe="/"),
                "Access-Control-Expose-Headers": "X-File-Dir",
            },
        )
    raise HTTPException(status_code=404, detail=f"File not found: {vault_path}")


@router.get("/obsidian/pdf/{stem:path}")
async def get_pdf(
    stem: str,
    _user: User = Depends(get_current_user_query),
):
    """Serve a PDF file by its stem (filename without .pdf). Auth via ?token= query param."""
    if ".." in stem:
        raise HTTPException(status_code=400, detail="Invalid path")
    # stem may include subpath; try exact filename stem first
    file_stem = Path(stem).name
    pdf = _find_pdf(file_stem)
    if pdf is None:
        raise HTTPException(status_code=404, detail=f"PDF not found: {stem}")
    return FileResponse(
        str(pdf),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                "inline; "
                f"filename*=UTF-8''{urllib.parse.quote(pdf.name, safe='')}"
            )
        },
    )


@router.get("/obsidian/img/{img_path:path}")
async def get_image(
    img_path: str,
    _user: User = Depends(get_current_user_query),
):
    """Serve an image referenced from a markdown file."""
    if ".." in img_path:
        raise HTTPException(status_code=400, detail="Invalid path")
    # img_path is relative to wilson_lib
    candidate = _WILSON_LIB / img_path
    if candidate.exists():
        return FileResponse(str(candidate), media_type=_IMG_MEDIA.get(candidate.suffix.lower(), "image/png"))
    # Search by exact filename across the vault (incl. staging).
    # Avoid rglob(name) — glob metacharacters in filenames (parens, brackets, $)
    # would cause fnmatch to misinterpret the pattern.
    name = Path(img_path).name
    name_lower = name.lower()
    suffix = Path(name).suffix.lower()
    if suffix in _IMG_MEDIA:
        for match in _WILSON_LIB.rglob(f"*{suffix}"):
            if match.name.lower() == name_lower:
                return FileResponse(str(match), media_type=_IMG_MEDIA[suffix])
    # Fallback: recover a mis-transcribed filename (e.g. a dropped char in a hash)
    repaired = _resolve_image_fuzzy(img_path)
    if repaired:
        return FileResponse(str(repaired), media_type=_IMG_MEDIA.get(repaired.suffix.lower(), "image/png"))
    raise HTTPException(status_code=404, detail=f"Image not found: {img_path}")


@router.get("/obsidian/search", response_class=PlainTextResponse)
async def search_vault(
    q: str,
    _user: User = Depends(get_current_user),
):
    results: list[str] = []
    stem = q.strip().lower()
    for match in _WILSON_LIB.rglob("*.md"):
        if stem in match.stem.lower():
            results.append(match.relative_to(_WILSON_LIB).as_posix())
        if len(results) >= 20:
            break
    return "\n".join(results)
