# 概率统计教学助手

面向大学概率论与数理统计课程的题库问答与教学助手。系统由 React、FastAPI 和 SQLAlchemy 构建，开发环境可使用 SQLite，正式部署使用 PostgreSQL。

## 当前能力

- 学生端：四种辅导方式、流式答疑、多方式作答诊断、知识点掌握度、认知断层预警和个性化学习路径
- 教学闭环：教师创建班级并发布短诊断，学生使用班级码加入和完成任务；系统按班级证据生成知识点风险、动态干预分组和无提示迁移验证
- 探究实验：提供大数定律、概率分布、极限定理、贝叶斯、置信区间与蒙特卡洛等 8 个参数化实验，并关联题库练习
- 教师端：按主题、课时、课堂类型、学情基线和指定题号生成教师执行版、无答案学生学习单与证据报告，可编辑、保存、分别导出，并把任一层级直接发布为班级任务
- 身份登录：账号分为 `student` 和 `teacher`，教师注册需要部署方配置的邀请码；浏览器会话使用 HttpOnly Cookie
- 专属题库：内置 `P000001`—`P001007` 共 1007 道题
- 会话记忆：自动保存历史会话，并携带最近 20 条消息支持连续追问

学习路径依据题库 `keypoint_ids`、作答正确性、错误类型、提示次数和重复尝试动态计算。预警至少需要两次相关作答证据；证据较少时会明确标记低可信度，不把一次失误直接判断为知识断层。

班级认知雷达只统计当前教师所建班级内的任务作答，不读取其他班级或学生个人自学会话。系统会把学生暂时分为证据积累、前置回补、去提示练习、概念巩固和迁移挑战等任务组；分组随新证据更新，用于安排下一项任务，不作为固定能力标签。

分层教学包由可审计的课程规则引擎生成，不依赖模型 API Key。引擎会保证课堂时间闭合、题目可追溯、教师答案与学生版本分离，并为每层写明适用证据、达标标准和升级条件；关联班级时，仅使用该班级与所选题目直接相关的任务作答。

## 环境要求

- Python 3.12
- Node.js 22
- 本地开发无需单独安装数据库
- PostgreSQL 17（正式环境）
- Docker 与 Docker Compose（可选，用于一键模拟正式部署）

## 本地开发（SQLite）

后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

前端另开一个终端：

```bash
cd web
npm ci
npm run dev
```

浏览器访问 `http://localhost:5173`。SQLite 数据默认写入 `backend/teaching_assistant.db`，适合开发和测试。

## PostgreSQL / Docker 部署验证

这套方式会构建前端、运行 Alembic 数据库迁移并启动 PostgreSQL 与后端。企业的真实服务器、域名和密钥不应写入源代码。

1. 安装 Docker Desktop。
2. 创建配置文件：

```bash
cd backend
cp .env.example .env
```

3. 至少修改以下配置：

```ini
SECRET_KEY=至少32个字符的随机密钥
POSTGRES_PASSWORD=数据库强密码
BOOTSTRAP_TEACHER_USERNAME=admin
BOOTSTRAP_TEACHER_PASSWORD=至少12位的初始教师密码
```

4. 构建并启动：

```bash
docker compose up --build -d
docker compose ps
```

浏览器访问 `http://localhost:8101`。首次启动会执行 `alembic upgrade head`，并在配置了初始教师账号时创建该账号。重复启动不会重复创建。

查看日志或停止服务：

```bash
docker compose logs -f app
docker compose down
```

`docker compose down` 不会删除 PostgreSQL 数据卷。只有明确执行 `docker compose down -v` 才会删除数据库数据。

## 正式环境配置

配置模板位于 `backend/.env.example`，正式配置复制为 `backend/.env`，不要提交到 Git。

| 变量 | 用途 |
|---|---|
| `APP_ENV` | 本地为 `development`；Docker 会覆盖为 `production` |
| `DATABASE_URL` | 直接运行后端时的数据库地址 |
| `SECRET_KEY` | JWT 签名密钥，生产环境至少 32 个字符 |
| `ALLOWED_ORIGINS` | 逗号分隔的前端来源；同域部署可留空 |
| `POSTGRES_DB` | Docker PostgreSQL 数据库名 |
| `POSTGRES_USER` | Docker PostgreSQL 用户名 |
| `POSTGRES_PASSWORD` | Docker PostgreSQL 密码；用于连接地址时特殊字符需 URL 编码 |
| `BOOTSTRAP_TEACHER_*` | 可选的首个教师账号，只在账号不存在时创建 |
| `TEACHER_REGISTRATION_CODE` | 可选；教师自行注册时必须提供的邀请代码 |
| `DEEPSEEK_API_KEY` | 部署方提供的模型 API Key |
| `DEEPSEEK_TIMEOUT_SECONDS` | 模型请求超时秒数，默认 60 |
| `DEEPSEEK_MAX_RETRIES` | 模型请求最大重试次数，默认 2、最大 5 |

