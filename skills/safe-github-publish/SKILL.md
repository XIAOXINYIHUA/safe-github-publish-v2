---
name: safe-github-publish
description: 安全自动化发布项目到 GitHub：分阶段门禁式审查密钥/隐私/Git 历史，生成工整的 README、LICENSE 决策、CHANGELOG 与仓库元数据，再创建或推送仓库。Use when a user asks to upload, publish, push, open-source, share, 上传, 发布, 开源, 整理仓库, or prepare any local project for GitHub — including "帮我发到 GitHub", "把这个项目开源", "improve the README", or "make this repo public-ready". Also use before any git push to a public remote.
---

# Safe GitHub Publish v2

## 目标

将项目安全、格式工整地发布到 GitHub：阻止密钥与隐私泄露，同时产出结构规范的 README、CHANGELOG、LICENSE 决策与仓库元数据。整个流程是**阶段门禁式**的——每个阶段有明确的准入与准出条件，上一关未通过不得进入下一关。

## 安全契约（不可违反）

1. 用户说"上传到 GitHub"即视为发布授权，但只执行与该项目直接相关的非破坏性操作。
2. 未指定可见性时默认创建 **private** 仓库；public 必须用户明说。
3. 高风险项未解决前**禁止** add/commit/push。绝不显示密钥原文——报告只含相对路径、行号、规则名。
4. 不自动强推、改写历史、覆盖 remote、删除本地文件、添加许可证或转移所有权；这些操作必须先获得用户对具体方案的确认。
5. 发现真实密钥已进入 Git 历史时立即停止，先引导撤销/轮换密钥（读 [references/leak-response.md](references/leak-response.md)），再谈历史清理。
6. 声明安全边界时不夸大：报告"已检查的范围"，不宣称"完全安全"。

## 工具与资料路由

| 需要 | 用什么 |
|---|---|
| 隐私/密钥扫描（含 Git 历史） | `python3 scripts/security_scan.py <root> [--json] [--scan-history] [--staged] [--baseline <file>]`（Windows 用 `py -3`） |
| 发布格式检查（README/LICENSE/链接/图表） | `python3 scripts/repo_lint.py <root> [--json]`（Windows 用 `py -3`） |
| 人工复核隐私风险时 | 读 [references/privacy-checklist.md](references/privacy-checklist.md) |
| 生成或重写 README 时 | 读 [references/readme-template.md](references/readme-template.md) |
| 提交/标签/CHANGELOG/topics/许可证选择时 | 读 [references/release-format.md](references/release-format.md) |
| 疑似或确认泄露时 | 读 [references/leak-response.md](references/leak-response.md) |
| 防复发三件套（gitleaks 配置 / pre-commit / CI 扫描） | 复制 [assets/](assets/) 下对应模板进用户项目 |

扫描器退出码：`2` = 存在阻断项（high）；`1` = 需人工复核（medium 及以下）；`0` = 候选集未命中。lint 退出码：`2` = 格式错误（error）；`1` = 警告；`0` = 通过。**退出码 2 是硬门禁，不得绕过。**

## 阶段门禁工作流

### Phase 0 · 侦察（准入：用户提出发布意图）

- 确认项目根目录、`git status --short --ignored`、remote、分支、`gh auth status`。不读取、不打印任何认证 token。
- 从目录名推导仓库名；从代码、manifest、现有文档提炼一句准确的仓库描述（不夸大）。
- 保留用户明确指定的仓库名、组织、可见性、分支。

### Phase 1 · 圈定候选集

- 检查 `git ls-files`、untracked、嵌套仓库、符号链接、大文件（GitHub 单文件 >50MB 必须处理，>100MB 拒绝并建议 LFS）。
- 按 [references/privacy-checklist.md](references/privacy-checklist.md) 的"通常应忽略"清单**合并更新** `.gitignore`（不覆盖已有规则）。

### Phase 2 · 安全扫描 ⛔ 门禁一

