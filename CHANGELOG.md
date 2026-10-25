# Changelog

本项目所有重要变更记录在此。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [2.1.0] - 2026-10-25

### Added

- Claude Code 支持：`.claude-plugin/plugin.json` 与 `marketplace.json`，可用 `/plugin marketplace add` 直接安装（ZCode 仍优先读取 `.zcode-plugin/`）
- push 守卫拦截转公开：`gh repo edit --visibility public` 与 `gh api` 改可见性，按全部历史扫描；新增 `gh pr create`
- `security_scan.py --remote <name>`：配合 `--unpushed` 只与指定 remote 比较；未推送范围纳入标签
- `repo_lint.py` 检查引用式链接（`[x]: path`）与 HTML `href`/`src`；链接指向被 `.gitignore` 忽略的文件时报错
- `tests/test_push_guard.py`：命令解析、目录跟踪、新 remote / 转公开、基线变更与 fail-closed
- CI 增加 macOS 与 ruff 检查（`ruff.toml` 固定默认规则集）；Dependabot 跟进 GitHub Actions 版本
- 发布后默认部署 gitleaks CI 与 `.gitleaks.toml`，pre-commit 钩子询问后启用

### Changed

- 守卫按命令结构识别发布操作：按 `&&` `;` `|` 拆段（引号内不拆），跟踪 `cd` / `pushd` / `Set-Location` 与 `git -C`，使用事件中的 `cwd`，并扫描仓库根目录而非当前子目录；`git commit -m "...push..."`、`git stash push` 不再触发
- 守卫按目标 remote 计算未推送范围：推到 URL 或从未同步过的 remote（如新建的公开 remote）时扫描全部历史
- 守卫 fail-closed：扫描异常以退出码 2 阻断；`.safe-publish-baseline.json` 在待发布改动中被修改时请求用户确认
- `hooks/hooks.json` 改为 ZCode 与 Claude Code 通用的 `command` 形式，matcher 覆盖 `Bash|PowerShell`
- 历史扫描在 git 失败时报告 high 级 `history-scan-failed`，`history_scanned` 如实反映；`--scan-history` 与 `--unpushed` 同时给出时按全量扫描
- 模板：gitleaks / checkout action 固定到 commit SHA，说明 organization 需 `GITLEAKS_LICENSE`、gitleaks 不读取本项目基线；pre-commit 钩子版本更新
- 文档与输出统一为简体中文；`leak-response.md` 补充强推后旧提交仍可经 SHA 访问、需联系 GitHub Support 清理

### Fixed

- 历史 / staged 扫描漏掉非 ASCII 文件名（如 `配置.py`）：git 默认把路径转义为 `"b/\351..."`，diff 解析认不出文件头；现在以 `core.quotePath=false` 调用 git，并解码仍带引号的路径
- `credential-assignment` 漏报：支持带前缀的变量名（`OPENAI_API_KEY`、`MYSQL_ROOT_PASSWORD`、`AWS_SECRET_ACCESS_KEY`）、JSON / dict 引号键与 `:=` / `=>` 赋值；同一行逐个匹配，前面的占位值不再掩盖后面的真实值
- 高风险误报：代码表达式（`os.getenv(...)`、`process.env.X`、`Optional[str]`）、源代码中未加引号的变量引用、界面文案（`"password": "Enter your password"`）、变量占位（`$VAR`、`%VAR%`、URL 中的 `${VAR}`）、省略示例（`sk-proj-...`）与不足 8 位的拼接片段（`SECRET = "github_" + ...`）不再按凭据阻断
- 守卫扫描的是 hook 进程的工作目录而非命令所在仓库，`cd other && git push` 或 hook 进程目录不同时会漏拦
- `repo_lint.py`：百分号编码的中文文件名链接被误报为不存在；只检查子目录时指向上级目录的链接被误报
- 只含子章节的容器标题不再被判为空章节
- 英文 locale 的 Windows（如 GitHub Actions windows-latest）管道编码为 cp1252，脚本输出中文触发 `UnicodeEncodeError`：security_scan / repo_lint / push_guard 三个入口统一把 stdout/stderr 重配置为 UTF-8，测试 subprocess 解码显式 UTF-8，CI 增加 `PYTHONUTF8=1`

## [2.0.0] - 2026-10-24

全面升级：框架借鉴高星 skill 项目（anthropics/skills 的渐进式披露、obra/superpowers 的阶段门禁），安全扫描对齐社区分层防御实践。

### Added

- 阶段门禁工作流：8 阶段 4 硬门禁，替代 v1 的线性步骤列表
- `security_scan.py --scan-history`：扫描全部 Git 历史新增行（含已删除文件），命中附 commit 摘要；超 200MB 截断并如实提示
- `security_scan.py --staged`：提交前对 staged diff 的最后一道复扫
- `security_scan.py --unpushed`：只扫描本地分支上未出现在任何 remote 的提交（push 守卫的精确范围，首次推送等效全历史）
- plugin 形态与 PreToolUse push 守卫：拦截 `git push` / `gh repo create` / `gh release create|upload`，存在未处置 high 时以退出码 2 阻断，输出不含命中值
- 误报基线机制：`.safe-publish-baseline.json` 记录人工审核豁免项（rule/path/line/reason/date）
- `repo_lint.py`：发布格式门禁——README 结构与快速开始章节、唯一一级标题、相对链接可达与大小写匹配（GitHub 区分大小写）、Mermaid 图表类型校验、空章节、badge 上限、LICENSE/.gitignore/CHANGELOG 检查
- 防复发三件套 `assets/`：gitleaks 配置、pre-commit 钩子、CI 密钥扫描 workflow 模板；仓库自身 CI 见 `.github/workflows/tests.yml`
- 新增密钥规则：Anthropic、Telegram bot、SendGrid、熵值检测（Shannon ≥ 4.0）、`app_secret`/`secret`/`db_password` 等赋值语境扩展；`sk-` 通用规则收紧为"同时含数字与大写字母且 ≥24 字符"，避免普通标识符误报阻断
- JPEG/PNG EXIF 元数据存在性检测；`.DS_Store`/`Thumbs.db` 等系统残留与 `.tfvars` 规则
- 锁文件降噪：package-lock 等 15 类锁文件只保留前缀锚定的高可信规则，不再把完整性哈希当凭据
- `references/release-format.md`：Conventional Commits、语义化标签、Keep a Changelog、Release notes、仓库元数据（description/topics）与许可证对照表
- `references/leak-response.md`：泄露应急手册——先轮换、再评估暴露面、经确认才清理历史
- 测试从 8 个扩展到 25 个，覆盖历史/staged/unpushed 扫描、基线、熵值、EXIF、锁文件降噪与全部格式检查

### Changed

- `privacy_scan.py` 更名为 `security_scan.py`；输出增加 `scope`（worktree/history/staged/unpushed）字段
- `.gitignore` 建议清单合并进 privacy-checklist，按技术栈裁剪而非机械全加

### Security

- 扫描器输出持续保证不含命中值与扫描根目录绝对路径，测试明确断言

## [1.0.0]

首个版本：SKILL.md 工作流、privacy_scan.py（候选集扫描、不泄值输出）、隐私清单与 README 模板、8 个单元测试。（发布日期未记录）

[Unreleased]: https://github.com/XIAOXINYIHUA/safe-github-publish-v2/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/XIAOXINYIHUA/safe-github-publish-v2/releases/tag/v2.0.0
