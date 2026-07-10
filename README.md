# Market Research Assistant（MRA）

基于原 IC Research Assistant 改造的市场研究系统。用户通过 Web 或飞书提交问题，系统整合 `company_lib`、Market Engine 和必要的 Web 补充来源，生成市场、产品、竞品或技术报告。

GitHub：`https://github.com/0731steven/MRA`

## 当前版本

本仓库已完成 MRA MVP 主链路改造：

- 四类报告识别：`market`、`product`、`competitive`、`technology`
- Step 1 结构化提取：报告类型、研究参数、子问题、关键词
- `company_lib` L0/L1 分层检索、Markdown chunk 和 BM25 排序
- Market Engine 只读客户端，支持 `mock` / `real` 双模式
- 按报告模板评估章节覆盖度，仅对核心缺口触发 Web 补搜
- KB → ME → Web 的证据块排序与 120k 字符预算
- 写前数据基础检查，资料不足时自动生成 `insufficient` 报告
- 三段式报告生成、来源编号、质量评分和非阻塞格式校验
- 报告写入 `company_lib/generated/{report_type}/`
- 完整报告可进一步提炼为 `company_lib/fact_cards/` L1 卡片
- Web 前端支持四类报告确认、MRA 流水线进度和报告展示

原 IEEE、CNIPA、MinerU 代码仍保留在仓库中作为历史参考，但 MRA 主调度器不再导入或执行这些模块。

## 主流程

```text
提问 / 澄清
  → 报告分类与参数确认
  → company_lib 检索
  → Market Engine 只读查询
  → 章节覆盖度评估
  → 条件 Web 补搜
  → 证据组装与写前检查
  → 三段式报告生成
  → 质量评分与格式校验
  → Web/飞书推送 + Fact Card
```

## 本地启动

```bash
git clone https://github.com/0731steven/MRA.git
cd MRA
```

### 1. 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

开发地址默认为 `http://localhost:8101`。首次启动可使用 SQLite；生产环境建议 PostgreSQL 并执行：

```bash
alembic upgrade head
```

### 2. 前端开发

```bash
cd web
npm install
npm run dev
```

生产构建：

```bash
npm run build
```

Vite 会将产物写入 `backend/static/`，由 FastAPI 托管。

## 必要配置

```ini
APP_PORT=8101
DATABASE_URL=sqlite+aiosqlite:///./research.db
COMPANY_LIB_PATH=../company_lib
MRA_KB_CHAR_BUDGET=120000

DEEPSEEK_API_KEY=                 # 只写在 backend/.env，禁止提交
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_REASONING_EFFORT=high

ME_API_MODE=mock                  # 本地验证用 mock
ME_API_BASE_URL=http://127.0.0.1:8002
ME_API_KEY=
```

进入南芯网络并确认 ME 数据契约后，将 `ME_API_MODE` 改为 `real`。MRA 对 ME 只执行 GET 请求，不写入 ME 数据库。

全部模型调用统一使用 OpenAI Python SDK 连接 DeepSeek，固定为非流式请求，并启用 high reasoning 与 thinking。`backend/.env` 已被 `.gitignore` 排除，GitHub 中只保留无密钥的 `.env.example`。

## company_lib 目录

```text
company_lib/
├── _our_company_profile.md
├── competitive/
├── bom/
├── internal/market_reports/
├── raw/web/
├── fact_cards/                 # L1
├── market_cards/               # L1
├── tech_cards/                 # L1
├── company_info/               # L1
├── generated/                  # L2 报告
└── staging/
```

检索顺序为 L1 卡片优先、ME 实时数据其次、L0 文档再次、Web 补充最后。竞品报告会提高财务文档权重，市场和产品报告会提高 BOM 文档权重。

## 验证

```bash
cd backend
pytest -q

cd ../web
npm run build
```

Mock 模式不要求连接南芯内网。没有任何资料时，端到端流水线仍会完成，但报告会明确标记为 `insufficient`，不会编造结论。

## 当前尚未完成

- 真实 ME 端点字段需在南芯内网按实际返回值做最后联调
- 旧“批量入库”模块内部仍保留 IC 文档分类逻辑，后续应改为市场文档元数据抽取
- Web 搜索仍复用旧项目脚本壳；生产版应替换为公司实际使用的 AnySearch 接口
- 数据库生产迁移、飞书卡片和权限体系需要在真实部署环境复验

详细改造记录见 `MRA_MIGRATION.md`。
# MRA
