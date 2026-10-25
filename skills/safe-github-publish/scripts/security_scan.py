#!/usr/bin/env python3
"""GitHub 发布前安全扫描：工作区候选集 + Git 历史 + staged diff。

设计约束：绝不打印命中的敏感值，绝不输出扫描根目录的绝对路径。
退出码：2 = 存在未接受的高风险项（阻断）；1 = 存在需人工复核项；0 = 未命中。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

VERSION = "2.1.0"

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".cache",
    ".next", ".nuxt", "build", "coverage", "dist", "out", "target", "vendor",
    ".idea", ".vscode", ".gradle", ".terraform",
}
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_EXIF_BYTES = 64 * 1024
MAX_HISTORY_BYTES = 200 * 1024 * 1024

# 锁文件只保留前缀锚定的高可信规则，避免把完整性哈希当凭据。
LOCK_FILE_NAMES = {
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
    "bun.lockb", "poetry.lock", "pipfile.lock", "uv.lock", "cargo.lock",
    "go.sum", "composer.lock", "gemfile.lock", "flake.lock", "mix.lock",
}

NAME_RULES = [
    ("private-env-file", "high", re.compile(r"(^|/)\.env(?:$|\.(?!(?:example|sample|template|dist)$)[^/]+$)", re.I)),
    ("private-env-file", "high", re.compile(r"(^|/)(?:prod(?:uction)?|staging)\.env$", re.I)),
    ("private-key-file", "high", re.compile(r"(^|/)(id_rsa|id_dsa|id_ecdsa|id_ed25519|.*\.(pem|key|p12|pfx|ppk|jks|kdbx|keystore))$", re.I)),
    ("credential-file", "high", re.compile(r"(^|/)(credentials?\.json|service[-_]?account.*\.json|\.git-credentials|\.netrc|auth\.json|cookies?\.json|kubeconfig|\.aws/credentials)$", re.I)),
    ("credential-file", "high", re.compile(r"(^|/)(?:\.docker/config\.json|\.kube/config)$", re.I)),
    ("secret-file", "high", re.compile(r"(^|/)(?:secrets?|vault)(?:\.[^/]+)?$", re.I)),
    ("terraform-state", "high", re.compile(r"\.tfstate(?:\..+)?$", re.I)),
    ("auth-config-file", "medium", re.compile(r"(^|/)(?:\.npmrc|\.pypirc|\.gem/credentials)$", re.I)),
    ("terraform-vars", "medium", re.compile(r"\.tfvars$", re.I)),
    ("os-junk-file", "medium", re.compile(r"(^|/)(?:\.DS_Store|Thumbs\.db|desktop\.ini|\.bash_history|\.zsh_history|.*\.swp)$", re.I)),
    ("agent-local-config", "medium", re.compile(r"(^|/)(?:\.claude/settings\.local\.json|\.zcode/)$", re.I)),
    ("local-database", "medium", re.compile(r"\.(sqlite3?|db|accdb|dump)$", re.I)),
    ("local-log", "medium", re.compile(r"\.(log|trace)$", re.I)),
    ("backup-file", "medium", re.compile(r"\.(?:bak|backup|old|orig)$", re.I)),
]


@dataclass(frozen=True)
class ContentRule:
    name: str
    severity: str
    pattern: re.Pattern[str]
    value_group: str | None = None
    strict: bool = False  # strict 规则在锁文件中仍然执行（前缀锚定的供应商格式）
    literal_only: bool = False  # 只报字面量：跳过代码表达式与界面文案


PLACEHOLDER_VALUE = re.compile(
    r"(?ix)^(?:"
    r"your[-_ ]?(?:api[-_ ]?key|token|secret|password)?|"
    r"replace[-_ ]?(?:me|this|with[-_ ]?.+)?|"
    r"example|sample|dummy|fake|test|changeme|change[-_ ]?me|"
    r"redacted|masked|placeholder|none|null|undefined|x{4,}|\*{4,}|"
    r"<[^>]+>|\$\{[^}]+\}|\$[a-z_]\w*|%[a-z_]\w*%|%\([^)]+\)s|"
    r".*(?:\.{3}|…).*"  # 文档里的省略示例：sk-proj-...
    r")$"
)

# 源代码里的字符串字面量必带引号，未加引号的值是变量或表达式（'password': password）；
# 例外是带前缀的字面量 b"..." / f"..." 与模板字符串，正则会把它们归入未加引号分支
SOURCE_SUFFIXES = {
    ".py", ".pyx", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte",
    ".go", ".java", ".kt", ".kts", ".scala", ".groovy", ".rb", ".php", ".cs", ".rs", ".swift",
    ".dart", ".c", ".h", ".cc", ".cpp", ".hpp", ".m", ".lua",
}
PREFIXED_LITERAL = re.compile(r"[bBrRuUfF]{0,2}[\"'`][^\"'`]{8,}")

# 未加引号的代码表达式读取的是运行时值而非字面量：
# os.getenv("X")、os.environ["X"]、process.env.X!、Optional[str]、request.form["password"]
CODE_EXPRESSION = re.compile(
    r"""(?x)
    [A-Za-z_$][\w$]{0,31}
    (?: \??\.[A-Za-z_$][\w$]{0,31}               # 属性访问（含可选链 ?.）
      | \( (?:"[^"]*"?|'[^']*'?|[\w$.]*) \)?     # 调用：参数可能被 , 截断而不闭合
      | \[ (?:"[^"]*"?|'[^']*'?|[\w$.]*) \]?     # 下标
    )*
    !?
    """
)

# 含空白或中日韩文字、且不含数字与 base64 符号的值是界面文案（"password": "Enter your password"）
PROSE_VALUE = re.compile(r"(?=.*[\s\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af])[^\d+/=]+")

CONTENT_RULES = [
    ContentRule("private-key-content", "high", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"), strict=True),
    ContentRule("github-token", "high", re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b"), strict=True),
    ContentRule("gitlab-token", "high", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"), strict=True),
    ContentRule("anthropic-token", "high", re.compile(r"\bsk-ant-(?:api|admin)-[A-Za-z0-9_-]{20,}\b"), strict=True),
    ContentRule("openai-style-token", "high", re.compile(r"\bsk-(?!ant-)(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Z])[A-Za-z0-9_-]{24,}\b"), strict=True),
    ContentRule("aws-access-key", "high", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), strict=True),
    ContentRule("google-api-key", "high", re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b"), strict=True),
    ContentRule("stripe-live-secret", "high", re.compile(r"\bsk_live_[A-Za-z0-9]{20,}\b"), strict=True),
    ContentRule("npm-token", "high", re.compile(r"\bnpm_[A-Za-z0-9]{30,}\b"), strict=True),
    ContentRule("pypi-token", "high", re.compile(r"\bpypi-[A-Za-z0-9_-]{40,}\b"), strict=True),
    ContentRule("huggingface-token", "high", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"), strict=True),
    ContentRule("slack-token", "high", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"), strict=True),
    ContentRule("telegram-bot-token", "high", re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b"), strict=True),
    ContentRule("sendgrid-key", "high", re.compile(r"\bSG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}\b"), strict=True),
    ContentRule(
        "credential-assignment",
        "high",
        re.compile(
            # 前缀段覆盖 OPENAI_API_KEY / MYSQL_ROOT_PASSWORD / AWS_SECRET_ACCESS_KEY；
            # 键后可选引号覆盖 JSON 与 dict 键，赋值符含 := 与 =>
            r"(?ix)\b(?:[a-z0-9]+[_-])*"
            r"(?:api[_-]?key|api[_-]?secret|app[_-]?secret|access[_-]?key|access[_-]?token|"
            r"auth[_-]?token|client[_-]?secret|secret|secret[_-]?key|password|passwd)\b"
            r"[\"']?\s*(?::=|=>|[:=])\s*"
            # 无引号分支不以引号开头，否则 "github_" 这类短字面量连引号凑够 8 位
            r"(?P<value>\"[^\"\r\n]{8,}\"|'[^'\r\n]{8,}'|[^\s#;,\"'][^\s#;,]{7,})"
        ),
        "value",
        literal_only=True,
    ),
    ContentRule(
        "authorization-header",
        "high",
        re.compile(r"(?i)\bauthorization\s*[:=]\s*(?:bearer|basic)\s+(?P<value>[A-Za-z0-9._~+/=-]{16,})"),
        "value",
    ),
    ContentRule("cloud-storage-key", "high", re.compile(r"(?i)\bAccountKey\s*=\s*(?P<value>[A-Za-z0-9+/=]{32,})"), "value", strict=True),
    ContentRule("credential-url", "high", re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s:/]+:(?P<value>[^\s/@]+)@"), "value"),
    ContentRule("jwt-like-token", "medium", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ContentRule(
        "internal-ip",
        "medium",
        re.compile(r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"),
    ),
    ContentRule("email-address", "medium", re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")),
    ContentRule("windows-user-path", "medium", re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\/\s]+")),
    ContentRule("unix-user-path", "medium", re.compile(r"(?:/Users/|/home/)[A-Za-z0-9._-]{2,}")),
]

# internal-ip 在容器编排示例里通常是合法演示值，跳过这些文件。
INTERNAL_IP_EXEMPT = re.compile(r"(?i)(?:^|/)(?:dockerfile[^/]*|docker-compose[^/]*\.ya?ml|compose\.ya?ml)$")

HIGH_ENTROPY_ASSIGNMENT = re.compile(
    r"(?ix)\b\w*(?:key|token|secret|password|passwd)\b[\"']?\s*[:=]\s*[\"'](?P<value>[A-Za-z0-9+/=_-]{20,})[\"']"
)
ENTROPY_THRESHOLD = 4.0


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    total = len(value)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def git_candidates(root: Path) -> list[Path] | None:
    try:
        check = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=10,
        )
        if check.returncode != 0:
            return None
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
            capture_output=True, timeout=30,
        )
        if proc.returncode != 0:
            return None
        items = proc.stdout.decode("utf-8", errors="surrogateescape").split("\0")
        return [root / item for item in items if item]
    except (OSError, subprocess.SubprocessError):
        return None


def tree_candidates(root: Path) -> list[Path]:
    result: list[Path] = []
    for current, dirs, files in os.walk(root):
        base = Path(current)
        kept_dirs: list[str] = []
        for name in dirs:
            path = base / name
            if path.is_symlink():
                result.append(path)
            elif name in SKIP_DIRS:
                if name == ".git" and base != root:
                    result.append(path)
            else:
                kept_dirs.append(name)
        dirs[:] = kept_dirs
        result.extend(base / name for name in files)
    return result


def relative_name(path: Path, root: Path) -> str:
    try:
        return path.absolute().relative_to(root.absolute()).as_posix()
    except (OSError, ValueError):
        return path.name


def is_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER_VALUE.fullmatch(value.strip().strip("\"'")))


def is_literal_secret(value: str, source_code: bool = False) -> bool:
    if value[:1] not in "\"'":
        if source_code and not PREFIXED_LITERAL.match(value):
            return False
        if CODE_EXPRESSION.fullmatch(value) and any(c in value for c in ".(["):
            return False
    return not PROSE_VALUE.fullmatch(value.strip("\"'"))


def is_outside_root(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve())
        return False
    except (OSError, ValueError):
        return True


def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def has_exif(data: bytes) -> bool:
    head = data[:MAX_EXIF_BYTES]
    if head.startswith(b"\xff\xd8"):  # JPEG
        return b"Exif\x00\x00" in head
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return b"eXIf" in head
    return False


class Findings:
    def __init__(self) -> None:
        self.items: list[dict] = []
        self._seen: set[tuple] = set()

    def add(self, severity: str, rule: str, path: str, line: int | None = None,
            scope: str = "worktree", commit: str | None = None) -> None:
        key = (severity, rule, path, line, scope)
        if key in self._seen:
            return
        self._seen.add(key)
        item = {"severity": severity, "rule": rule, "path": path, "scope": scope}
        if line is not None:
            item["line"] = line
        if commit is not None:
            item["commit"] = commit
        self.items.append(item)


def scan_text_line(line: str, rel: str, line_number: int | None, findings: Findings,
                   commit: str | None = None, scope: str = "worktree",
                   lock_file: bool = False) -> None:
    exempt_ip = bool(INTERNAL_IP_EXEMPT.search(rel))
    source_code = Path(rel).suffix.lower() in SOURCE_SUFFIXES
    for rule in CONTENT_RULES:
        if lock_file and not rule.strict:
            continue
        if rule.name == "internal-ip" and exempt_ip:
            continue
        # 逐个匹配：同一行前面的占位/文案不能掩盖后面的真实值
        for match in rule.pattern.finditer(line):
            if rule.value_group:
                value = match.group(rule.value_group)
                if is_placeholder(value) or (rule.literal_only and not is_literal_secret(value, source_code)):
                    continue
            findings.add(rule.severity, rule.name, rel, line_number, scope, commit)
            break
    if not lock_file:
        entropy_match = HIGH_ENTROPY_ASSIGNMENT.search(line)
        if entropy_match:
            value = entropy_match.group("value")
            if shannon_entropy(value) >= ENTROPY_THRESHOLD and not is_placeholder(value):
                findings.add("medium", "high-entropy-secret", rel, line_number, scope, commit)


def scan_worktree(root: Path, findings: Findings) -> None:
    paths = git_candidates(root)
    if paths is None:
        paths = tree_candidates(root)

    for path in sorted(set(paths), key=lambda value: str(value).lower()):
        rel = relative_name(path, root)
        lock_file = Path(rel).name.lower() in LOCK_FILE_NAMES

        if path.is_symlink():
            rule = "external-symbolic-link" if is_outside_root(path, root) else "symbolic-link"
            severity = "high" if rule == "external-symbolic-link" else "medium"
            findings.add(severity, rule, rel)
            continue

        if path.is_dir():
            if path.name == ".git" or (path / ".git").exists():
                findings.add("medium", "nested-git-repository", rel)
            continue
        if not path.is_file():
            continue

        for rule, severity, pattern in NAME_RULES:
            if pattern.search(rel):
                findings.add(severity, rule, rel)

        try:
            size = path.stat().st_size
            if size > MAX_TEXT_BYTES:
                findings.add("medium", "large-or-unscanned-file", rel)
                continue
            data = path.read_bytes()
        except OSError:
            findings.add("medium", "unreadable-file", rel)
            continue

        if is_binary(data):
            if has_exif(data):
                findings.add("medium", "image-exif-metadata", rel)
            else:
                findings.add("medium", "binary-file-unscanned", rel)
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            findings.add("medium", "non-utf8-text", rel)
            text = data.decode("utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), 1):
            scan_text_line(line, rel, line_number, findings, lock_file=lock_file)


C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def unquote_c_style(value: str) -> str:
    """还原 git 的 C 风格路径转义（\\ooo 八进制为 UTF-8 字节）。"""
    out = bytearray()
    i = 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value):
            octal = value[i + 1:i + 4]
            if len(octal) == 3 and all(c in "01234567" for c in octal):
                out.append(int(octal, 8))
                i += 4
                continue
            out.append(C_ESCAPES.get(value[i + 1], ord(value[i + 1]) & 0xFF))
            i += 2
            continue
        out.extend(value[i].encode("utf-8"))
        i += 1
    return out.decode("utf-8", errors="replace")


def diff_target_path(header: str) -> str:
    """从 "+++ b/<path>" 取路径；路径含引号/反斜杠/控制字符时 git 仍会加引号转义。"""
    target = header[4:].strip()
    if len(target) >= 2 and target.startswith('"') and target.endswith('"'):
        target = unquote_c_style(target[1:-1])
    return target[2:]


def _scan_diff(lines, findings: Findings, scope: str) -> None:
    rel: str | None = None
    line_number = 0
    commit: str | None = None
    in_hunk = False
    for line in lines:
        if line.startswith("commit "):
            commit = line.split()[1][:10] if len(line.split()) > 1 else None
            rel, in_hunk = None, False
        elif line.startswith("+++ b/") or line.startswith('+++ "b/'):
            rel = diff_target_path(line)
            in_hunk = False
        elif line.startswith("@@ "):
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if match and rel:
                line_number = int(match.group(1))
                in_hunk = True
            else:
                in_hunk = False
        elif in_hunk and rel:
            if line.startswith("+"):
                scan_text_line(line[1:], rel, line_number, findings, commit=commit, scope=scope,
                               lock_file=Path(rel).name.lower() in LOCK_FILE_NAMES)
                line_number += 1
            elif line.startswith("-") or line.startswith("\\"):
                pass
            else:
                line_number += 1


def run_git_bytes(root: Path, args: list[str]) -> "subprocess.Popen[bytes] | None":
    # quotePath=false：中文等非 ASCII 路径原样输出，否则 diff 头会变成 "b/\351..." 而漏扫
    try:
        return subprocess.Popen(
            ["git", "-C", str(root), "-c", "core.quotePath=false", *args],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None


def scan_history(root: Path, findings: Findings, unpushed_only: bool = False,
                 remote: str | None = None) -> bool:
    """流式扫描历史，返回 git 是否成功输出。

    unpushed_only 时只扫本地分支与标签上尚未出现在 remote 的提交；指定 remote 时只与该
    remote 比较——推到新的公开 remote 时，已在私有 remote 上的历史同样会被公开。
    """
    args = ["log", "-p", "--no-color", "--no-ext-diff", "--full-history"]
    if unpushed_only:
        args += ["--branches", "--tags", "--not", f"--remotes={remote}" if remote else "--remotes"]
    else:
        args += ["--all"]
    proc = run_git_bytes(root, args)
    if proc is None:
        findings.add("high", "history-scan-failed", "<history>", scope="history")
        return False
    lines: list[str] = []
    total = 0
    truncated = False
    assert proc.stdout is not None
    try:
        for raw in proc.stdout:
            total += len(raw)
            if total > MAX_HISTORY_BYTES:
                truncated = True
                break
            lines.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        if truncated:
            proc.kill()
        returncode = proc.wait()
    _scan_diff(iter(lines), findings, scope="history")
    if truncated:
        findings.add("medium", "history-scan-truncated", "<history>", scope="history")
    elif returncode != 0:
        # 未能确认历史范围时按阻断处理，不把"没扫到"当成"没有"
        findings.add("high", "history-scan-failed", "<history>", scope="history")
        return False
    return True


def scan_staged(root: Path, findings: Findings) -> None:
    proc = run_git_bytes(root, ["diff", "--cached", "--no-color", "--no-ext-diff", "-U0"])
    if proc is None:
        return
    lines = []
    total = 0
    assert proc.stdout is not None
    for raw in proc.stdout:
        total += len(raw)
        if total > MAX_HISTORY_BYTES:
            findings.add("medium", "staged-scan-truncated", "<staged>", scope="staged")
            break
        lines.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
    proc.stdout.close()
    proc.wait()
    _scan_diff(iter(lines), findings, scope="staged")


def load_baseline(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "entries": []}
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return {"version": 1, "entries": []}
    return data


def apply_baseline(findings: list[dict], baseline: dict) -> tuple[list[dict], list[dict]]:
    entries = [e for e in baseline.get("entries", []) if isinstance(e, dict)]
    remaining: list[dict] = []
    accepted: list[dict] = []
    for item in findings:
        matched = False
        for entry in entries:
            if entry.get("rule") != item["rule"] or entry.get("path") != item["path"]:
                continue
            entry_line = entry.get("line")
            if entry_line is None or entry_line == item.get("line"):
                matched = True
                break
        (accepted if matched else remaining).append(item)
    return remaining, accepted


def scan(root: Path, scan_history_flag: bool = False, staged_flag: bool = False,
         unpushed_flag: bool = False, baseline_path: Path | None = None,
         remote: str | None = None) -> dict:
    findings = Findings()
    scan_worktree(root, findings)
    history_scanned = False
    in_git = git_candidates(root) is not None
    if (scan_history_flag or unpushed_flag) and in_git:
        # 同时指定时以全量为准，范围只放大不缩小
        history_scanned = scan_history(root, findings, unpushed_only=unpushed_flag and not scan_history_flag,
                                       remote=remote)
    if staged_flag and in_git:
        scan_staged(root, findings)

    baseline: dict = {"version": 1, "entries": []}
    if baseline_path is not None and baseline_path.is_file():
        baseline = load_baseline(baseline_path)
    remaining, accepted = apply_baseline(findings.items, baseline)

    severity_order = {"high": 0, "medium": 1, "low": 2}
    remaining.sort(key=lambda i: (severity_order[i["severity"]], i["path"], i.get("line", 0), i["rule"]))
    summary = {
        "high": sum(i["severity"] == "high" for i in remaining),
        "medium": sum(i["severity"] == "medium" for i in remaining),
        "accepted": len(accepted),
    }
    return {
        "findings": remaining,
        "accepted": len(accepted),
        "summary": summary,
        "history_scanned": history_scanned,
        "scanner": f"security_scan/{VERSION}",
    }


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
    parser.add_argument("--scan-history", action="store_true", help="扫描全部 Git 历史（新增行）")
    parser.add_argument("--unpushed", action="store_true", help="只扫描未推送到任何 remote 的本地分支与标签提交")
    parser.add_argument("--remote", default=None,
                        help="配合 --unpushed：只与该 remote 比较（推到新的公开 remote 前使用）")
    parser.add_argument("--staged", action="store_true", help="只扫描 staged diff 的新增行")
    parser.add_argument("--baseline", type=Path, default=None,
                        help="基线文件路径（默认 <root>/.safe-publish-baseline.json）")
    parser.add_argument("--version", action="version", version=f"security_scan {VERSION}")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print("项目根目录不存在。", file=sys.stderr)
        return 2

    baseline = args.baseline if args.baseline is not None else root / ".safe-publish-baseline.json"
    result = scan(root, scan_history_flag=args.scan_history, staged_flag=args.staged,
                  unpushed_flag=args.unpushed, baseline_path=baseline, remote=args.remote)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in result["findings"]:
            location = item["path"]
            if "line" in item:
                location += f":{item['line']}"
            suffix = ""
            if item.get("scope", "worktree") != "worktree":
                suffix = f" [{item['scope']}"
                if "commit" in item:
                    suffix += f"@{item['commit']}"
                suffix += "]"
            print(f"{item['severity'].upper()} {location} {item['rule']}{suffix}")
        if result["accepted"]:
            print(f"基线已接受: {result['accepted']} 项（经人工审核）")
        print(
            f"Summary: high={result['summary']['high']} medium={result['summary']['medium']}"
            f" history_scanned={result['history_scanned']}; 命中值未被打印。"
        )

    if result["summary"]["high"]:
        return 2
    if result["findings"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
