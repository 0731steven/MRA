"""Pytest configuration — sets env vars BEFORE any backend modules are imported.

pytest_configure runs before test collection, so module-level constants in
src/ (COMPANY_LIB_PATH, DATABASE_URL, DEEPSEEK_MOCK, etc.) pick up these values.
"""
import os
import sys
import tempfile
from pathlib import Path

# Add backend/ to sys.path so tests can import `from src.xxx import ...`
sys.path.insert(0, str(Path(__file__).parent.parent))

_TMPDIR: Path | None = None


def pytest_configure(config: object) -> None:
    global _TMPDIR
    _TMPDIR = Path(tempfile.mkdtemp(prefix="cad_e2e_"))

    wilson_lib = _TMPDIR / "company_lib"
    (wilson_lib / "wiki" / "research").mkdir(parents=True)
    (wilson_lib / "wiki" / "qa").mkdir(parents=True)
    (wilson_lib / "staging").mkdir()
    (wilson_lib / "OBSIDIAN-WRITING.md").write_text(
        "# Writing Rules\n- Use wikilinks [[page|label]]\n- YAML frontmatter required\n",
        encoding="utf-8",
    )

    # Force these for tests — don't use setdefault, we need to override shell env
    os.environ["WILSON_LIB_PATH"] = str(wilson_lib)
    os.environ["COMPANY_LIB_PATH"] = str(wilson_lib)
    os.environ["ME_API_MODE"] = "mock"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMPDIR / 'test.db'}"
    os.environ["DEEPSEEK_MOCK"] = "true"
    os.environ["JWT_SECRET"] = "test-secret-for-testing-only"
    os.environ["FEISHU_ENABLED"] = "false"
    os.environ["APP_ENV"] = "development"
