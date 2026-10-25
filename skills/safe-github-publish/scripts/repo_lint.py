#!/usr/bin/env python3
"""仓库发布格式检查：README 结构、LICENSE、.gitignore、相对链接、Mermaid 图表。

GitHub 在 Linux 上提供文件服务，链接大小写必须与实际文件完全一致，本工具按此标准检查。
退出码：2 = 存在格式错误（error）；1 = 存在警告（warn）；0 = 通过。
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

VERSION = "2.1.0"

README_NAMES = ["README.md", "readme.md", "Readme.md"]
LICENSE_NAMES = re.compile(r"(?i)^licen[cs]e(\.|$|^)|(?:copying|notice)(?:\.|$)")
CHANGELOG_NAMES = re.compile(r"(?i)^change[_-]?log")
QUICK_START_HEADINGS = re.compile(
    r"(?i)quick\s*start|getting\s*started|installation|install|usage|快速开始|快速開始|安装|安裝|使用|入门|入門|快速上手"
)
MERMAID_KEYWORDS = re.compile(
    r"(?i)^\s*(?:flowchart|graph\s|graph\s*[TBRL]|sequenceDiagram|stateDiagram|erDiagram|"
    r"classDiagram|journey|gantt|pie|mindmap|timeline|quadrantChart|gitGraph|sankey|xychart)"
)
LINK_PATTERN = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)[^)]*\)")
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)\s]+)[^)]*\)")
REFERENCE_PATTERN = re.compile(r"(?m)^ {0,3}\[(?!\^)[^\]]+\]:\s*<?([^\s>]+)>?")  # [^1]: 是脚注不是链接
HTML_LINK_PATTERN = re.compile(r"""(?i)<(?:a|img|source|video)\b[^>]*?\b(?:href|src)\s*=\s*["']([^"'\s]+)""")
MAX_BADGES = 6
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "data:", "//")


def git_files(root: Path) -> list[str] | None:
    """tracked + 未忽略的 untracked 文件，即会被推送的候选集；非 git 仓库返回 None。"""
    try:
        proc = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
                              capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [item for item in proc.stdout.decode("utf-8", errors="surrogateescape").split("\0") if item]


def walk_repo(root: Path) -> tuple[dict[str, set[str]], bool]:
    """返回 ({小写相对路径 -> 实际路径集合}, 是否来自 git 候选集)，用于大小写敏感匹配。

    git 仓库里只收录会被推送的文件：链接指向被 .gitignore 忽略的文件，本地能打开，GitHub 上是坏链。
    """
    index: dict[str, set[str]] = {}

    def add(rel: str) -> None:
        index.setdefault(rel.lower(), set()).add(rel)
        parent = posixpath.dirname(rel)
        while parent:
            index.setdefault(parent.lower(), set()).add(parent)
            parent = posixpath.dirname(parent)

    files = git_files(root)
    if files is not None:
        for rel in files:
            add(rel)
        return index, True
    for current, dirs, names in os.walk(root):
        if ".git" in dirs:
            dirs.remove(".git")
        base = Path(current)
        for entry in dirs + names:
            try:
                add((base / entry).relative_to(root).as_posix())
            except ValueError:
                continue
    return index, False


def split_fences(text: str) -> list[tuple[str, bool]]:
    """按行拆分并标记是否处于代码围栏内。"""
    result: list[tuple[str, bool]] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            result.append((line, in_fence))
            in_fence = not in_fence
        else:
            result.append((line, in_fence))
    return result


