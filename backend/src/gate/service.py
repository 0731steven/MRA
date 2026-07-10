"""Gate service — parses check_report.py output and persists GateResult."""
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GateResult
from ..integrations import cad_tools


async def run_gate(
    task_id: int,
    report_path: str,
    gate_name: str,
    mode: str,
    db: AsyncSession,
) -> tuple[int, str]:
    exit_code, output = await cad_tools.check_report(report_path, mode)
    gate = GateResult(
        task_id=task_id,
        gate_name=gate_name,
        exit_code=exit_code,
        output=output,
        ran_at=datetime.now(timezone.utc),
    )
    db.add(gate)
    await db.commit()
    return exit_code, output
