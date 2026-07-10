# Research Assistant 工具参考

> 本文档是脚本命令的完整参考手册。决策流程见 SKILL.md。

## 核心脚本

### research_runner.py（主入口）

**IEEE 两段式标准路径的封装入口**（见 SKILL.md Step 6）。标准用法是先 `--search-only` 获取候选，LLM 评分后再 `--dois` 下载。

```bash
cd /Users/wilsonzhao/Documents/wilson_lib/tools

# 两段式第 1 段：仅搜索，返回候选（标准路径第一步）
/opt/homebrew/bin/python3.11 scripts/research_runner.py <keywords> --search-only --json

# 两段式第 2 段：指定 DOI 下载（LLM 评分筛选后）
/opt/homebrew/bin/python3.11 scripts/research_runner.py <keywords> --dois DOI1 DOI2 DOI3

# 仅本地搜索（Step 3 使用）
/opt/homebrew/bin/python3.11 scripts/research_runner.py <keywords> --local-only

# 强制远程（sufficient 判断跳过时使用）
/opt/homebrew/bin/python3.11 scripts/research_runner.py <keywords> --force-remote --json

# 加 Scholar 补充
/opt/homebrew/bin/python3.11 scripts/research_runner.py <keywords> --scholar --json
```

| 参数 | 说明 |
|------|------|
| `--json` | 结构化 JSON 输出 |
| `--force-remote` | 跳过 sufficient 检查强制远程搜索 |
| `--local-only` | 仅本地搜索 |
| `--search-only` | 仅搜索返回候选（不下载） |
| `--dois DOI1 DOI2 ...` | 指定 DOI 列表下载（跳过搜索），空格分隔 |
| `--scholar` | 启用 Google Scholar 补充（默认关） |

**`--dois` 行为说明**：直接下载指定 DOI，跳过搜索阶段。内部自动 batch_convert 并行转换 + 按 topic 分类入库。

### ieee_search.py（IEEE 搜索下载）

仅在降级手动路径使用。正常流程用 research_runner.py。

```bash
cd /Users/wilsonzhao/Documents/wilson_lib/tools
# 搜索+下载
/opt/homebrew/bin/python3.11 scripts/ieee_search.py "<keywords>"

# 预览不下载
/opt/homebrew/bin/python3.11 scripts/ieee_search.py "<keywords>" --dry-run
```

### patent_search.py（专利搜索下载）

```bash
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/patent_search.py "<patent_query>" --max 10  # quick=5, normal=10, deep=15
```

| 参数 | 说明 |
|------|------|
| `--max 10` | 最大下载数（默认 10） |
| `--search-only` | 仅搜索不下载 |
| `--dry-run` | 列出候选不下载 |
| `--status GRANT` | 已授权专利（默认） |
| `--status APPLICATION` | 申请中专利 |

**IPC 自动分类**：内置 13 条常用 IPC 前缀映射（H03F→信号链与放大器、H03M→数据转换器等），扫描本地目录补充。匹配到时自动 mkdir + 分类保存，匹配不到进 inbox/。

**关键词改写**（学术词 → 专利功能描述词）：
- `direct time-of-flight` → `time of flight distance measurement`
- `SPAD quenching` → `single photon avalanche diode quenching circuit`
- `Class-D THD` → `class D audio amplifier dead time distortion`

### 专利搜索方案对比

| 方案 | 可用性 | 说明 |
|------|-------|------|
| **Google Patents** | ⚠️ 大陆不稳定 | `patent_search.py` CDP 驱动，PDF 含附图 |
| **CNIPA** | ✅ **首选 fallback，国内直连** | `patent_search_cnipa.py`，无需翻墙 |
| Lens.org API | ✅ 需注册 Bearer Token | 候选列表可用，PDF 需跳转 |
| Espacenet | ❌ 403 bot 拦截 | 仅手动查询 |

**当前 fallback**：`patent_search.py` 不可用时，**切换到 `patent_search_cnipa.py`**。CNIPA 前置条件：Chrome 已登录 CNIPA 账号（session 持久化）。

