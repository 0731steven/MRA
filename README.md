# 概率学伴（Probability Tutor）

面向大学概率论与数理统计课程的题库问答与教学助手。系统由 React + FastAPI 构建，使用统一的 DeepSeek 客户端，默认模型为 `deepseek-v4-pro`。

## 当前能力

- 学生端：四种辅导方式、流式答疑、可交互题目溯源、个人学习概览
- 教师端：按主题、课时、指定题号生成教学设计，并可编辑、保存历史和导出 Markdown
- 身份登录：账号分为 `student` 和 `teacher`
- 专属题库：内置 `P000001`—`P001007` 共 1007 道题，包含题干、题型、难度、知识点、答案和解析
- 可追溯回答：模型回答会携带所依据的题号；未配置模型密钥时自动展示题库标准解析
- 会话记忆：自动保存历史会话，并携带最近 20 条消息支持连续追问
- 智能续问：只有明确的续问才会继承上一题来源，切换知识点时自动重新检索

## 核心流程

```text
学生：登录 → 输入题号/题干/知识点 → 检索题库 → DeepSeek 分步讲解 → 推荐相关题目

连续追问：恢复历史会话 → 加载最近 20 条消息 → 继承上一轮题目来源 → 结合题库继续回答

教师：登录 → 设置主题与课时 → 选择或自动匹配题目 → 生成课堂教学设计
```

## 本地启动

### 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

后端默认为 `http://localhost:8101`。在 `backend/.env` 中配置：

```ini
QUESTION_BANK_PATH=./data/probability_questions.jsonl
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_REASONING_EFFORT=high
```

### 前端

```bash
cd web
npm install
npm run dev
```

生产构建使用 `npm run build`，产物会写入 `backend/static/` 并由 FastAPI 托管。

## 题库数据

默认文件为 `backend/data/probability_questions.jsonl`。每行是一道题，核心字段包括：

```json
{"ID":"P000001","qtype":"简答题","question":"...","keypoint":["样本空间"],"answer":"...","explanation":"...","hard_level":"易"}
```

学生列表页默认不直接显示答案，进入题目详情后可主动查看；教师端列表接口可直接取得完整内容。

## 验证

```bash
cd web && npm run build
cd ../backend && pytest -q
```

真实模型调用仍需要在后端环境变量中配置 `DEEPSEEK_API_KEY`，密钥不得提交到仓库。
