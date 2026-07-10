"""Small string-distance helpers shared across the codebase.

Used to recover MinerU image filenames that an LLM mis-transcribed when copying
64-hex hashes into a report (a dropped/changed char). Distinct hashes differ by
~50 chars, so a small distance cap unambiguously identifies the intended file.
"""
from __future__ import annotations


def edit_distance_capped(a: str, b: str, cap: int) -> int:
    """Levenshtein distance with early exit once it provably exceeds `cap`.

    Returns the true distance when it is ≤ cap, otherwise `cap + 1`.
    """
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        row_min = i
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            cur.append(v)
            if v < row_min:
                row_min = v
        if row_min > cap:
            return cap + 1
        prev = cur
    return prev[-1]