### web_search.py（Web 补充搜索）

```bash
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/web_search.py "Class-D amplifier PSRR" --max 10 --json
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/web_search.py "SAR ADC switching" --max 10 --save raw/web/ADC/
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/web_search.py "buck EMI" --max 5 --save raw/web/Power/ --fetch  # 抓全文

# 网络不稳定时（大陆环境）：加长超时
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/web_search.py "query" --max 10 --json --timeout 60
```

| 参数 | 说明 |
|------|------|
| `query` | 搜索关键词 |
| `--max N` | 最大返回数（默认 10） |
| `--json` | JSON 输出 |
| `--save DIR` | 保存结果 MD 到 vault 相对目录 |
| `--fetch` | 抓取每个结果的网页全文（与 --save 配合） |
| `--select 1,3,5` | 仅保存/抓取指定序号的结果 |
| `--timeout N` | 单次请求超时秒数（默认 30s） |
| `--retries N` | 失败后重试次数（默认 2，即最多 3 次尝试；每次间隔 3s/6s） |

纯 stdlib，零依赖。DuckDuckGo HTML 版，无反爬。失败时自动重试，全部失败后打印 `[error]` 并返回空列表——调用方需检查是否为空并在报告中记录失败原因。

### web_ingest.py（Web 资源入库）

统一入口：**Web 搜索结果中的高价值源（PDF/HTML），必须通过此脚本归档进 raw/web/。**

```bash
# 单 URL
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/web_ingest.py <url> --topic <topic>

# 多 URL（并行）
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/web_ingest.py <url1> <url2> --topic <topic> --workers 4

# 预览
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/web_ingest.py <url> --topic <topic> --dry-run
```

| 参数 | 说明 |
|------|------|
| `urls` | 一个或多个待入库 URL |
| `--topic NAME` | 必选，raw/web/ 下目标子目录（如 `MEMS_Stiction`） |
| `--dry-run` | 仅预览不下载 |
| `--workers N` | 多 URL 并行数（PDF 多文件时建议 2） |
| `--device` | MinerU 计算设备（默认 mps） |

**自动检测**：HEAD 请求判断 Content-Type → PDF 走下载+MinerU 转 MD；HTML 走抓取+Markdown 转换。PDF 原始文件留存 `~/Downloads/web_articles/<topic>/`。

**设计原则**：
- PDF 源 = paper/patent 同级流程：下载到 `~/Downloads/web_articles/` → MinerU 转 MD → `raw/web/<topic>/<slug>/`（含 images/ 子目录、含 frontmatter）
- HTML 源 = 直接抓取 → html→markdown → `raw/web/<topic>/<slug>.md`（含 frontmatter，`source:` 指向原始 URL）
- 不可读的 PDF（paywall 伪装、扫描件无 OCR）只存摘要+参考文献目录

**验货**（→ R10）：
```bash
# 确认 MD 存在且可读
find raw/web/<topic>/ -name "*.md" -not -path "*/images/*" -exec echo "{} ($(wc -c < {} 2>/dev/null || echo 0) bytes)" \;
```
- PDF 源：MD >500 bytes，非乱码，images/ 有图
- HTML 源：MD 存在，frontmatter `source:` 指向原始 URL
- Paywall：标注 `note: "Paywall"`，不假装全文

### patent_convert.py（专利转换）

```bash
# 按 IPC 目录转换
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/patent_convert.py --ipc H03F-信号链与放大器 --workers 4

# 按文件转换
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/patent_convert.py --files \
  ~/Downloads/patents/H03F/patent1.pdf ~/Downloads/patents/H03F/patent2.pdf --workers 4

# 预览
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/patent_convert.py --ipc H03F-信号链与放大器 --dry-run
```

| 参数 | 说明 |
|------|------|
| `--ipc <name>` | 限定 IPC 目录 |
| `--files <paths>` | 指定文件列表 |
| `--days 1` | 默认只扫最近 24h PDF |
| `--workers 4` | MPS 设备推荐 2 |
| `--dry-run` | 预览不转换 |

