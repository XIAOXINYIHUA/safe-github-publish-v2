# 发布格式规范

Phase 4/6 涉及提交、标签、CHANGELOG、许可证与仓库元数据时读取。目标：每个产物都有稳定、可预期的形状，不发明新格式。

## 提交信息

用 Conventional Commits 精简子集，一行不超过 72 字符：

```
<type>: <what changed>

types: feat | fix | docs | chore | refactor | test | build | ci
```

- 发布准备类提交用 `chore: prepare project for github` 或 `docs: rewrite readme for initial release`。
- 正文可选，只写"为什么"，不写命令输出、不写本机路径。
- 不在提交信息中出现密钥、账户名或内部代号。

## 语义化版本与标签

- 标签格式 `vMAJOR.MINOR.PATCH`（`v1.0.0`），不带前导空格或注释。
- 首次对外发布默认 `v1.0.0`；明确是早期预览可用 `v0.x.y` 并在 README 标注稳定性。
- 打标签前确认 CHANGELOG 已包含对应版本段落。

## CHANGELOG（Keep a Changelog 精简格式）

```markdown
# Changelog

本项目所有重要变更记录在此。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-10-24

### Added
- 首个公开版本：核心扫描、历史扫描与基线机制。

[1.0.0]: https://github.com/<owner>/<repo>/releases/tag/v1.0.0
```

- 只记 Added / Changed / Fixed / Removed / Security，不记流水账。
- 每个版本链接到对应 release tag。
- 无有意义版本时不强行创建（`repo_lint.py` 只提示 info）。

## GitHub Release

`gh release create <tag> --title "<tag> 主题" --notes-file <file>`，正文结构：

1. **一段话**：这个版本最重要的变化。
2. **Changes**：按 Added/Changed/Fixed 分组的要点列表，与 CHANGELOG 同源。
3. **Upgrade**：从上一版本升级需要的动作（无则省略）。

不自动生成 AI 风格的夸耀式标题；不把完整 diff 粘进正文。

## 仓库元数据

```bash
gh repo edit <owner>/<repo> --description "<一句话>" --add-topic <topic> ...
```

- **description**：一句话，≤120 字符，说明项目是什么/解决什么；不含本地路径、内部代号。
- **topics**：3–8 个 kebab-case 主题词，覆盖语言（`python`）、领域（`security`、`cli`）和场景（`github-actions`）；不超过 GitHub 上限 20 个。
- **homepage**：有真实文档站或在线 Demo 时才设置。
- **可见性**：默认 private；public 需用户明确要求并在推送前做最终确认。

## 许可证对照（由用户选择，不代做决定）

| 许可证 | 适合 | 要点 |
|---|---|---|
| MIT | 通用默认 | 极简宽松，保留版权声明即可 |
| Apache-2.0 | 含专利考虑的项目 | 宽松 + 明确专利授权 + NOTICE |
| BSD-3-Clause | 通用宽松 | 三条款，防背书 |
| GPL-3.0 | 要求衍生同许可 | 强 copyleft |
| AGPL-3.0 | 防止网络服务闭源 | 最强 copyleft |
| Unlicense / CC0 | 无条件放弃权利 | 极少场景 |

- 用户选定后取**官方原文**放入 `LICENSE`（例如 `gh api` 或可靠来源），不手写、不改写条款。
- README 的 License 章节一句话说明所选许可证并链接文件。
- 拿不准或多许可证（如代码 MIT + 文档 CC-BY）时列出建议让用户确认。

## .gitignore

- 按 `.gitignore` 官方模板或 `gitignore.io` 对应技术栈合并，不覆盖已有规则。
- 至少排除：依赖目录、构建产物、IDE 状态、`.env*`（保留 `!.env.example`）、本地数据库与日志。

## 分支与命名

- 默认分支遵循平台惯例（`main`），不擅自重命名已有默认分支。
- 分支名 kebab-case：`feat/xxx`、`fix/xxx`、`docs/xxx`。