1. 运行 `security_scan.py <root> --json` 扫描候选集。
2. 已有提交历史时追加 `--scan-history` 扫描全部历史。专业工具已安装（`gitleaks`/`trufflehog` 在 PATH 中）时优先使用并保留本扫描器作为兜底。
3. 逐项复核 high 项：确认是否真实（对照 privacy-checklist），**不得因"可能是测试值"就放行高可信度 token、私钥或凭据格式**。
4. binary / 符号链接 / 嵌套仓库 / unreadable 等扫描器声明的边界项逐项人工复核。
5. 误报经用户确认后可写入基线文件 `.safe-publish-baseline.json`（格式见 privacy-checklist），基线条目必须附 reason 与日期，**只允许人工审核后添加，不得为通过门禁而自动填充**。
6. 准出条件：无未处理的 high，medium 全部处置（修复 / 基线 / 明确接受并在报告中列出）。

### Phase 3 · 修复与脱敏

- 含本地密钥的配置改为环境变量或安全占位符；仅在有助于使用时创建不含真实值的 `.env.example`。
- 清理 README、示例、日志、截图文件名、配置中的用户名、邮箱、绝对路径、内网地址与客户数据。
- 已 tracked 的敏感文件：修正内容后从索引安全移除；本地原文件不删除。
- 保留运行项目必需的源代码、manifest 与锁文件——不为"精简"牺牲可复现性。
- 对可能敏感但未确定的文件：默认不上传，在结果中列出。

### Phase 4 · 发布格式 ⛔ 门禁二

1. 按 [references/readme-template.md](references/readme-template.md) 修正或生成 README：先读入口文件、manifest、CLI help、测试，从实际行为生成，不凭目录名猜测。
2. LICENSE：检查是否已有；缺失时按 [references/release-format.md](references/release-format.md) 的许可证对照表给出建议，**由用户选择后**再添加。
3. CHANGELOG：存在有意义版本时按 Keep a Changelog 精简格式创建或更新。
4. 准备仓库元数据：一句描述（≤120 字符）、3–8 个 kebab-case topics、默认分支名。
5. 运行 `repo_lint.py <root> --json`，修复全部 error；warning 逐条评估。
6. 准出条件：lint 无 error，README 快速开始路径经核实可复制执行。

### Phase 5 · 暂存与提交 ⛔ 门禁三

1. 再次运行 `security_scan.py <root>`（含 `--scan-history` 若适用），确认退出码非 2。
2. 用 `git add -- <已审查路径>` 显式添加；完成审查前禁止 `git add .` / `git add -A`。
3. 检查 `git diff --check`、`git diff --cached --stat` 与 staged diff；再对 staged 运行 `security_scan.py <root> --staged`。
4. 提交信息按 release-format 的格式规范，简短、事实性。
5. 不提交扫描报告、临时修复文件或含本机路径的输出。

### Phase 6 · 创建或推送仓库 ⛔ 门禁四（public 专项确认）

- 优先用已登录的 `gh` CLI。新仓库默认 `--private`；用户明确要求 public 时，**推送前用一句话清单向用户做最终确认**（可见性、仓库名、描述、public 后不可视为私密的信息）。
- `origin` 已存在时先核对 host/owner/repo，不匹配则询问，不覆盖。
- 推送当前分支；不用 `--force` / `--force-with-lease`，除非用户批准了明确的历史修复方案。
- 推送后用 `gh repo edit --description --add-topic` 等设置元数据；需要发版时按 release-format 打 tag 并 `gh release create`。
- 网络/认证/命名冲突/权限失败：保留本地修改，简洁报告阻塞原因。

### Phase 7 · 发布后验证

- 核对远程 URL、可见性、默认分支、推送结果、description 与 topics 生效。
- 确认工作区无意外 staged 文件；对 public 仓库浏览远程文件列表复检敏感项。
- **防复发（默认部署）**：发布完成后直接把 `assets/` 模板装进用户项目——gitleaks CI workflow（`.github/workflows/gitleaks.yml`）与 `.gitleaks.toml` 默认部署；pre-commit 钩子询问用户是否启用；发生过泄露的项目三件套全配。部署后在报告中说明，不静默添加。
- 报告已检查范围与未覆盖风险（历史、二进制、外部系统），不宣称"完全安全"。

## 输出格式

最终回复保持简短，只报告：

1. 仓库：名称、可见性、URL、description、topics
2. 发布产物：README/CHANGELOG/LICENSE/.gitignore 等新增或修改项
3. 安全检查：扫描结论（候选集 + 历史范围）、阻断项及处置、基线条目数
4. 提交与推送：commit 摘要、tag/release（如有）
5. 待办：必须由用户处理的事项（如密钥轮换、许可证确认）

不粘贴冗长命令输出、完整 diff 或任何疑似敏感值。
