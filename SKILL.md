---
name: market-research-assistant
description: 生成市场、产品、竞品或技术研究报告，整合公司知识库、Market Engine 和公开 Web 证据。
---

# Market Research Assistant

## 主流程

1. 澄清问题并分类为 `market`、`product`、`competitive` 或 `technology`。
2. 提取研究参数、关键词和可验证子问题。
3. 检索 `company_lib` L1/L0 文档。
4. 只读查询 Market Engine。
5. 对模板核心章节做覆盖度评估，缺口才触发 Web。
6. 按 L1 → ME → L0 → Web 排序证据。
7. 生成带来源编号的报告，执行质量评分与格式校验。
8. 完整报告归档到 `generated/`，充分报告提炼为 Fact Card。

## 约束

- 不编造市场规模、份额、财务、客户或路线图。
- 缺失信息明确标注“数据缺失”。
- Market Engine 单向只读。
- 全部模型调用必须经过统一 DeepSeek 客户端。
