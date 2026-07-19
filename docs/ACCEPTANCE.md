# 企业交付验收清单

## 交付方在移交前执行

```bash
cd web
npm ci
npm run test:math
npm run test:ui
npm run build

cd ../backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
alembic check
pytest -q
```

安装 Playwright 浏览器后，可执行真实页面验收：

```bash
cd web
npx playwright install chromium
npm run test:e2e
```

GitHub Actions 还会在 SQLite、PostgreSQL、真实浏览器和 Docker Compose 生产栈四类环境中执行检查。

## 教师端验收场景

- 创建班级并获得 7 位班级码；更换班级码后旧码失效。
- 归档班级后不能加入或发布任务；恢复后可继续使用。
- 发布带截止时间的短诊断，查看题目数和学生完成进度。
- 撤回任务后学生端不再显示；重新发布后恢复显示，历史进度不丢失。
- 移出学生后不再接收新任务，既有作答证据仍可审计。
- 生成分层教学包，确认教师答案与学生学习单分离，并分别导出 Markdown、打印或保存 PDF。
- 将教学包任一层级发布到班级，并在学生作答后看到雷达更新。

## 学生端验收场景

- 注册或登录学生账号，使用班级码加入班级。
- 查看待完成任务、截止时间和进度，逐题提交作答。
- 未作答前不能查看参考答案；作答后可查看答案与解析。
- 使用提示、检查思路、分步引导和完整解析四种答疑方式。
- 查看知识点掌握度、低证据信任提示和个性化学习路径。
- 在手机宽度下使用题库和答疑，无页面横向溢出；答疑设置从抽屉打开。

## 企业部署方提供

- Linux 服务器或容器平台、域名、DNS 和 HTTPS 证书。
- PostgreSQL、数据库密码、`SECRET_KEY`、模型 API Key 和教师邀请码。
- 网络访问策略、反向代理、备份位置、监控告警、日志留存和恢复演练。
- 正式的软件权属、许可范围、隐私政策和数据保留制度。

项目代码不包含真实企业地址、密码、证书或 API Key。是否进入正式生产由企业在其基础设施完成安全评审和最终验收后决定。
