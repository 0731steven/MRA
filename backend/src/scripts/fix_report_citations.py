#!/usr/bin/env python3
"""报告正文 [N] 引用 → wikilink 批量替换。

从报告的参考文献表格自动提取映射（[N] → 文件名），
然后扫描正文，将 "Author Year [N]" 替换为 "[[filename|Author Year]] [N]"。

用法:
  python3 scripts/fix_report_citations.py wiki/research/my_report_20260514.md
  python3 scripts/fix_report_citations.py wiki/research/my_report_20260514.md --dry-run
"""

import argparse
import os
import pathlib
import re
import sys

VAULT = pathlib.Path(os.environ.get("WILSON_LIB_PATH", str(pathlib.Path.home() / "Documents" / "wilson_lib")))


def parse_ref_table(content: str) -> dict[int, dict]:
    """解析参考文献区域的所有 wikilink，按出现顺序建立 [N] → {filename, author_display} 映射。"""
    refs = {}
    ref_section = content.find('## 参考文献')
    if ref_section < 0:
        return refs
    # 截至下一个 ## header 或文件末尾
    next_header = content.find('\n##', ref_section + 1)
    ref_text = content[ref_section:next_header] if next_header >= 0 else content[ref_section:]

    # 在参考文献区域找所有 wikilink: [[filename|alias]] 或 [[filename\|alias]]
    # 注意表格内用 \| 转义
    pattern = re.compile(r'\[\[([^\]|\\]+?)(?:[\\]?\|([^\]]+?))?\]\]')

    idx = 1
    for m in pattern.finditer(ref_text):
        filename = m.group(1).strip()
        alias = m.group(2).strip() if m.group(2) else filename
        refs[idx] = {
            'filename': filename,
            'author_display': alias,
        }
        idx += 1

    return refs


def _make_wikilink(filename: str, display: str) -> str:
    """生成 wikilink。"""
    if not filename:
        return display
    return f"[[{filename}|{display}]]"


def fix_citations(content: str, refs: dict[int, dict]) -> tuple[str, int, list[str]]:
    """替换正文中裸 [N] 为带 wikilink 的引用。返回 (新内容, 替换数, 未匹配列表)。"""
    replaced = 0
    unmatched: list[str] = []
    # 只处理正文部分（## 摘要 到 ## 参考文献 之间）
    abs_start = content.find('## 摘要')
    ref_start = content.find('## 参考文献')
    if abs_start < 0:
        return content, 0
    body_end = ref_start if ref_start > 0 else len(content)

    header = content[:abs_start]
    body = content[abs_start:body_end]
    tail = content[body_end:]

    # 第一轮：查找 "Author [N]" 模式，将前面的作者名替换为 wikilink
    new_body = body
    for ref_n, ref in sorted(refs.items(), key=lambda x: -len(str(x[1].get('author_display', '')))):
        filename = ref.get('filename', '')
        author_full = ref.get('author_display', '')
        if not filename or not author_full:
            continue

        # 提取短作者名: 取第一个逗号前的最后词（姓）
        clean = author_full.replace(' et al.', '').replace(' et. al', '')
        first_author = clean.split(',')[0].strip()
        short_author = first_author.split()[-1] if first_author.split() else first_author

        # 从 filename 提取年份
        year_match = re.search(r'(20\d{2})', filename)
        year = year_match.group(1) if year_match else ''
        display_name = f"{short_author} {year}" if year else short_author
        wl = _make_wikilink(filename, display_name)

        escaped = re.escape(short_author)
        # 模式: short_author ... [N]（中间可有年份/期刊名等）
        pattern = rf'\b({escaped})\b([^\[]*)\[{ref_n}\]'
        wl_captured = wl  # capture for closure

        def make_replacement(m, _wl=wl_captured, _n=ref_n):
            return f'{_wl} [{_n}]'

        # 逐行替换，跳过已有正确 wikilink 的行
        lines_out = []
        for line in new_body.split('\n'):
            if '[[' in line:
                lines_out.append(line)
                continue
            new_line = re.sub(pattern, make_replacement, line)
            if new_line != line:
                replaced += 1
            lines_out.append(new_line)
        new_body = '\n'.join(lines_out)

    # 第二轮（兜底）：把正文中所有仍然残留的裸 [N] 直接插入 wikilink
    # 只处理前面没有 ]] 的裸 [N]（避免重复处理已带 wikilink 的引用）
    def _fallback_replace(line: str) -> tuple[str, int]:
        count = 0
        # 从后往前替换，避免偏移问题
        for m in reversed(list(re.finditer(r'\[(\d+)\]', line))):
            n_val = int(m.group(1))
            if n_val not in refs:
                continue
            before = line[:m.start()].rstrip()
            # 已经有 wikilink 紧跟在前面，跳过
            if before.endswith(']]'):
                continue
            ref_entry = refs[n_val]
            filename = ref_entry.get('filename', '')
            author_full = ref_entry.get('author_display', '')
            if not filename:
                continue
            wl = _make_wikilink(filename, author_full)
            line = line[:m.start()] + f'{wl} [{n_val}]' + line[m.end():]
            count += 1
            log_entry = f"[{n_val}] 裸引用 → 自动补全 wikilink"
            if log_entry not in unmatched:
                unmatched.append(log_entry)
        return line, count

    lines_out = []
    for line in new_body.split('\n'):
        new_line, cnt = _fallback_replace(line)
        replaced += cnt
        lines_out.append(new_line)
    new_body = '\n'.join(lines_out)

    result = header + new_body + tail
    return result, replaced, unmatched


def main():
    parser = argparse.ArgumentParser(
        description="批量替换报告正文中的 [N] 引用为 wikilink"
    )
    parser.add_argument("report", help="报告路径（相对 vault）")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写入")
    args = parser.parse_args()

    rpath = pathlib.Path(args.report)
    if not rpath.is_absolute():
        rpath = VAULT / args.report
    if not rpath.exists():
        print(f"文件不存在: {rpath}")
        sys.exit(1)

    content = rpath.read_text(encoding='utf-8')
    refs = parse_ref_table(content)
    print(f"[refs] 解析到 {len(refs)} 条参考文献")

    if not refs:
        # 区分：完全没有表 vs 表存在但缺 wikilink
        ref_section = content.find('## 参考文献')
        if ref_section >= 0:
            next_header = content.find('\n##', ref_section + 1)
            ref_text = content[ref_section:next_header] if next_header >= 0 else content[ref_section:]
            if re.search(r'^\|.*\|.*\|', ref_text, re.MULTILINE):
                print("[warn] 参考文献表格缺少 wikilink，请在作者列添加 [[文件名|作者]] 后重试")
                sys.exit(1)
        print("[warn] 未找到参考文献表格，退出")
        sys.exit(1)

    new_content, count, unmatched = fix_citations(content, refs)
    print(f"[fix ] 替换了 {count} 处引用")
    if unmatched:
        print(f"[warn] {len(unmatched)} 处 [N] 引用未匹配（缺 wikilink）：")
        for u in unmatched[:20]:
            print(f"  {u}")

    if args.dry_run:
        print("\n--- 预览差异（前 50 行变化）---")
        import difflib
        old_lines = content.split('\n')
        new_lines = new_content.split('\n')
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=''))
        for d in diff[:50]:
            print(d)
        return

    rpath.write_text(new_content, encoding='utf-8')
    print(f"[ok  ] 已写入 {rpath.name}")


if __name__ == "__main__":
    main()
