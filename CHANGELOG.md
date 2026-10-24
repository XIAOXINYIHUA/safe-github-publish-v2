# Changelog

本项目所有重要变更记录在此。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [2.0.0] - 2026-10-24

全面升级：框架借鉴高星 skill 项目（anthropics/skills 的渐进式披露、obra/superpowers 的阶段门禁），安全扫描对齐社区分层防御实践。

### Added

- 阶段门禁工作流：8 阶段 4 硬门禁，替代 v1 的线性步骤列表
- `security_scan.py --scan-history`：扫描全部 Git 历史新增行（含已删除文件），命中附 commit 摘要；超 200MB 截断并如实提示
- `security_scan.py --staged`：提交前对 staged diff 的最后一道复扫
- `security_scan.py --unpushed`：只扫描本地分支上未出现在任何 remote 的提交（push 守衛的精确范围，首次推送等效全历史）
- plugin 形态与 PreToolUse push 守衛：拦截 `git push` / `gh repo create` / `gh release create|upload`，存在未处置 high 时以退出码 2 阻断，输出不含命中值
- 误报基线机制：`.safe-publish-baseline.json` 记录人工审核豁免项（rule/path/line/reason/date）
- `repo_lint.py`：发布格式门禁——README 结构与快速开始章节、唯一一级标题、相对链接可达与大小写匹配（GitHub 区分大小写）、Mermaid 图表类型校验、空章节、badge 上限、LICENSE/.gitignore/CHANGELOG 检查
- 防复发三件套 `assets/`：gitleaks 配置、pre-commit 钩子、CI 密钥扫描 workflow 模板；仓库自身 CI 见 `.github/workflows/tests.yml`
- 新增密钥规则：Anthropic、Telegram bot、SendGrid、熵值检测（Shannon ≥ 4.0）、`app_secret`/`secret`/`db_password` 等赋值语境扩展；`sk-` 通用规则收紧为"同时含数字与大写字母且 ≥24 字符"，避免普通标识符误报阻断
- JPEG/PNG EXIF 元数据存在性检测；`.DS_Store`/`Thumbs.db` 等系统残留与 `.tfvars` 规则
- 锁文件降噪：package-lock 等 15 类锁文件只保留前缀锚定的高可信规则，不再把完整性哈希当凭据
- `references/release-format.md`：Conventional Commits、语义化标签、Keep a Changelog、Release notes、仓库元数据（description/topics）与许可证对照表
- `references/leak-response.md`：洩露应急手册——先轮换、再评估暴露面、经确认才清理历史
- 测试从 8 个扩展到 25 个，覆盖历史/staged/unpushed 扫描、基线、熵值、EXIF、锁文件降噪与全部格式检查

### Changed

- `privacy_scan.py` 更名为 `security_scan.py`；输出增加 `scope`（worktree/history/staged）字段
- `.gitignore` 建议清单合并进 privacy-checklist，按技术栈裁剪而非机械全加

### Security

- 扫描器输出持续保证不含命中值与扫描根目录绝对路径，测试明确断言

## [1.0.0]

首个版本：SKILL.md 工作流、privacy_scan.py（候选集扫描、不泄值输出）、隐私清单与 README 模板、8 个单元测试。（发布日期未记录）
