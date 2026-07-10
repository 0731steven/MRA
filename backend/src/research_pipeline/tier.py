"""档位配置常量。"""

TIER: dict[str, dict] = {
    "quick": {
        "ieee_max": 5,
        "patent_max": 5,
        "web_max": 0,       # quick 档跳过 Web
        "read_max": 5,
        "ieee_retries": 1,
        "patent_retries": 1,
    },
    "normal": {
        "ieee_max": 10,
        "patent_max": 10,
        "web_max": 5,
        "read_max": 15,
        "ieee_retries": 2,
        "patent_retries": 2,
    },
    "deep": {
        "ieee_max": 20,
        "patent_max": 15,
        "web_max": 8,
        "read_max": 25,
        "ieee_retries": 3,
        "patent_retries": 3,
    },
}


def cfg(tier: str) -> dict:
    return TIER.get(tier, TIER["normal"])
