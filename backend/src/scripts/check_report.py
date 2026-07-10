#!/usr/bin/env python3
"""报告格式检查脚本。检查 wiki/research/ 下报告的完整性。

用法:
  python3 scripts/check_report.py wiki/research/foo_report_20260515.md
  python3 scripts/check_report.py --all   # 检查所有报告
  python3 scripts/check_report.py --papers ieee_paper_md/Power/2025_xxx/
  python3 scripts/check_report.py --papers-brief ieee_paper_md/Power/
  python3 scripts/check_report.py --lint-papers          # 全库论文 YAML 语法 + LaTeX 扫描
  python3 scripts/check_report.py --lint-patents         # inbox 残留 + 分类检查
"""

import argparse
import os
import pathlib
import re
import subprocess
import sys

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

VAULT = pathlib.Path(os.environ.get("WILSON_LIB_PATH", str(pathlib.Path.home() / "Documents" / "wilson_lib")))

# Extra roots (e.g. a task's staging dir) so a report still in pre-approval
# resolves figures/wikilinks that haven't been moved into the vault yet.
EXTRA_SEARCH_PATHS = [
    pathlib.Path(p) for p in os.environ.get("EXTRA_SEARCH_PATHS", "").split(",")
    if p.strip()
]


def _embedded_image_exists(target: str) -> bool:
    """Does an embedded image (`<dir>/images/<file>`) resolve to a real file?

    The embed carries the source's folder name but not its full vault/staging
    prefix, so try the literal relative path first, then fall back to a basename
    search across the vault and any extra roots (mirrors how the web app serves
    these images)."""
    roots = [VAULT, *EXTRA_SEARCH_PATHS]
    for root in roots:
        if (root / target).exists():
            return True
    base = pathlib.PurePosixPath(target).name
    for root in roots:
        if not root.exists():
            continue
        if next(root.rglob(base), None) is not None:
            return True
    return False


# ─────────────────────────────────────────────
# 报告检查
# ─────────────────────────────────────────────