def check_readme(root: Path, readme: Path, index: dict[str, set[str]], findings: list[dict],
                 from_git: bool = False) -> None:
    try:
        readme_dir = readme.parent.relative_to(root).as_posix()
    except ValueError:
        readme_dir = "."
    try:
        text = readme.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        findings.append({"severity": "error", "check": "readme-readable", "message": f"README 无法读取: {type(error).__name__}"})
        return
    lines = split_fences(text)

    h1_count = 0
    for line, fenced in lines:
        if not fenced and line.startswith("# "):
            h1_count += 1
    if h1_count == 0:
        findings.append({"severity": "error", "check": "readme-title", "message": "README 缺少一级标题（# 项目名）"})
    elif h1_count > 1:
        findings.append({"severity": "warn", "check": "readme-title", "message": f"README 有 {h1_count} 个一级标题，应只保留 1 个"})

    if not text.lstrip().startswith("#"):
        first_nonempty = next((ln for ln, _ in lines if ln.strip()), "")
        if first_nonempty and not first_nonempty.startswith("#"):
            findings.append({"severity": "warn", "check": "readme-first-screen", "message": "README 首行不是标题，首屏应先呈现项目名与一句话描述"})

    has_quick_start = any(
        (not fenced) and re.match(r"^#{1,6}\s", line) and QUICK_START_HEADINGS.search(line)
        for line, fenced in lines
    )
    if not has_quick_start:
        findings.append({"severity": "error", "check": "readme-quick-start", "message": "README 缺少快速开始/安装/使用章节（Quick start / Installation / 使用）"})

    badge_count = 0
    for match in IMAGE_PATTERN.finditer(text):
        if match.group(1).startswith("https://img.shields.io") or match.group(1).startswith("https://badge"):
            badge_count += 1
    if badge_count > MAX_BADGES:
        findings.append({"severity": "warn", "check": "readme-badges", "message": f"badge 数量 {badge_count} 超过 {MAX_BADGES}，只保留可验证的状态"})

    headings = []
    for i, (line, fenced) in enumerate(lines):
        if fenced:
            continue
        match = re.match(r"^(#{1,6})\s", line)
        if match:
            headings.append((i + 1, len(match.group(1)), line))
    for idx in range(len(headings) - 1):
        line_no, level, heading = headings[idx]
        next_line_no, next_level, _ = headings[idx + 1]
        if next_level > level:
            continue  # 容器标题：直接进入子章节，属正当结构，不算空
        between = [ln for ln, _ in lines[line_no:next_line_no - 1] if ln.strip()]
        if not between:
            findings.append({"severity": "warn", "check": "readme-empty-section", "message": f"空章节: 第 {line_no} 行 “{heading.strip()}”"})

    # 链接检查只针对围栏外的正文，避免检查代码示例中的链接
    unfenced_text = "\n".join(line for line, fenced in lines if not fenced)
    link_cache: dict[str, None] = {}
    patterns = (LINK_PATTERN, IMAGE_PATTERN, REFERENCE_PATTERN, HTML_LINK_PATTERN)
    for match in [m for pattern in patterns for m in pattern.finditer(unfenced_text)]:
        target = match.group(1)
        if target.lower().startswith(EXTERNAL_PREFIXES) or target.startswith(("#", "<")):
            continue
        target = target.split("#")[0].split("?")[0]
        if not target:
            continue
        # 中文文件名在链接里通常是百分号编码：docs/%E4%BD%BF%E7%94%A8.md
        decoded = unquote(target).rstrip("/")
        if decoded in link_cache:
            continue
        link_cache[decoded] = None
        # ../ 相对链接按 README 所在目录归一化到仓库根再匹配
        decoded = posixpath.normpath(posixpath.join(readme_dir, decoded)) if readme_dir != "." else decoded
        candidates = index.get(decoded.lower())
        if decoded == ".." or decoded.startswith("../"):
            # 指向检查根目录之外（如只检查子目录时链接仓库根的 LICENSE）：只能确认存在
            if not (root / decoded).exists():
                findings.append({"severity": "error", "check": "link-resolves", "message": f"相对链接目标不存在: {decoded}"})
            continue
        if not candidates and from_git and (root / decoded).exists():
            findings.append({"severity": "error", "check": "link-ignored", "message": f"链接目标被 .gitignore 忽略，推送后失效: {decoded}"})
        elif not candidates:
            findings.append({"severity": "error", "check": "link-resolves", "message": f"相对链接目标不存在: {decoded}"})
        elif decoded not in candidates:
            actual = next(iter(candidates))
            findings.append({"severity": "error", "check": "link-case", "message": f"链接大小写不匹配: {decoded} → 实际是 {actual}（GitHub 区分大小写）"})

    # mermaid 块本身是围栏，不能用 split_fences 的 fenced 标记跳过内容行，
    # 需要独立追踪围栏状态；外层代码块内的 ```mermaid 示例不算真块。
    in_any_fence = False
    in_mermaid = False
    mermaid_lines: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.lstrip()
        is_fence = stripped.startswith("```") or stripped.startswith("~~~")
        if is_fence:
            if in_mermaid:
                body = [item for item in mermaid_lines if item.strip()]
                if not body:
                    findings.append({"severity": "error", "check": "mermaid-block", "message": "空的 mermaid 代码块"})
                elif not any(MERMAID_KEYWORDS.search(item) for item in body):
                    findings.append({"severity": "error", "check": "mermaid-block", "message": "mermaid 块缺少合法图表类型（flowchart/sequenceDiagram/stateDiagram 等）"})
                in_mermaid = False
            elif not in_any_fence and stripped.startswith("```mermaid"):
                in_mermaid = True
                mermaid_lines = []
            in_any_fence = not in_any_fence
        elif in_mermaid:
            mermaid_lines.append(raw_line)
    if in_mermaid:
        findings.append({"severity": "error", "check": "mermaid-block", "message": "mermaid 代码块未闭合"})


def lint(root: Path) -> list[dict]:
    findings: list[dict] = []
    index, from_git = walk_repo(root)
    names = {entry.name for entry in root.iterdir()}

    readme = next((root / name for name in README_NAMES if (root / name).is_file()), None)
    readme_any = next((n for n in names if n.lower() == "readme.md"), None)
    if readme is None:
        if readme_any:
            findings.append({"severity": "error", "check": "readme-name", "message": f"README 文件名应为 README.md（当前: {readme_any}）"})
            readme = root / readme_any
        else:
            findings.append({"severity": "error", "check": "readme-exists", "message": "缺少 README.md"})
    if readme is not None and readme.is_file():
        check_readme(root, readme, index, findings, from_git)

    if not any(LICENSE_NAMES.match(n) for n in names):
        findings.append({"severity": "warn", "check": "license-exists", "message": "缺少 LICENSE 文件；发布前应让用户选择许可证"})
    if not any(n.lower() == ".gitignore" for n in names):
        findings.append({"severity": "warn", "check": "gitignore-exists", "message": "缺少 .gitignore"})
    if any(CHANGELOG_NAMES.match(n) for n in names):
        pass
    else:
        findings.append({"severity": "info", "check": "changelog-exists", "message": "无 CHANGELOG（存在有意义版本时建议添加）"})

    return findings


def main() -> int:
    # 英文 locale 的 Windows 管道默认 cp1252，输出中文会 UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", help="项目根目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--version", action="version", version=f"repo_lint {VERSION}")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print("项目根目录不存在。", file=sys.stderr)
        return 2

    findings = lint(root)
    counts = {"error": 0, "warn": 0, "info": 0}
    for item in findings:
        counts[item["severity"]] += 1

    if args.json:
        print(json.dumps({"findings": findings, "summary": counts, "linter": f"repo_lint/{VERSION}"}, ensure_ascii=False, indent=2))
    else:
        for item in findings:
            print(f"{item['severity'].upper()} [{item['check']}] {item['message']}")
        print(f"Summary: error={counts['error']} warn={counts['warn']} info={counts['info']}")

    if counts["error"]:
        return 2
    if counts["warn"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
