#!/bin/sh
# 跨平台選擇 Python 解釋器：Windows 用 py 啟動器，Unix 用 python3，最後回退 python
if command -v py >/dev/null 2>&1; then
  exec py -3 "$(dirname "$0")/push_guard.py"
elif command -v python3 >/dev/null 2>&1; then
  exec python3 "$(dirname "$0")/push_guard.py"
else
  exec python "$(dirname "$0")/push_guard.py"
fi
