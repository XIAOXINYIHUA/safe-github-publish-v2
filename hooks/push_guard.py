#!/usr/bin/env python3
"""PreToolUse 守卫：发布类命令执行前扫描密钥，存在 high 项时以退出码 2 阻断。

拦截与扫描范围：
- git push [<remote>]：工作区 + staged + 目标 remote 尚未包含的提交（含标签）；
  目标是 URL 或未配置的 remote 时，对方已有什么不可知，扫描全部历史
- gh repo create、gh repo edit --visibility public、gh api 改为公开：会暴露全部历史，扫描全量
- gh release create|upload、gh pr create：与默认 remote 比较的未推送提交

命令按 && || ; | 与换行拆段，跟踪 cd / pushd / Set-Location 与 git -C 定位仓库。
扫描出错时阻断（fail-closed）。输出只含路径/规则/行号，绝不含命中值。
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCAN_SCRIPTS = PLUGIN_ROOT / "skills" / "safe-github-publish" / "scripts"
BASELINE_NAME = ".safe-publish-baseline.json"

CD_COMMANDS = {"cd", "pushd", "chdir", "set-location", "sl"}
WRAPPERS = {"sudo", "env", "command", "exec", "time", "nohup"}
SHELLS = {"bash", "sh", "zsh", "pwsh", "powershell"}
SHELL_COMMAND_FLAGS = {"-c", "-command"}
GIT_VALUE_OPTIONS = {"-c", "--git-dir", "--work-tree", "--namespace"}
PUSH_VALUE_OPTIONS = {"-o", "--push-option", "--receive-pack", "--exec"}
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
MSYS_DRIVE = re.compile(r"^/([A-Za-z])(?=/|$)")

Target = tuple[Path, str, "str | None"]  # (目录, 种类 push/full/default, push 的 remote 参数)


def split_segments(command: str, posix: bool = True) -> list[str]:
    """按 && || ; | & 与换行拆段；引号内的分隔符不拆。"""
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(command):
        ch = command[i]
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            elif posix and ch == "\\" and quote == '"' and i + 1 < len(command):
                current.append(command[i + 1])
                i += 1
        elif ch in "\"'":
            quote = ch
            current.append(ch)
        elif posix and ch == "\\" and i + 1 < len(command):
            current.extend(command[i:i + 2])
            i += 1
        elif ch in ";&|\n":
            segments.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    segments.append("".join(current))
    return [segment.strip() for segment in segments if segment.strip()]


def tokenize(segment: str, posix: bool = True) -> list[str]:
    lexer = shlex.shlex(segment, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    if not posix:
        lexer.escape = ""  # PowerShell：反斜杠是路径分隔符，不是转义
    try:
        return list(lexer)
    except ValueError:
        return segment.split()


def resolve_dir(cwd: Path, dest: str) -> Path:
    dest = os.path.expanduser(dest)
    if os.name == "nt":
        dest = MSYS_DRIVE.sub(lambda m: m.group(1) + ":", dest)  # Git Bash 的 /c/Users → C:/Users
    path = Path(dest)
    return path if path.is_absolute() else cwd / path


def parse_git(args: list[str], cwd: Path) -> Target | None:
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "-C" and i + 1 < len(args):
            cwd = resolve_dir(cwd, args[i + 1])
            i += 2
        elif arg in GIT_VALUE_OPTIONS and i + 1 < len(args):
            i += 2
        elif arg.startswith("-"):
            i += 1
        else:
            break
    if i >= len(args) or args[i] != "push":
        return None
    rest = args[i + 1:]
    remote: str | None = None
    j = 0
    while j < len(rest):
        arg = rest[j]
        if arg == "--":
            remote = rest[j + 1] if j + 1 < len(rest) else None
            break
        if arg.startswith("--repo="):
            remote = arg.split("=", 1)[1]
            break
        if arg == "--repo" and j + 1 < len(rest):
            remote = rest[j + 1]
            break
        if arg in PUSH_VALUE_OPTIONS and j + 1 < len(rest):
            j += 2
        elif arg.startswith("-"):
            j += 1
        else:
            remote = arg
            break
    return (cwd, "push", remote)


def option_value(args: list[str], *names: str) -> str | None:
    for i, arg in enumerate(args):
        for name in names:
            if arg == name and i + 1 < len(args):
                return args[i + 1]
            if name.startswith("--") and arg.startswith(name + "="):
                return arg.split("=", 1)[1]
    return None


def parse_gh(args: list[str], cwd: Path) -> Target | None:
    # -R/--repo 指向的远端仓库无法在本地扫描，仍以命令所在仓库近似
    command = args[:2]
    if command == ["repo", "create"]:
        source = option_value(args, "--source", "-s")
        return (resolve_dir(cwd, source) if source else cwd, "full", None)
    if command == ["repo", "edit"]:
        visibility = option_value(args, "--visibility")
        return (cwd, "full", None) if visibility and visibility.lower() == "public" else None
    if args[:1] == ["api"]:
        if any(arg.lower().endswith(("private=false", "visibility=public")) for arg in args):
            return (cwd, "full", None)
        return None
    if command in (["release", "create"], ["release", "upload"], ["pr", "create"]):
        return (cwd, "default", None)
    return None


def publish_targets(command: str, base: Path, posix: bool = True) -> list[Target]:
    cwd = base
    targets: list[Target] = []
    for segment in split_segments(command, posix):
        tokens = tokenize(segment, posix)
        if tokens:
            tokens[0] = tokens[0].lstrip("({")
            if not tokens[0]:
                tokens = tokens[1:]
        while tokens and (tokens[0] in WRAPPERS or (posix and ENV_ASSIGNMENT.match(tokens[0]))):
            tokens = tokens[1:]
        if not tokens:
            continue
        name = Path(tokens[0].replace("\\", "/")).name.lower().removesuffix(".exe")
        if name in CD_COMMANDS:
            dest = next((t for t in tokens[1:] if not t.startswith("-")), None)
            if dest:
                cwd = resolve_dir(cwd, dest)
        elif name in SHELLS or name == "eval":
            inner = " ".join(tokens[1:]) if name == "eval" else next(
                (tokens[i + 1] for i, t in enumerate(tokens[:-1]) if t.lower() in SHELL_COMMAND_FLAGS), None)
            if inner:
                targets.extend(publish_targets(inner, cwd, posix=name not in {"pwsh", "powershell"}))
        elif name == "git":
            target = parse_git(tokens[1:], cwd)
            if target:
                targets.append(target)
        elif name == "gh":
            target = parse_gh(tokens[1:], cwd)
            if target:
                targets.append(target)
    return targets


def git_lines(root: Path, *args: str) -> list[str] | None:
    try:
        proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [line for line in proc.stdout.splitlines() if line]


def repo_toplevel(directory: Path) -> Path | None:
    lines = git_lines(directory, "rev-parse", "--show-toplevel")
    return Path(lines[0]) if lines else None


def default_push_remote(root: Path, remotes: set[str]) -> str | None:
    branch = (git_lines(root, "symbolic-ref", "--short", "-q", "HEAD") or [""])[0]
    keys = ["remote.pushDefault"]
    if branch:
        keys = [f"branch.{branch}.pushRemote", *keys, f"branch.{branch}.remote"]
    for key in keys:
        value = (git_lines(root, "config", "--get", key) or [""])[0]
        if value in remotes:
            return value
    if "origin" in remotes:
        return "origin"
    return next(iter(remotes)) if len(remotes) == 1 else None


def resolve_scope(root: Path, kind: str, remote_arg: str | None) -> tuple[bool, str | None]:
    """返回 (是否扫描全部历史, 比较的 remote)；remote 为 None 时与任意 remote 比较。"""
    if kind == "full":
        return True, None
    remotes = set(git_lines(root, "remote") or [])
    if kind == "push" and remote_arg is not None:
        return (False, remote_arg) if remote_arg in remotes else (True, None)
    return False, default_push_remote(root, remotes)


def baseline_changed(root: Path, full: bool, remote: str | None) -> bool:
    """基线文件是否在待发布的改动里被修改：豁免条目只能由人工确认。"""
    if git_lines(root, "status", "--porcelain", "--", BASELINE_NAME):
        return True
    if full:
        return False
    not_on = f"--remotes={remote}" if remote else "--remotes"
    return bool(git_lines(root, "log", "--format=%h", "--branches", "--tags", "--not", not_on,
                          "--", BASELINE_NAME))


def guard(targets: list[Target]) -> int:
    sys.path.insert(0, str(SCAN_SCRIPTS))
    import security_scan

    blocked = False
    notes: list[str] = []
    asks: list[str] = []
    seen: set[tuple[str, bool, str | None]] = set()
    for directory, kind, remote_arg in targets:
        root = repo_toplevel(directory)
        if root is None:
            continue  # 不在 git 仓库内（如不带 --source 的 gh repo create）
        full, remote = resolve_scope(root, kind, remote_arg)
        if (str(root), full, remote) in seen:
            continue
        seen.add((str(root), full, remote))

        result = security_scan.scan(root, scan_history_flag=full, staged_flag=True, unpushed_flag=not full,
                                    baseline_path=root / BASELINE_NAME, remote=remote)
        scope = "全部历史" if full else (f"{remote} 尚未包含的提交" if remote else "未推送的提交")
        if result["summary"]["high"]:
            blocked = True
            print(f"safe-github-publish 守卫：{root.name}（工作区 + staged + {scope}）检测到未处置的高风险项，"
                  "已阻断发布类命令。", file=sys.stderr)
            for item in result["findings"]:
                if item["severity"] != "high":
                    continue
                location = item["path"] + (f":{item['line']}" if "line" in item else "")
                label = "" if item.get("scope", "worktree") == "worktree" else f" [{item['scope']}]"
                print(f"HIGH {location} {item['rule']}{label}", file=sys.stderr)
        elif result["summary"]["medium"]:
            notes.append(f"safe-github-publish 守卫：{root.name} 有 {result['summary']['medium']} 个中风险项请复核（未阻断）。")
        if baseline_changed(root, full, remote):
            asks.append(f"{root.name} 的 {BASELINE_NAME} 在待发布的改动中被修改（当前豁免 {result['accepted']} 项）")

    if blocked:
        print("处置后重试：修复或移除敏感项，误报经人工审核写入 .safe-publish-baseline.json。", file=sys.stderr)
        return 2
    for note in notes:
        print(note, file=sys.stderr)
    if asks:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "safe-github-publish 守卫：" + "；".join(asks) + "。基线豁免须经人工审核，确认后再发布。",
        }}, ensure_ascii=False))
    return 0


def main() -> int:
    # 英文 locale 的 Windows 管道默认 cp1252，输出中文会 UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    tool_input = event.get("tool_input") if isinstance(event, dict) else None
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if not isinstance(command, str) or not command.strip():
        return 0
    base = Path(event.get("cwd") or os.getcwd())
    targets = publish_targets(command, base, posix=event.get("tool_name") != "PowerShell")
    if not targets:
        return 0
    try:
        return guard(targets)
    except Exception as error:  # 守卫必须 fail-closed：扫不了就不放行
        print(f"safe-github-publish 守卫：扫描异常（{type(error).__name__}），已阻断发布类命令。"
              "修复环境后重试，确需跳过时由用户在终端手动执行。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