def check_report(report_path: pathlib.Path) -> list[str]:
    """检查单个报告，返回问题列表。"""
    issues = []
    content = report_path.read_text(encoding="utf-8")

    # 1. 图片嵌入检测（含占位符）
    for m in re.finditer(r'!\[\[([^\]]+)\]\]', content):
        target = m.group(1)
        # 1a. 占位符/无效嵌入：无扩展名或 pipe 在末尾 (如 images/|alias)
        if '.' not in target.split('/')[-1]:
            issues.append(f"  ❌ 图片嵌入无扩展名（疑似占位符）: ![[{target[:80]}]]")
        elif target.endswith('.md'):
            issues.append(f"  ❌ .md 文件被当图片嵌入: {target}")
        elif target.endswith(('.jpg', '.png', '.gif', '.webp', '.jpeg', '.svg')):
            if not _embedded_image_exists(target):
                issues.append(f"  ❌ 图片不存在: {target}")
        # 1b. 未知扩展名
        elif '.' in target.split('/')[-1]:
            issues.append(f"  ⚠️ 图片扩展名非标准: {target}")

    # 2. 表格内 wikilink 转义检查
    for i, line in enumerate(content.split('\n'), 1):
        if line.strip().startswith('|') and '|' in line:
            for m in re.finditer(r'\[\[([^\]]+)\]\]', line):
                link = m.group(1)
                # 2a. 缺少 \| 转义 (裸 |)
                if '|' in link and '\\|' not in link:
                    issues.append(f"  ⚠️ L{i}: 表格内 wikilink 未用 \\| 转义: [[{link[:60]}...]]")
                # 2b. 双反斜杠 \\| (Python 脚本转义过头)
                if '\\\\|' in link:
                    issues.append(f"  ❌ L{i}: wikilink 含双反斜杠 \\\\|（应改为 \\|）: [[{link[:60]}...]]")

    # 4. 报告 frontmatter 必要字段
    fm_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if fm_match:
        fm = fm_match.group(1)
        for field in ['title', 'tags', 'created', 'question', 'domain', 'status']:
            if not re.search(rf'^{field}\s*:', fm, re.MULTILINE):
                issues.append(f"  ⚠️ 缺少 frontmatter 字段: {field}")

    # 5. wikilink 死链检查（含路径的，纯文件名跳过让 Obsidian 自动匹配）
    checked = set()
    for m in re.finditer(r'\[\[((?:[^\]|#]|\\\|)+?)(?:\|[^\]]+)?\]\]', content):
        target = m.group(1).strip()
        # 5a. 检测双反斜杠 \\| 残留（\\ 在 target 中）
        if '\\\\' in target:
            issues.append(f"  ❌ wikilink target 含双反斜杠（\\\\| 残留）: [[{target[:80]}]]")
            continue
        if target in checked or target.startswith(('http://', 'https://')):
            continue
        checked.add(target)
        if '/' not in target:
            # 去掉 \| 转义残留的尾反斜杠
            clean = target.rstrip('\\')
            # 短别名模式检测: "Author Year" 或 "Author2023" 等非文件名格式
            if re.match(r'^[A-Z][a-z]+\s*\d{4}$', clean) or re.match(r'^[A-Z][a-z]+\s+et\s+al', clean):
                issues.append(f"  ❌ wikilink 疑似短别名（非文件名）: [[{clean}]]")
            # 纯文件名：用 find 命令验证 vault 中存在
            found = subprocess.run(
                ["find", str(VAULT), "-name", f"{clean}.md", "-not", "-path", "*/images/*", "-not", "-path", "*/auto/*"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
            ).stdout.strip()
            if not found:
                found = subprocess.run(
                    ["find", str(VAULT), "-name", clean, "-not", "-path", "*/images/*"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
                ).stdout.strip()
            if not found:
                issues.append(f"  ❌ wikilink 目标不存在（全库搜索）: [[{clean}]]")
            continue
        # 5b. 去掉 \| 转义残留在 target 末尾的 \（Obsidian 表内合法转义）
        clean_target = target.rstrip('\\')
        # 检查目标文件：允许 target 或 target.md 两种形式
        tpath = VAULT / clean_target
        tpath_with_md = VAULT / (clean_target + '.md') if not clean_target.endswith('.md') else tpath
        if not tpath.exists() and not tpath_with_md.exists():
            issues.append(f"  ⚠️ wikilink 无法解析: [[{target[:80]}]]")

    # 6. 正文 [N] 引用缺少 wikilink
    in_refs = False
    for i, line in enumerate(content.split('\n'), 1):
        if line.strip().startswith('## 参考文献'):
            in_refs = True
            continue
        if in_refs:
            continue
        if line.strip().startswith(('|', '![[', '- ', '---', '>')):
            continue
        if re.findall(r'\[\d+\]', line) and not re.search(r'\[\[.+?\]\]', line):
            issues.append(f"  ❌ L{i}: [N] 引用缺少 wikilink: {line.strip()[:80]}...")

    # 7. LaTeX $ 未闭合（渲染级错误）
    for i, line in enumerate(content.split('\n'), 1):
        # 跳过代码块和 frontmatter
        if line.strip().startswith('```') or line.strip().startswith('---'):
            continue
        # 行内 $ 必须成对（排除 $$ 块级）
        # 先剥离 wikilink，防止文件名中 $ 被误当 LaTeX
        clean_line = re.sub(r'\[\[.*?\]\]', '', line)
        single_dollar = clean_line.count('$') - clean_line.count('$$') * 2
        if single_dollar % 2 != 0:
            issues.append(f"  ❌ L{i}: LaTeX $ 未闭合: {line.strip()[:80]}...")

    # 8. 技术全景表类别列检查（核心/约束/邻域）
    in_panorama = False
    for i, line in enumerate(content.split('\n'), 1):
        if '## 技术全景' in line:
            in_panorama = True
            continue
        if in_panorama and line.strip().startswith('## '):
            break
        if not in_panorama or not line.strip().startswith('|'):
            continue
        if '---' in line or '技术方向' in line or '类别' in line:
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) < 2:
            continue
        cat = cells[1] if len(cells) > 1 else ''
        if cat not in ('核心', '约束', '邻域', ':---:', ''):
            issues.append(f"  ⚠️ L{i}: 全景表类别不是 核心/约束/邻域: '{cat[:20]}'")

    return issues


# ─────────────────────────────────────────────
# 论文/专利 frontmatter 字段检查
# ─────────────────────────────────────────────

# Semantic fields (background, core_innovation, etc.) are filled by Obsidian
# knowledge-base tooling, not by the pipeline.  Gate 1 only enforces the
# bibliographic fields the report actually needs for citations.
PAPER_FIELDS: list[str] = []
PATENT_FIELDS = [
    "background", "core_innovation", "critical_topology",
    "problem_solved", "solution_overview", "key_embodiments",
    "process_technology", "limitations",
]


def check_paper_fm(md_path: pathlib.Path) -> list[str]:
    """检查论文/专利 MD 的 frontmatter 字段是否填写（空字段检测）。"""
    issues = []
    content = md_path.read_text(encoding="utf-8")
    fm_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not fm_match:
        return ["  ❌ 无 frontmatter"]
    fm = fm_match.group(1)
    is_patent = bool(re.search(r'(^|/)patent', str(md_path), re.IGNORECASE))
    fields = PATENT_FIELDS if is_patent else PAPER_FIELDS
    # 占位符黑名单（精确匹配）和模式（子串匹配）
    placeholder_words = {'待提取', 'TBD', 'Unknown', 'TODO', 'N/A', 'NA', 'pending', 'PENDING'}
    placeholder_patterns = [
        r'^待',                       # 任何以"待"开头的值（待提取/待补充/待细节提取/…）
        r'^(TBD|TODO|Unknown|N/A)',  # 开头
    ]

    for field in fields:
        m = re.search(rf'^{field}\s*:\s*(.+)', fm, re.MULTILINE)
        if not m:
            issues.append(f"  ❌ 缺少字段: {field}")
            continue
        val = m.group(1).strip().strip('"').strip("'")
        if not val or val in ('""', "''"):
            issues.append(f"  ⚠️ 字段为空: {field}")
        elif val in placeholder_words:
            issues.append(f"  ⚠️ 字段为占位符: {field} = '{val}'")
        elif any(re.search(p, val, re.IGNORECASE) for p in placeholder_patterns):
            issues.append(f"  ⚠️ 字段含占位词: {field} = '{val[:60]}...'")
    return issues


def find_missing_fm(papers_dir: str | None = None) -> dict:
    scan = VAULT / (papers_dir if papers_dir else "ieee_paper_md")
    results = {}
    for md in sorted(scan.rglob("*.md")):
        if "/auto/" in str(md) or "/images/" in str(md):
            continue
        issues = check_paper_fm(md)
        if issues:
            results[str(md.relative_to(VAULT))] = issues
    return results


# ─────────────────────────────────────────────
# NEW: YAML 语法 + LaTeX 残留 + 作者字段检查
# ─────────────────────────────────────────────

LATEX_PATTERN = re.compile(
    r'\$[^$\n]+\$'          # $...$
    r'|\\\w+'               # \cmd
    r'|\{[^}]*\}'           # {...}
)

def lint_paper_yaml(md_path: pathlib.Path) -> list[str]:
    """
    检查单篇论文/专利 MD：
      1. YAML 语法是否合法（裸冒号、特殊字符等）
      2. authors 字段是否含 LaTeX 残留和噪声词
      3. 其他关键字段是否含 LaTeX 残留
    """
    issues = []
    text = md_path.read_text(encoding="utf-8")
    parts = text.split('---')
    if len(parts) < 3:
        return []
    fm_raw = parts[1]

    # 1. YAML 语法
    if YAML_AVAILABLE:
        try:
            data = yaml.safe_load(fm_raw)
        except yaml.YAMLError as e:
            # 提取行号
            mark = getattr(e, 'problem_mark', None)
            loc = f" (行 {mark.line + 1})" if mark else ""
            issues.append(f"  ❌ YAML 语法错误{loc}: {str(e)[:120]}")
            return issues  # 语法错误时后续检查无意义
    else:
        data = {}

    # 2. authors 字段检查
    authors = data.get('authors', []) if data else []
    # 单词噪声库：包含简短词、固定噪声词、复合噪声词
    noise_words = {
        'Graduate', 'Member', 'Student', 'IEEE', 'Senior', 'Junior',
        '待提取', 'TBD', 'Unknown', 'et', 'al', 'et al', 'PhD', 'MSc'
    }
    # 复合噪声词（子串匹配）
    noise_patterns = [
        r'Graduate\s+Student', r'Member\s+(IEEE|of)',
        r'Senior\s+Member', r'Junior\s+Member',
        r'^[A-Z]\.?\s+[A-Z]\.$',  # 单初字母形式 "J. D."
    ]
    noise_regex = re.compile('|'.join(noise_patterns), re.IGNORECASE)

    if isinstance(authors, list):
        for a in authors:
            a_str = str(a).strip()
            if not a_str:
                continue
            # LaTeX 残留
            if LATEX_PATTERN.search(a_str):
                issues.append(f"  ⚠️ authors 含 LaTeX: {a_str[:60]}")
            # 单词噪声（精确匹配）
            if a_str in noise_words:
                issues.append(f"  ⚠️ authors 含噪声词: '{a_str}'")
            # 复合噪声词（子串匹配）
            if noise_regex.search(a_str):
                issues.append(f"  ⚠️ authors 含复合噪声: '{a_str}'")
            # 姓名过短（<3 字符）
            if len(a_str) < 3:
                issues.append(f"  ⚠️ authors 疑似截断: '{a_str}'")
    elif authors and not isinstance(authors, str):
        # 作者字段应是列表或字符串，非法类型报错
        issues.append(f"  ⚠️ authors 字段类型异常: {type(authors).__name__}")

    # 3. 其他关键字段 LaTeX 残留（论文和专利共同字段）
    check_fields = PAPER_FIELDS + PATENT_FIELDS + ['title']
    for field in set(check_fields):  # 去重
        val = data.get(field, '') if data else ''
        if val and isinstance(val, str) and LATEX_PATTERN.search(val):
            issues.append(f"  ⚠️ {field} 含 LaTeX 残留: {val[:60]}")

    return issues


# ─────────────────────────────────────────────
# NEW: 专利分类 + inbox 残留检查
# ─────────────────────────────────────────────

def lint_patents() -> list[str]:
    """
    检查专利库：
      1. inbox 下有无未分类的 MD（转换后应移走）
      2. 各 IPC 目录下专利的 ipc_class 字段是否与目录名一致
    """
    issues = []
    patent_root = VAULT / "patent_md"
    if not patent_root.exists():
        return ["  ❌ patent_md/ 目录不存在"]

    # 1. inbox 残留
    inbox = patent_root / "inbox"
    if inbox.exists():
        mds = [f for f in inbox.rglob("*.md") if "/images/" not in str(f)]
        if mds:
            issues.append(f"  ❌ inbox 有 {len(mds)} 篇未分类专利（阻塞：转换后必须移至 IPC 目录）：")
            for f in mds:
                issues.append(f"    - {f.parent.name}")

    # 2. ipc_class 与目录不匹配
    mismatch = []
    for md in patent_root.rglob("*.md"):
        if "/images/" in str(md) or "/inbox/" in str(md):
            continue
        text = md.read_text(encoding="utf-8")
        fm_match = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
        if not fm_match:
            continue
        fm = fm_match.group(1)
        m = re.search(r'^ipc_class\s*:\s*(.+)', fm, re.MULTILINE)
        if not m:
            continue
        ipc_in_fm = m.group(1).strip().strip('"').strip("'")
        actual_dir = md.parent.parent.name  # patent_md/<IPC>/<专利目录>/xxx.md
        if ipc_in_fm and ipc_in_fm != actual_dir and ipc_in_fm not in ('inbox', ''):
            mismatch.append(f"    - {md.parent.name}: frontmatter '{ipc_in_fm}' ≠ 目录 '{actual_dir}'")
    if mismatch:
        issues.append(f"  ⚠️ {len(mismatch)} 篇专利 ipc_class 与目录不一致：")
        issues.extend(mismatch)

    return issues


def _count_criticals(issues: list[str]) -> int:
    """Count ❌-prefixed issues (critical, should block)."""
    return sum(1 for i in issues if i.strip().startswith('❌'))


# ─────────────────────────────────────────────
# main
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="检查研究报告格式完整性")
    parser.add_argument("report", nargs="?", help="报告路径（相对 vault）")
    parser.add_argument("--all", action="store_true", help="检查所有报告")
    parser.add_argument("--papers", nargs="?", const="", metavar="DIR",
                        help="检查论文 frontmatter 空字段（可选指定子目录）")
    parser.add_argument("--papers-brief", action="store_true",
                        help="论文检查仅统计，不逐篇列出")
    parser.add_argument("--lint-papers", nargs="?", const="", metavar="DIR",
                        help="YAML 语法 + LaTeX 残留扫描（可选指定子目录，默认 ieee_paper_md/）")
    parser.add_argument("--lint-patents", action="store_true",
                        help="专利 inbox 残留 + ipc_class 分类一致性检查")
    args = parser.parse_args()

    # ── --lint-papers ──
    if args.lint_papers is not None:
        if not YAML_AVAILABLE:
            print("⚠️  缺少 pyyaml，YAML 语法检查不可用。运行: pip install pyyaml")
        base = VAULT / (args.lint_papers if args.lint_papers else "ieee_paper_md")
        mds = [f for f in sorted(base.rglob("*.md"))
               if "/images/" not in str(f) and "/auto/" not in str(f)]
        total_issues = 0
        bad_files = []
        for md in mds:
            issues = lint_paper_yaml(md)
            if issues:
                bad_files.append((md, issues))
                total_issues += len(issues)
        if not bad_files:
            print(f"✅ {len(mds)} 篇论文/专利 YAML 语法正常，无 LaTeX 残留")
        else:
            criticals = _count_criticals(
                [i for _, issues in bad_files for i in issues])
            print(f"📊 {len(bad_files)} 篇有问题（共 {total_issues} 项，{criticals} 个致命）：\n")
            for md, issues in bad_files:
                print(f"  [[{md.relative_to(VAULT)}]]")
                for i in issues:
                    print(i)
        sys.exit(1 if any(_count_criticals(issues) > 0 for _, issues in bad_files) else 0)
        return

    # ── --lint-patents ──
    if args.lint_patents:
        issues = lint_patents()
        if not issues:
            print("✅ 专利库：inbox 无残留，ipc_class 分类一致")
        else:
            criticals = _count_criticals(issues)
            print(f"📊 专利库检查发现 {len([i for i in issues if i.strip().startswith('-') or '篇' in i])} 个问题（{criticals} 个致命）：\n")
            for i in issues:
                print(i)
        sys.exit(1 if _count_criticals(issues) > 0 else 0)
        return

    # ── --papers / --papers-brief ──
    if args.papers is not None:
        d = args.papers if args.papers else None
        results = find_missing_fm(d)
        if not results:
            print("✅ 所有论文 frontmatter 完整")
            criticals = 0
        else:
            all_issues = [i for issues in results.values() for i in issues]
            criticals = _count_criticals(all_issues)
            print(f"📊 {len(results)} 篇论文 frontmatter 有空字段（{criticals} 个致命）:\n")
            if args.papers_brief:
                for path, issues in results.items():
                    fields = [i.split(": ")[-1] for i in issues if "缺少" in i or "为空" in i]
                    print(f"  [[{path}]] — 缺 {', '.join(fields)}")
            else:
                for path, issues in results.items():
                    print(f"\n  [[{path}]]")
                    for i in issues:
                        print(f"    {i}")
        sys.exit(1 if criticals > 0 else 0)
        return

    # ── 报告检查 ──
    if args.all or not args.report:
        reports = sorted((VAULT / "wiki" / "research").glob("*_report_*.md"))
    else:
        rpath = VAULT / args.report
        if not rpath.exists():
            print(f"文件不存在: {rpath}")
            sys.exit(1)
        reports = [rpath]

    total_issues = 0
    total_criticals = 0
    for r in reports:
        issues = check_report(r)
        rel = r.relative_to(VAULT)
        if issues:
            criticals = sum(1 for i in issues if i.strip().startswith('❌'))
            print(f"\n📄 [[{rel}]] — {len(issues)} 个问题（{criticals} 个致命）:")
            for i in issues:
                print(i)
            total_issues += len(issues)
            total_criticals += criticals
        else:
            print(f"✅ [[{rel}]] — 无问题")

    if total_issues:
        print(f"\n📊 共 {total_issues} 个问题待修复（{total_criticals} 个致命）")
    else:
        print(f"\n✅ 全部 {len(reports)} 个报告通过检查")

    sys.exit(1 if total_criticals > 0 else 0)


if __name__ == "__main__":
    main()
