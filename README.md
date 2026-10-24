# Safe GitHub Publish

安全自动化发布项目到 GitHub 的 ZCode plugin：**一个 skill + 一道主动防线**。

- **skill**（[skills/safe-github-publish/](skills/safe-github-publish/)）：阶段门禁式发布工作流——安全扫描（工作区 / Git 历史 / staged / 未推送提交）、误报基线、README 与发布格式规范、洩露应急手册
- **push 守衛**（[hooks/](hooks/)）：PreToolUse hook，任何 `git push` / `gh repo create` / `gh release create|upload` 执行前自动扫描未推送提交，存在未处置高风险项时阻断——不经过 skill 直接让 agent 推送也会被拦

## 安装

**方式一：作为 plugin 安装（推荐，含守衛）**

1. Plugin Marketplace → Add → Add Plugin Marketplace，粘贴本地 marketplace 目录（或把本仓库配置为 marketplace 源）
2. 安装 `safe-github-publish`

**方式二：仅安装 skill**

把 `skills/safe-github-publish/` 复制到 `~/.agents/skills/`（或项目内 `.zcode/skills/`）。

## 使用

对 agent 说「帮我把这个项目发布到 GitHub」即可触发。工具脚本可独立运行：

```console
$ python3 skills/safe-github-publish/scripts/security_scan.py . --scan-history
$ python3 skills/safe-github-publish/scripts/repo_lint.py .
```

（Windows 用 `py -3`。）

## Development

```bash
python -m unittest discover -s skills/safe-github-publish/tests -v   # 25 个测试
```

守衛手动验证：

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"git push"}}' | bash hooks/push_guard.sh
```

详细设计、安全边界与变更记录见 [skills/safe-github-publish/README.md](skills/safe-github-publish/README.md) 与 [CHANGELOG.md](CHANGELOG.md)。

## License

[MIT](LICENSE)
