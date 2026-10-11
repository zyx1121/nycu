# NYCU

供 Codex 與 Claude Code 使用的 NYCU MCP plugin。從
[zyx1121/plugin](https://github.com/zyx1121/plugin) 拆出原有 21 個工具，
涵蓋校務入口、E3、公開課表與工讀出勤。MCP 是操作入口，scripts 是實作；
不另外維護重複的 skill 工具手冊。

## 安裝

請 agent 從 [zyx1121/marketplace](https://github.com/zyx1121/marketplace)
安裝 `nycu@zyx1121`。也可使用 host 的安裝指令：

```sh
# Claude Code
claude plugin marketplace add zyx1121/marketplace
claude plugin install nycu@zyx1121

# Codex
codex plugin marketplace add zyx1121/marketplace
codex plugin add nycu@zyx1121
```

需要 Bun 1.3.13+、uv、Python 3.11+（uv 可管理）。MCP 已打包，安裝後不需要
在 plugin 目錄執行 bun install。Python 套件由各 script 的 PEP 723 宣告解析。

## 能力與平台

| 服務 | 工具數 | 條件 |
|---|---:|---|
| E3 課程、作業、期限、成績、教材下載 | 9 | E3 token；macOS / Linux |
| 公開課表、課程時間、節次 | 4 | 不需登入；macOS / Linux |
| 校務入口身分、系統、活動、登入準備 | 5 | macOS Keychain、Playwright Chromium |
| 工讀出勤狀態、簽到、簽退 | 3 | 同一份校務 SSO，且網路須可存取校內 timeclock |

macOS 可註冊全部 21 個工具；Linux 註冊 E3 與課表的 13 個工具。
啟動只檢查平台與 uv，不嘗試登入或連線。缺少條件的工具列於 stderr 診斷。
`NYCU_FORCE_PLATFORM` 是測試用的平台覆寫，不會讓 Linux 取得 Keychain 能力。

例如：「列出近期 E3 作業」、「這門課幾點在哪間教室」、「查看今天工讀狀態」。
`parttime_sign_in` / `parttime_sign_out` 會寫入真實出勤紀錄，沿用明確的
`confirm=true` 與 `dry_run` 參數。兩個 logout 工具同樣保留確認欄位。

## 登入與私有設定

三種資料來源各自獨立，不強迫課表或 E3 透過校務入口登入：

- 校務 token：`~/.config/nycu/portal.json`。
- E3 token：`~/.config/nycu/e3p.json`。
- 校務帳密與 TOTP：Keychain 的 `kilo/nycu-portal`、`kilo/nycu-totp` service，
  account 都是學號，TOTP 存 `otpauth://` URI。

Token 檔案權限為 0600，支援 `XDG_CONFIG_HOME`。明確路徑可由
`NYCU_PORTAL_CONFIG` / `NYCU_E3P_CONFIG` 指定；舊的 `UTILS_NYCU_CONFIG` /
`UTILS_E3P_CONFIG` 仍有效，新名稱優先。
E3 也接受 `NYCU_E3P_TOKEN`、`NYCU_E3P_USERID`、`NYCU_E3P_BASE`、
`NYCU_E3P_SERVICE`，優先於相對應的 `UTILS_E3P_*`。

已有設定的使用者執行下方遷移即可。全新設定時，請 agent 先確認缺少的是
哪一項；校務 Chromium 用 `nycu_setup` 準備，帳密仍透過本機 Keychain 安全輸入。
E3 首次取 token 保留內部 script 的互動式 `uv run scripts/e3p.py login`，
密碼以隱藏提示輸入，不包成讓密碼經過對話的 MCP tool。

E3 下載僅把 token 傳給已設定 Moodle 的 HTTPS pluginfile URL，跨來源重新導向
會拒絕；下載錯誤不包含 token URL。這是本次抽出時修正的既有憑證外洩問題。

## 從 zyx 遷移

1. 安裝本 plugin，請 agent 在安裝目錄執行 `python3 scripts/migrate_config.py`。
2. 遷移器把預設 `~/.config/utils/nycu.json`、`e3p.json` 移到新位置，保留
   `~/.config/nycu/migration-backups/` 下的 0600 備份。既有新設定不覆寫；
   明確指定 config 環境變數的路徑保持原樣。輸出只有遷移狀態，不含 token。
3. 以唯讀工具驗證後，更新 zyx 到 0.26.0，並重啟 host。

所有 21 個短工具名稱、參數和輸出 schema 保持原樣。完整名稱從
`plugin_zyx_utils` 移到 `plugin_nycu_nycu`（以 host 顯示為準）；引用完整名稱
的權限或 hooks 需同步更新。不要另註冊同一個 NYCU MCP server。

新程式不會偷偷退回舊預設 token 路徑，因此登出後不會重新讀入舊 token。
備份也不會自動載入。Plugin 更新與解除安裝不刪除私有登入設定。
校務快取 JWT 過期，或 API／relay 回報 token timeout 時，會重新登入一次；
第二次仍失敗就回報錯誤，不會無限重試。

## 開發與驗證

```sh
bun install --frozen-lockfile
bun run check
```

Root `plugin.json` / `mcp.json` 是 manifest 來源；build 產生 Claude 相容檔與
`dist/server.js`，CI 檢查生成檔一致。測試涵蓋平台註冊、confirmation、MCP
錯誤 contract、無 node_modules 的 bundle、設定遷移、E3 下載 token 保護，
portal token 更新，以及使用合成資料的出勤解析／按鈕選擇回歸。CI 不需要校務帳密、不呼叫真實出勤。

沿用既有服務 timeout；逾時不代表寫入已回滾，出勤操作逾時後先查狀態。
原始 scripts、schemas 與 helper 來自
[zyx1121/plugin@9f3e6aa](https://github.com/zyx1121/plugin/tree/9f3e6aa)，保留 MIT。
此套件沒有對原 repo 或其他 plugin 的 runtime 依賴。
