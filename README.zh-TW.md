<!-- 翻譯自 README.md @ docs/readme-template-v2。只翻 "For AI agents" 以上的章節，英文版更新時一起改。 -->

<div align="center">

<h1>NYCU</h1>

<p><strong>把陽明交大入口網站、E3、課表和兼任簽到變成 agent 能用的 MCP 工具。</strong></p>

[![CI](https://img.shields.io/github/actions/workflow/status/zyx1121/nycu/check.yml?branch=main&style=flat-square&label=CI)](https://github.com/zyx1121/nycu/actions)
[![Claude Code](https://img.shields.io/badge/Claude_Code-plugin-D97757?style=flat-square)](https://github.com/zyx1121/marketplace)
[![License](https://img.shields.io/github/license/zyx1121/nycu?style=flat-square)](LICENSE)

[English](README.md) | **繁體中文** | [简体中文](README.zh-CN.md)

</div>

```console
$ timetable_list_semesters
{"data": ["1151", "114X", "1142", "1141", "113X", ...], "metadata": {"count": 83}}
```

陽明交大的學生要在三個網站之間切換：E3 課程、課表和兼任簽到。這個 plugin 給 Codex 和 Claude Code 21 個工具，所有會寫入的工具都要明確確認。

## 功能

- **讀 E3**：課程、作業、期限、成績、繳交紀錄和教材下載(9 個工具)。
- **查公開課表**：課程、上課時間和節次，不用登入(4 個工具)。
- **使用入口網站登入**：透過陽明交大單一登入查身分、系統和活動(5 個工具)。
- **兼任簽到**：狀態、簽到和簽退，有 `confirm` 和 `dry_run`(3 個工具)。
- **依平台註冊**：macOS 有全部 21 個工具，Linux 有 E3 和課表的 13 個。

## 快速開始

```sh
claude plugin marketplace add zyx1121/marketplace
claude plugin install nycu@zyx1121
```

Codex：先 `codex plugin marketplace add zyx1121/marketplace`，再 `codex plugin add nycu@zyx1121`。開新的對話，問它「這週有哪些 E3 作業要交？」。

需要 Bun 1.3.13 以上、uv 和 Python 3.11 以上，Python 可以交給 uv 安裝。MCP server 已經打包好，plugin 目錄不需要 `bun install`。

## 使用方式

| 服務 | 工具 | 需要 |
|------|------|------|
| E3 | `e3p_whoami`、`e3p_list_courses`、`e3p_list_assignments`、`e3p_list_due`、`e3p_get_submission`、`e3p_list_grades`、`e3p_get_content`、`e3p_download_file`、`e3p_logout` | E3 權杖，macOS 或 Linux |
| 課表 | `timetable_list_semesters`、`timetable_search_courses`、`timetable_lookup_courses`、`timetable_get_periods` | 不需要，macOS 或 Linux |
| 入口網站 | `nycu_setup`、`nycu_whoami`、`nycu_list_systems`、`nycu_list_events`、`nycu_logout` | macOS 鑰匙圈和 Playwright Chromium |
| 簽到 | `parttime_get_status`、`parttime_sign_in`、`parttime_sign_out` | 入口網站登入和校內網路 |

- **E3 登入**：在 plugin 目錄執行一次 `uv run scripts/e3p.py login`。密碼用隱藏提示輸入，不會經過對話。
- **入口網站登入**：把學號和密碼存進鑰匙圈項目 `kilo/nycu-portal`，`otpauth://` URI 存進 `kilo/nycu-totp`。再請 agent 執行 `nycu_setup` 準備 Chromium。
- **簽到**：`parttime_sign_in` 和 `parttime_sign_out` 會寫入真實的出勤紀錄，需要 `confirm=true`。先用 `dry_run` 試。

## 設定

| 設定 | 位置 | 預設 |
|------|------|------|
| 入口網站權杖 | `NYCU_PORTAL_CONFIG` | `~/.config/nycu/portal.json` |
| E3 權杖 | `NYCU_E3P_CONFIG` | `~/.config/nycu/e3p.json` |
| E3 覆寫 | `NYCU_E3P_TOKEN`、`NYCU_E3P_USERID`、`NYCU_E3P_BASE`、`NYCU_E3P_SERVICE` | 取自 E3 權杖檔 |
| 入口網站密碼 | 鑰匙圈 `kilo/nycu-portal`，帳號是學號 | 入口網站工具必填 |
| 入口網站 TOTP | 鑰匙圈 `kilo/nycu-totp`，帳號是學號 | 入口網站工具必填 |
| 平台覆寫(僅測試用) | `NYCU_FORCE_PLATFORM` | 實際平台 |

權杖檔權限是 600，會遵循 `XDG_CONFIG_HOME`。舊的 `UTILS_NYCU_CONFIG`、`UTILS_E3P_CONFIG` 和 `UTILS_E3P_*` 仍然有效，但 `NYCU_*` 優先。

## 運作方式

Bun 的 MCP server 啟動時依平台註冊工具，只看平台和 uv，不會登入或連線。每次呼叫都透過 uv 執行一支 Python 腳本，每支腳本都在檔案內宣告自己的套件(PEP 723)。

- 入口網站的快取權杖過期時會重新登入一次，還是失敗就回報錯誤。
- E3 下載只會把權杖送到已設定的 Moodle `pluginfile` HTTPS 網址，會拒絕跨來源的轉址，錯誤訊息也不會包含帶權杖的網址。

## 限制

- 簽到寫入是真的。逾時不代表已經回滾，逾時後請呼叫 `parttime_get_status` 確認。
- 簽到需要校內網路，因為打卡系統只能從校內連線。
- 入口網站和簽到工具需要 macOS，因為要用鑰匙圈。

## 其他

給 AI agent 的結構化資訊與開發說明在[英文版](README.md#for-ai-agents)。

## 授權

[MIT](LICENSE)
