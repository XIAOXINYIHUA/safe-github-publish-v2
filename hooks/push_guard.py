#!/usr/bin/env python3
"""PreToolUse 守衛：攔截 git push / gh repo create / gh release create|upload。

從 stdin 讀取事件 JSON，若命令命中發佈類操作，則對相應倉庫執行
security_scan（工作區 + staged + 未推送提交）。存在 high 項時以退出碼 2
阻斷；輸出只含路徑/規則/行號，絕不含命中值。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCAN_SCRIPTS = PLUGIN_ROOT / "skills" / "safe-github-publish" / "scripts"

PUBLISH_COMMAND = re.compile(
    r"(?im)(?:\bgit\b[^;&|]*\bpush\b)"
    r"|(?:\bgh\s+repo\s+create\b)"
    r"|(?:\bgh\s+release\s+(?:create|upload)\b)"
)
GIT_C = re.compile(r"(?im)\bgit\s+-C\s+(\"[^\"]+\"|\S+)")


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
    command = (event.get("tool_input") or {}).get("command", "")
    if not isinstance(command, str) or not PUBLISH_COMMAND.search(command):
        return 0

    root = Path.cwd()
    match = GIT_C.search(command)
    if match:
        root = Path(match.group(1).strip('"'))
    try:
        check = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=15,
        )
        if check.returncode != 0:
            return 0
    except (OSError, subprocess.SubprocessError):
        return 0

    sys.path.insert(0, str(SCAN_SCRIPTS))
    import security_scan

    result = security_scan.scan(
        root,
        staged_flag=True,
        unpushed_flag=True,
        baseline_path=root / ".safe-publish-baseline.json",
    )

    if result["summary"]["high"] > 0:
        print("safe-github-publish 守衛：檢測到未處置的高風險項，已阻斷發佈類命令。", file=sys.stderr)
        for item in result["findings"]:
            if item["severity"] != "high":
                continue
            location = item["path"] + (f":{item['line']}" if "line" in item else "")
            scope = "" if item.get("scope", "worktree") == "worktree" else f" [{item['scope']}]"
            print(f"HIGH {location} {item['rule']}{scope}", file=sys.stderr)
        print("處置後重試：修復或移除敏感項，誤報經人工審核寫入 .safe-publish-baseline.json。", file=sys.stderr)
        return 2

    if result["findings"]:
        print(
            f"safe-github-publish 守衛：{result['summary']['medium']} 個中風險項請複核（未阻斷）。",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