### local_search.py（本地搜索）

```bash
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/local_search.py <keyword1> <keyword2> ...
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/local_search.py <keywords> --json
```

输出：papers / patents / concepts / surveys / reports 路径列表 + sufficient 标志。

> ⚠️ `sufficient` 是纯数量判断（报告存在→true，有综述→3篇即true，无综述→5篇即true）。Claude 必须独立做语义评估（→ R6）。

### check_report.py（格式检查）

```bash
# 检查报告格式
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/check_report.py wiki/research/<slug>.md

# 检查论文 frontmatter
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/check_report.py --papers ieee_paper_md/Power/2025_PaperName/

# 简要论文列表
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/check_report.py --papers-brief ieee_paper_md/Power/
```

`--papers-brief`：只输出论文列表（标题 + frontmatter 填充状态），不读原文。适合快速扫描大批论文。

### fix_report_citations.py（引用修复）

```bash
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/fix_report_citations.py wiki/research/<slug>.md
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/fix_report_citations.py wiki/research/<slug>.md --dry-run
```

从参考文献表格提取 [N] → 文件名映射，扫描正文将 `Author [N]` 替换为 `[[filename|Author Year]] [N]`。

### 降级手动路径（research_runner 不可用时）

```bash
# 第 1 段：搜索+下载 PDF
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/ieee_search.py "<keywords>"

# 第 2 段：批量转换（必须用 --rescan，禁止逐篇）
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/ingest_pdf.py --rescan --workers 4

# 转换完检查目录分类
find ieee_paper_md/ -mindepth 2 -maxdepth 2 -type d | \
  xargs -I{} sh -c 'n=$(find {} -name "*.md" -not -path "*/images/*" | wc -l); [ $n -gt 0 ] && echo "$n {}"' | \
  sort -rn
```

> **禁止** `ingest_pdf.py <单文件>` 逐篇串行。`--days 1`（默认）只扫最近 24h。

---

## Chrome CDP

脚本内置 `_cdp_helper.ensure_cdp()`，自动检测端口 → 未开放则启动研究 Chrome（专用 profile，与日常浏览器隔离）。

**手动启动**（降级用）：
```bash
bash /Users/wilsonzhao/Documents/wilson_lib/tools/scripts/launch_research_chrome.sh
```

**首次使用**：需在弹出的 Chrome 窗口登录 IEEE 机构账号（登录态持久化，后续自动可用）。

### IEEE auth 恢复流程

当 IEEE 下载返回 HTML 而非 PDF（文件 ~50KB，真 PDF >400KB）：

1. 检查研究 Chrome 是否已启动（`lsof -i :9222`）
2. 在研究 Chrome 中手动访问 `https://ieeexplore.ieee.org/` 确认登录态
3. 若显示 `Sign In` → 重新登录机构账号
4. 登录后重新运行脚本

脚本已内置 `%PDF-` 文件头校验，HTML 伪装自动拒绝。

### 转换失败 skip 说明

MinerU 转换失败的 PDF（损坏/扫描件/加密）会被 skip 并记录到 stdout。常见原因：
- PDF 加密（DRM）→ 联系 IEEE 换源
- 纯扫描件无 OCR 层 → 手动 OCR 后重试
- 文件截断（下载不完整）→ 删除后重新下载

---

## 专利 vs 论文字段对照

| 论文字段 | 专利字段 | 说明 |
|----------|---------|------|
| `background` | `background` | 共用 |
| `core_innovation` | `core_innovation` | 共用 |
| `critical_topology` | `critical_topology` | 共用 |
| `test_results` | `key_embodiments` | 替换：专利无实测数据 |
| `process_package_area` | `process_technology` | 替换：工艺大类而非具体面积 |
| `limitations` | `limitations` | 共用 |
| — | `problem_solved` | 新增：技术问题陈述 |
| — | `solution_overview` | 新增：方案概述 |

---

## 工具路径表

