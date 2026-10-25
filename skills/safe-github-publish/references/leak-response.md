# 泄露应急手册

扫描发现疑似或确认泄露（候选集、staged 或 Git 历史）时读取。原则：**先止损，再清理，最后总结**。顺序不可颠倒——历史清理不能代替密钥轮换，因为任何人都可能在清理前完成克隆或缓存。

## 第一步：立即止损（在任何清理之前）

1. **不要推送**。已推送则评估是否先设为 private（需用户确认）。
2. 按泄露值类型引导用户**轮换/撤销**：
   - GitHub PAT → github.com/settings/tokens 撤销
   - AWS AKIA/ASIA → IAM 控制台停用并轮换
   - Google AIza / service account → Google Cloud 凭据页面轮换
   - OpenAI / Anthropic / HuggingFace / npm / PyPI → 各平台 API keys 页面轮换
   - 数据库连接串 → 改密码
   - 私钥 → 重新生成并重新部署对应证书/授权密钥
3. 只报告规则名与位置，不展示值本体；轮换由用户在对应平台操作。

## 第二步：评估暴露面

- 仓库当前可见性：public / private。
- 是否已推送：未推送（仅本地历史）/ 已推送（可能被克隆、Fork、缓存）。
- 泄露存在位置：工作区、staged、已提交历史。
- public 且已推送：假设已被读取，轮换是唯一可靠补救。

## 第三步：清理（仅在轮换完成后，且用户确认方案）

**未提交/未推送**：最简单——从文件移除值，用 `git add` 覆盖，必要时 `git commit --amend`（仅未推送时）。

**已进入本地历史、未推送**：

```bash
git filter-repo --replace-text <(echo "实际值==>REMOVED")   # 概念示意，值写在临时文件中
# 或对整个文件：git filter-repo --path secrets.env --invert-paths
```

**已推送**：轮换完成后执行历史清理，然后：

```bash
git push --force-with-lease   # 仅此场景允许，需用户明确批准
```

- `filter-repo` 不可用时备选：BFG Repo-Cleaner。不建议 `filter-branch`（慢且易错）。
- 历史重写后提醒用户：通知所有协作者重新克隆；GitHub 上已有的 Fork、缓存页面与已传播克隆不受影响——这正是第一步必须轮换的原因。
- 强推后旧提交在 GitHub 上仍可通过 SHA 直接访问，引用它的 PR 也会保留；要彻底移除需用户联系 GitHub Support，并提供受影响的仓库与提交 SHA。
- 若值已被 GitHub Secret Scanning 标记（public 仓库会自动通知供应商），提醒用户检查邮件与 Security advisory。

## 第四步：复盘防复发

- 确认该值已从：工作区、staged、全部本地分支历史中消失（重跑 `security_scan.py --scan-history` 验证）。
- 将对应文件加入 `.gitignore` 或改为环境变量 + `.env.example`。
- **必须**向用户部署防复发三件套（`assets/` 模板）：gitleaks 配置、pre-commit 钩子、CI 扫描 workflow——发布时的一次扫描挡不住后续提交引入的新密钥。
- 记录事件：什么规则、在哪里发现、如何处置——写入最终报告的"待办/已处置"部分，供用户归档。

## 明确不做的事

- 不代替用户轮换密钥（需要平台登录，属用户操作）。
- 不在未轮换时建议"清理历史就没事了"。
- 不未经确认执行任何历史重写或强推。
- 不在报告、提交信息或 issue 中复述泄露值本体。
