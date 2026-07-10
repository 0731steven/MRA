"""MRA report schemas and coverage-critical sections."""
from __future__ import annotations

TEMPLATES = {
    "market": {
        "label": "市场研究",
        "sections": ["市场定义与边界", "市场规模与增长", "应用场景与需求驱动", "竞争格局", "南芯机会与风险", "行动建议", "数据来源与缺口"],
        "core": ["市场规模与增长", "竞争格局", "南芯机会与风险"],
    },
    "product": {
        "label": "产品研究",
        "sections": ["产品与场景定义", "关键参数对比", "功能与方案差异", "供应与客户信号", "南芯差距与定位", "行动建议", "数据来源与缺口"],
        "core": ["关键参数对比", "功能与方案差异", "南芯差距与定位"],
    },
    "competitive": {
        "label": "竞品分析",
        "sections": ["公司与业务概览", "财务与经营走势", "新品与产品路线", "客户和市场动作", "技术及招聘信号", "对南芯的影响", "应对建议", "数据来源与缺口"],
        "core": ["财务与经营走势", "新品与产品路线", "对南芯的影响"],
    },
    "technology": {
        "label": "技术研究",
        "sections": ["技术定义与路线", "成熟度与关键指标", "产业采用与时间表", "竞品技术信号", "南芯产品关联", "布局建议", "数据来源与缺口"],
        "core": ["技术定义与路线", "成熟度与关键指标", "南芯产品关联"],
    },
}


def get_template(report_type: str) -> dict:
    return TEMPLATES.get(report_type, TEMPLATES["market"])