不使用 Docker、直接连接企业 PostgreSQL 时设置：

```ini
APP_ENV=production
DATABASE_URL=postgresql+asyncpg://用户名:URL编码后的密码@数据库地址:5432/数据库名
SECRET_KEY=至少32个字符的随机密钥
ALLOWED_ORIGINS=https://实际前端域名
```

生产模式会拒绝默认密钥、非 PostgreSQL 数据库及通配符 CORS 配置。若前后端由同一个域名提供，浏览器请求属于同源访问，`ALLOWED_ORIGINS` 可以留空。

## 数据库迁移与升级

数据库结构由 Alembic 管理。修改 ORM 模型后，应创建并检查迁移：

```bash
cd backend
alembic revision --autogenerate -m "describe change"
alembic upgrade head
alembic check
```

企业升级源代码后，在启动新版本应用前执行：

```bash
alembic upgrade head
```

Docker 镜像的入口脚本会自动执行这一步。SQLite 与 PostgreSQL 是两套独立数据库，已有 SQLite 数据不会因为修改连接地址自动复制到 PostgreSQL；如需保留历史数据，应在正式切换前单独制定数据迁移和核对方案。

## 备份与恢复

Docker 环境备份示例：

```bash
docker compose exec -T db pg_dump -U mra -d mra -Fc > mra.backup
```

恢复前应停止应用写入，并由部署人员确认目标数据库：

```bash
docker compose exec -T db pg_restore -U mra -d mra --clean --if-exists < mra.backup
```

实际生产环境的备份频率、保存位置、加密和恢复演练由部署方按照企业制度执行。

## 题库数据

默认题库为 `backend/data/probability_questions.jsonl`。每行是一道题：

```json
{"ID":"P000001","qtype":"简答题","question":"...","keypoint":["样本空间"],"answer":"...","explanation":"...","hard_level":"易"}
```

题库文件不存放在 PostgreSQL 中，切换数据库不会改变题库内容。

## 验证

```bash
cd web && npm ci && npm run test:math && npm run test:ui && npm run build
cd ../backend && pytest -q
```

真实页面的手机与桌面验收：

```bash
cd web
npx playwright install chromium
npm run test:e2e
```

数学内容统一经过 `MathMarkdown` 渲染：兼容 `$...$`、`$$...$$`、`\\(...\\)`、`\\[...\\]` 和题库中的二次转义分隔符，同时保护代码块与矩阵换行。无需使用文档 OCR API 处理已有 LaTeX。

CI 会分别在全新 SQLite 和真实 PostgreSQL 数据库上执行 `alembic upgrade head`、`alembic check` 和后端测试，并执行前端生产构建、手机/桌面浏览器验收及 Docker Compose 生产栈健康检查。本地已有的旧 SQLite 文件可能没有 Alembic 版本标记，不应在未备份、未核对结构前直接执行 `alembic stamp`。

服务提供两个健康检查接口：

- `/health/live`：应用进程存活
- `/health/ready`：应用可以连接数据库

## 源代码交付边界

本仓库交付应用源代码、依赖清单、数据库迁移、容器配置、配置模板和部署说明，不包含公网服务器。部署方负责提供实际服务器、域名、HTTPS 证书、数据库密码、`SECRET_KEY`、模型 API Key、网络入口限流/WAF、网络策略以及日常备份与监控。

学生提交的文字答案、解题思路与答疑文字可能发送给部署方配置的模型服务；上传的手写图片只保存在应用数据库，不发送给模型。企业部署前应按自身制度确认模型供应商、隐私告知、数据保存周期和删除流程。

交付前不得把 `.env`、数据库文件、真实密码、真实 API Key 或企业内部地址提交到仓库。

交付评审可同时参考 [系统架构与数据边界](docs/ARCHITECTURE.md)、[企业交付验收清单](docs/ACCEPTANCE.md)、[安全说明](SECURITY.md) 和 [变更记录](CHANGELOG.md)。本项目不要求开发者个人先购买公网服务器；企业在其基础设施上完成部署、安全评审和最终生产验收即可。
