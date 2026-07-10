# MRA 开发规约

## 系统定位

MRA 是按需市场研究系统，输出市场、产品、竞品和技术四类可追溯 Markdown 报告。主数据流为：

```text
company_lib → Market Engine（只读）→ 条件 Web → 证据块 → 报告 → 质量评分
```

## 模型铁律

- 全项目只允许通过 `backend/src/integrations/llm_client.py` 调用模型。
- SDK：`openai.OpenAI`。
- Base URL：`https://api.deepseek.com`。
- 模型：`deepseek-v4-pro`。
- `stream=False`。
- `reasoning_effort="high"`。
- `extra_body={"thinking": {"type": "enabled"}}`。
- 密钥只允许从 `DEEPSEEK_API_KEY` 环境变量读取。
- 禁止在代码、测试、日志、README、Git 历史中写入真实密钥。

## 数据与写作铁律

- MRA 对 Market Engine 只能执行只读请求。
- 每个事实和数字必须能映射到 KB、ME 或 Web 来源编号。
- 数据不足时输出 `status: insufficient`，不得用模型常识补造。
- L1 Fact Card 优先于普通 KB，ME 优先于 L0，Web 只补缺口。
- Web 内容需要保留 URL 和日期；过旧或日期未知的候选不进入报告。

## 验证

```bash
cd backend && pytest -q
cd web && npm ci && npm run build
```

CI 配置位于 `.github/workflows/ci.yml`。仓库地址为 `https://github.com/0731steven/MRA`。
