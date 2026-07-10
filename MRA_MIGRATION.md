# IC-RA → MRA 改造记录

## 改造原则

保留原系统中已经成熟的 FastAPI、账户认证、Question/ResearchTask 状态机、WebSocket 进度、崩溃恢复、报告页和飞书入口；替换与 IC 文献研究强耦合的数据源和流水线。

## 已完成的代码映射

| 旧 IC-RA | 当前 MRA | 状态 |
|---|---|---|
| IC 技术关键词提取 | 四类报告分类 + `research_params` | 已完成 |
| `wilson_lib` 本地论文搜索 | `company_lib` L0/L1 检索 + BM25 chunk | 已完成 |
| IEEE / CNIPA 两段式下载 | Market Engine 只读 API | 已从主链下线 |
| 技术全景表 | 报告章节覆盖度矩阵 | 已完成 |
| IC Gate 阅读与 frontmatter | 写前数据基础检查 | 已完成 |
| 单次技术报告 | 四类模板三段式报告 | 已完成 |
| 论文/专利引用 | KB/ME/Web 来源编号 | 已完成 |
| `wiki/qa` 存档 | `generated/` + L1 Fact Card | 已完成 |

## 新增模块

- `backend/src/company_lib/bm25.py`
- `backend/src/company_lib/chunker.py`
- `backend/src/company_lib/retriever.py`
- `backend/src/integrations/me_client.py`
- `backend/src/research_pipeline/report_templates.py`
- `step3_mra_search.py`
- `step3b_me_fetch.py`
- `step4_coverage.py`
- `step5_web_search.py`
- `step6_qc.py`
- `step6b_prewrite_check.py`
- `step9_mra_report.py`
- `step9b_evaluate.py`
- `step8_validate.py`
- `step10b_factcard.py`

## 数据库变化

迁移 `0005_mra_core_fields.py` 新增：

- `Question.report_type`
- `Question.research_params_json`
- `Report.report_type`
- `Report.research_params_json`
- `Report.me_data_stats_json`
- `Report.coverage_json`
- `Report.qc_warnings_json`
- `Report.eval_scores_json`
- `mra_me_query_logs`

## 联调优先级

1. 在南芯内网确认 ME 基础 URL、鉴权方式和各端点实际字段。
2. 放入一套脱敏 `company_lib` 样例，验证竞品财务、BOM 和 Fact Card 的强制召回。
3. 将旧 Web 搜索脚本替换为 AnySearch JSON-RPC，并实现近一年硬过滤的真实日期解析。
4. 用四类真实问题各生成 3 份报告，人工评估来源准确性、覆盖度与洞察密度。
5. 最后处理批量入库、知识库浏览和管理员审核页的市场文档语义。
