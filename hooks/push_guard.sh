#!/bin/sh
# 跨平台选择 Python 解释器：Windows 用 py 启动器，Unix 用 python3，最后回退 python
if command -v py >/dev/null 2>&1; then
  exec py -3 "$(dirname "$0")/push_guard.py"
elif command -v python3 >/dev/null 2>&1; then
  exec python3 "$(dirname "$0")/push_guard.py"
else
  exec python "$(dirname "$0")/push_guard.py"
fi