| 脚本 | 用途 |
|------|------|
| `tools/scripts/_cdp_helper.py` | Chrome CDP 自动管理 |
| `tools/scripts/local_search.py` | 本地 grep 搜索 |
| `tools/scripts/ieee_search.py` | IEEE CDP 搜索下载 |
| `tools/scripts/patent_search.py` | Google Patents CDP 搜索下载 |
| `tools/scripts/web_search.py` | DuckDuckGo Web 补充搜索 |
| `tools/scripts/web_ingest.py` | **Web 资源自动入库（PDF→MinerU / HTML→MD）** |
| `tools/scripts/research_runner.py` | 搜索+下载+ingest 胶水 |
| `tools/scripts/ingest_pdf.py` | PDF → MD 转换 |
| `tools/scripts/batch_convert_v2.py` | MinerU 批量转换引擎 |
| `tools/scripts/patent_convert.py` | 专利 PDF → MD 转换 |
| `tools/scripts/check_report.py` | 报告/论文格式检查 |
| `tools/scripts/fix_report_citations.py` | 引用 → wikilink 批量替换 |
| `tools/scripts/launch_research_chrome.sh` | 手动启动研究 Chrome |
| `tools/scripts/scholar_search.py` | Google Scholar 补充搜索 |

---

## 关键模板

| 模板 | 用途 |
|------|------|
| `templates/paper-note-template.md` | 论文 frontmatter 字段定义 |
| `templates/survey-template.md` | 综述八章结构 + 引用系统 |
| `templates/concept-template.md` | 概念页模板 |
| `templates/patent-note-template.md` | 专利 frontmatter 字段定义 |
| `templates/short-report-template.md` | 短报告模板（≤2 子问题 + ≤5 引用） |

---

## 评分标准（两段式候选评分）

### 论文评分

| 分 | 含义 |
|---|------|
| 5 | 直接回答，含电路拓扑/实测数据 |
| 4 | 高度相关，有技术细节 |
| 3 | 相关但偏综述/系统级/年代久远（>10年） |
| 2 | 领域擦边 |
| 1 | 无关（直接排除） |

**话题中心性过滤**（评分后强制检查）：
- 用户研究对象是论文的**主贡献**（标题/摘要 contribution 描述中出现）→ 分数不变
- 用户研究对象仅是论文系统中的**一个模块/工具**（论文主贡献是更大系统）→ **封顶 3 分**
- 判断依据：标题去掉用户研究对象关键词后，剩余部分是否仍成立为独立贡献？是 → component（封顶 3）；否 → protagonist（不限）
- 例：用户研究 "DC-DC 变换器" → "A TEG Energy Harvesting PMU with Boost DC-DC"，去掉 DC-DC 后 "TEG Harvesting PMU" 仍成立 → component → 封顶 3
- 例：用户研究 "DC-DC 变换器" → "A Fully Integrated SC DC-DC Buck Converter"，去掉 DC-DC 后无主语 → protagonist → 不限
- **封顶豁免**：Step 6 Override 条目（<2 年 top 1 / 唯一覆盖）优先于封顶
- **封顶自动解除**：候选列表中被封顶论文占比 >80% 时，说明该方向文献生态以系统级为主，取消全部封顶，回退到原始评分，报告注明「该方向文献以系统级论文为主」

**硬过滤**（直接 1 分）：无电路设计内容 / 0 引用+5 年以上+非知名会议 / 关键词匹配但实质不同领域

**期刊加权**：JSSC > ISSCC > TCAS-I > VLSI > CICC > ASSCC > ESSCIRC > IFCS > MEMS Conf. > Sensors J. > 其他

### 专利评分

| 分 | 含义 |
|---|------|
| 5 | 直接解决子问题，含具体电路/方法实施例 |
| 4 | 高度相关，有关键技术方案描述 |
| 3 | 相关但偏系统级/方法抽象/年代久远（>15年） |
| 2 | 领域擦边，核心 claim 不匹配 |
| 1 | 无关（直接排除） |

