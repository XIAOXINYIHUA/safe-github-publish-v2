# GitHub 发布隐私检查表

只在人工复核扫描结果或准备处置敏感项时读取。报告风险类别和位置，不复制敏感值。

## 阻断上传（high）

- API key、访问 token、OAuth secret、密码和数据库连接凭据（含 `key = value`、`Authorization: Bearer`、连接串内嵌凭据）
- 高熵随机串出现在 `key/token/secret/password` 赋值语境中（熵值 ≥ 4.5 且非占位符）
- SSH、PGP、TLS 私钥或签名密钥（任何 `-----BEGIN ... PRIVATE KEY-----` 变体）
- 云服务凭据：AWS AKIA/ASIA、Google AIza、Azure `AccountKey=`、service account 文件、本地 credential store
- 模型/平台 token：GitHub PAT、GitLab、Anthropic `sk-ant-`、OpenAI `sk-`、HuggingFace、npm、PyPI、Slack、Telegram bot、SendGrid
- 真实的 `.env`、`.env.local`、`.env.production`、生产配置、备份、数据库、数据导出和客户数据
- 已进入 Git 历史但尚未撤销或轮换的真实密钥
- 指向工作区之外的符号链接

## 必须复核（medium）

- 姓名、邮箱、手机号、地址、身份证件或账户标识
- Windows / macOS / Linux 用户目录绝对路径
- 内网域名、私有 IP（docker-compose 等编排示例除外）、主机名、VPN、内部仓库或工单地址
- 公司、客户、员工、聊天记录、日志、测试数据和截图
- JPEG/PNG 图片的 EXIF 元数据（可能含 GPS、设备、姓名）——发布前剥离
- `.tfvars`、`.npmrc`、`.pypirc` 等可能含凭据的配置文件
- `.DS_Store`、`Thumbs.db` 等操作系统残留
- 调试转储、堆栈跟踪、遥测数据
- 许可证、第三方代码和不确定是否允许公开的素材
- 符号链接、submodule 和嵌套 Git 仓库指向的外部内容
- 扫描器无法读取的二进制、大文件（>2MB）、压缩包和非 UTF-8 内容

## 通常应忽略

按项目技术栈合并 `.gitignore` 规则，不要机械添加所有条目：依赖目录与虚拟环境、缓存与 coverage、IDE 与编辑器状态、构建输出与安装包、本地数据库与模型权重、私人笔记与草稿。

## 误报基线机制

`security_scan.py --baseline`（默认读 `<root>/.safe-publish-baseline.json`）：

```json
{
  "version": 1,
  "entries": [
    {"rule": "email-address", "path": "docs/contact.md", "line": 3, "reason": "项目公开联系方式", "date": "2026-10-24"}
  ]
}
```

- `line` 为 `null` 时接受该文件中此规则的所有命中。
- 被接受的条目不计入退出码，但会在输出中报告数量。
- **只允许在用户明确复核后添加条目**；不得为了让门禁通过而自动填充。每条必须写 reason 与 date。
- 密钥类 high 规则原则上不允许进基线——正确处置是轮换，不是接受。

## Git 历史处置

- `--scan-history` 扫描 `git log -p --all` 的新增行；输出超 200MB 会截断并提示 `history-scan-truncated`。
- 历史 binary diff 无法扫描，扫描器不会声称覆盖它们。
- 历史中的真实密钥：**先轮换，再清理历史**。流程见 [leak-response.md](leak-response.md)。
- `git filter-repo` / 强推属于历史重写，必须用户确认具体方案后才执行。

## 安全替代

- 环境变量替代硬编码凭据；`.env.example` 只存变量名和无效占位符。
- 匿名最小化示例数据替代真实数据；相对路径替代本机绝对路径。
- 私人配置加入 `.gitignore`，保留本地副本不删除。
- 图片发布前剥离 EXIF（如 `magick convert in.jpg -strip out.jpg` 或等效工具）。

## 防复发三件套

发布完成后默认部署持续防线（复制 `assets/` 模板进用户项目；pre-commit 需询问，其余默认）：

1. `.gitleaks.toml` —— 扩展 gitleaks 内置规则并接入基线豁免
2. `.pre-commit-config.yaml` —— 提交前本地自动扫描
3. `.github/workflows/gitleaks.yml` —— CI 全历史扫描

## 扫描器边界（如实告知用户）

- 覆盖：tracked + 未忽略的 untracked 文件（非 Git 目录按文件树）、Git 历史新增行（可选）、staged diff（可选）、JPEG/PNG EXIF 存在性。
- 不覆盖：二进制文件内部、压缩包内部、Git LFS 对象、远程系统、历史 binary blob、被截断的历史。
- 规则命中是发布决策的输入，不等于已确认泄露；high 项必须人工确认后处置。

## 描述标准

- 仓库描述：一句话说明项目是什么或解决什么问题。
- README 只写经代码或测试验证的功能；不写"最先进""企业级""完全安全"等无法验证的宣传语。
- 不披露账户名、本地路径、内部代号、客户名称或部署细节。
