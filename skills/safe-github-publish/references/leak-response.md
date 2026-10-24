# 洩露應急手冊

掃描發現疑似或確認洩露（候選集、staged 或 Git 歷史）時讀取。原則：**先止損，再清理，最後總結**。順序不可顛倒——歷史清理不能代替密鑰輪換，因為任何人都可能在清理前完成克隆或快取。

## 第一步：立即止損（在任何清理之前）

1. **不要推送**。已推送則評估是否先設為 private（需用戶確認）。
2. 按洩露值型別引導用戶**輪換/撤銷**：
   - GitHub PAT → github.com/settings/tokens 撤銷
   - AWS AKIA/ASIA → IAM 控制台停用並輪換
   - Google AIza / service account → Google Cloud 憑據頁面輪換
   - OpenAI / Anthropic / HuggingFace / npm / PyPI → 各平台 API keys 頁面輪換
   - 資料庫連線串 → 改密碼
   - 私鑰 → 重新生成並重新部署對應證書/授權金鑰
3. 只報告規則名與位置，不展示值本體；輪換由用戶在對應平台操作。

## 第二步：評估暴露面

- 倉庫當前可見性：public / private。
- 是否已推送：未推送（僅本地歷史）/ 已推送（可能被克隆、Fork、快取）。
- 洩露存在位置：工作區、staged、已提交歷史。
- public 且已推送：假設已被讀取，輪換是唯一可靠補救。

## 第三步：清理（僅在輪換完成後，且用戶確認方案）

**未提交/未推送**：最簡單——從檔案移除值，用 `git add` 覆蓋，必要時 `git commit --amend`（僅未推送時）。

**已進入本地歷史、未推送**：

```bash
git filter-repo --replace-text <(echo "實際值==>REMOVED")   # 概念示意，值寫在臨時檔案中
# 或對整個檔案：git filter-repo --path secrets.env --invert-paths
```

**已推送**：輪換完成後執行歷史清理，然後：

```bash
git push --force-with-lease   # 僅此場景允許，需用戶明確批准
```

- `filter-repo` 不可用時備選：BFG Repo-Cleaner。不建議 `filter-branch`（慢且易錯）。
- 歷史重寫後提醒用戶：通知所有協作者 re-clone；GitHub 上已有的 Fork、快取頁面與已傳播克隆不受影響——這正是第一步必須輪換的原因。
- 若值已被 GitHub Secret Scanning 標記（public 倉庫會自動通知供應商），提醒用戶檢查郵件與 Security advisory。

## 第四步：復盤防復發

- 確認該值已從：工作區、staged、全部本地分支歷史中消失（重跑 `security_scan.py --scan-history` 驗證）。
- 將對應檔案加入 `.gitignore` 或改為環境變數 + `.env.example`。
- **必須**向用戶部署防復發三件套（`assets/` 模板）：gitleaks 配置、pre-commit 鉤子、CI 掃描 workflow——發佈時的一次掃描擋不住後續提交引入的新密鑰。
- 記錄事件：什麼規則、在哪裡發現、如何處置——寫入最終報告的"待辦/已處置"部分，供用戶歸檔。

## 明確不做的事

- 不代替用戶輪換密鑰（需要平台登入，屬用戶操作）。
- 不在未輪換時建議"清理歷史就沒事了"。
- 不未經確認執行任何歷史重寫或強推。
- 不在報告、提交資訊或 issue 中複述洩露值本體。