**硬过滤**（直接 1 分）：非电路/非 IC 实现 / 纯机械/材料专利 / claim 与子问题无交集

**申请人加权**：TI > ADI > NXP/ST > Cirrus/Maxim > 大厂研究院 > 个人发明人

### Web 结果评分

| 分 | 含义 |
|---|------|
| 5 | 直接回答子问题，权威来源（IEEE/ISSCC/academic / 原厂 app note） |
| 4 | 高度相关，技术博客/论坛详实讨论 |
| 3 | 相关但偏介绍/科普/年代久远 |
| 2 | 擦边，内容浅 |
| 1 | 无关/广告/SEO 页面 |

**来源加权**：原厂 app note (TI/ADI/ST/NXP) > 技术博客/设计指南 > 论坛

> 论文/专利源（ieeexplore / patents.google / scholar / arxiv 等）在搜索阶段自动过滤。

## Google Scholar 补充

> [!warning] Google Scholar 反爬极严
> - 首次使用需手动过 CAPTCHA
> - 默认不启用 `--scholar`
> - Scholar 结果仅打印 URL 供手动下载
> - 非 IEEE 源无批量 PDF 下载通道

---

## 踩坑记录

### IEEE PDF 下载 HTML 伪装
`stampPDF/getPDF.jsp` 在未登录机构账号时静默返回 HTML 登录页，脚本误当 PDF 保存。文件大小 ~50KB（真 PDF >400KB）。

**预防**：Chrome 必须已登录 IEEE 机构账号；脚本已内置 `%PDF-` 文件头校验；`route.fetch()` 超时已扩至 60s。某些 Chrome 扩展会修改 PDF 响应体，优先用 route 拦截。

### MinerU 转换速度
每篇 1–3 分钟。`--rescan --days 0` 会扫全部 PDF（含旧文件），极慢。

**预防**：批量转换用 `ingest_pdf.py --rescan --workers 4`（内部调 batch_convert_v2 并行）。**禁止** `ingest_pdf.py <单文件>` 逐篇串行。`--days 1`（默认）限制扫描范围到最近 24h。

### 手动拆阶段绕过并行和分类
Agent 有时绕过 research_runner，自己跑 `ieee_search.py` + `ingest_pdf.py` 逐篇，导致串行极慢（~50s/篇）+ topic 自动分类失效（论文散落 `_unclassified/`）。

**预防**：**两段式（`--search-only` → 评分 → `--dois`）是标准路径**（见 SKILL.md Step 6），勿绕过。降级手动时（research_runner 不可用）：用 `batch_convert_v2.py --files --topic --workers 4`，**绝不用** `ingest_pdf.py` 逐篇。转换完检查论文是否在正确 `ieee_paper_md/<Topic>/` 下，散落的立即 `mv` 归位。

### patent_convert.py 未用 MPS + workers 4

MPS 设备（Apple Silicon）默认用 `--device cpu` 而非 MPS，且 workers 默认值低。每篇专利 ~3–12 min，2 并行时 5 篇 = 24.7 min。用 `--device mps --workers 4` 预期快 3–4×。

**预防**：`patent_convert.py --files ... --workers 4 --device mps`（MPS 设备）。`ingest_pdf.py --rescan --workers 4` 同理。

### Agent 补 frontmatter 不可靠
大量论文补 frontmatter 时 agent 容易超时或逐字段编辑极慢。

**预防**：每篇一次性改全部字段（一次 Edit 替换整个 frontmatter 块）。>10 篇时优先用脚本批量处理。专利 frontmatter（8 字段）和论文 frontmatter（6 字段）都要补，写报告前 `check_report.py --papers` 验证。

---

## 验证命令

```bash
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/local_search.py Class-D THD amplifier
```
```bash
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/ieee_search.py "low-power ADC" --dry-run
```
```bash
cd /Users/wilsonzhao/Documents/wilson_lib/tools && /opt/homebrew/bin/python3.11 scripts/patent_search.py "Class-D amplifier" --search-only
```
