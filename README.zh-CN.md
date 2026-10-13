<!-- 翻译自 README.md @ docs/readme-template-v2。只翻译 "For AI agents" 之前的章节，英文版更新时一起改。 -->

<div align="center">

<h1>NYCU</h1>

<p><strong>把阳明交大门户网站、E3、课表和兼任签到变成 agent 能用的 MCP 工具。</strong></p>

[![CI](https://img.shields.io/github/actions/workflow/status/zyx1121/nycu/check.yml?branch=main&style=flat-square&label=CI)](https://github.com/zyx1121/nycu/actions)
[![Claude Code](https://img.shields.io/badge/Claude_Code-plugin-D97757?style=flat-square)](https://github.com/zyx1121/marketplace)
[![License](https://img.shields.io/github/license/zyx1121/nycu?style=flat-square)](LICENSE)

[English](README.md) | [繁體中文](README.zh-TW.md) | **简体中文**

</div>

```console
$ timetable_list_semesters
{"data": ["1151", "114X", "1142", "1141", "113X", ...], "metadata": {"count": 83}}
```

阳明交大的学生要在三个网站之间切换：E3 课程、课表和兼任签到。这个插件给 Codex 和 Claude Code 26 个工具，所有会写入的工具都要明确确认。

## 功能

- **读取 E3**：课程、作业、截止日期、成绩、提交记录和教材下载(9 个工具)。
- **查询公开课表**：课程、上课时间和节次，不用登录(4 个工具)。
- **使用门户登录**：通过阳明交大单点登录查询身份、系统和活动(5 个工具)。
- **兼任签到**：状态、签到和签退，有 `confirm` 和 `dry_run`(3 个工具)。
- **按平台注册**：macOS 有全部 26 个工具，Linux 有 E3 和课表的 18 个。

## 快速开始

```sh
claude plugin marketplace add zyx1121/marketplace
claude plugin install nycu@zyx1121
```

Codex：先 `codex plugin marketplace add zyx1121/marketplace`，再 `codex plugin add nycu@zyx1121`。开新的对话，问它“这周有哪些 E3 作业要交？”。

需要 Bun 1.3.13 以上、uv 和 Python 3.11 以上，Python 可以交给 uv 安装。MCP server 已经打包好，插件目录不需要 `bun install`。

## 使用方法

| 服务 | 工具 | 需要 |
|------|------|------|
| E3 | `e3p_whoami`、`e3p_list_courses`、`e3p_list_assignments`、`e3p_list_due`、`e3p_list_announcements`、`e3p_get_discussion`、`e3p_list_updates`、`e3p_list_notifications`、`e3p_list_quizzes`、`e3p_get_submission`、`e3p_list_grades`、`e3p_get_content`、`e3p_download_file`、`e3p_logout` | E3 令牌，macOS 或 Linux |
| 课表 | `timetable_list_semesters`、`timetable_search_courses`、`timetable_lookup_courses`、`timetable_get_periods` | 不需要，macOS 或 Linux |
| 门户 | `nycu_setup`、`nycu_whoami`、`nycu_list_systems`、`nycu_list_events`、`nycu_logout` | macOS 钥匙串和 Playwright Chromium |
| 签到 | `parttime_get_status`、`parttime_sign_in`、`parttime_sign_out` | 门户登录和校内网络 |

- **E3 登录**：在插件目录运行一次 `uv run scripts/e3p.py login`。密码通过隐藏提示输入，不会经过对话。
- **门户登录**：把学号和密码存进钥匙串项目 `kilo/nycu-portal`，`otpauth://` URI 存进 `kilo/nycu-totp`。再请 agent 运行 `nycu_setup` 准备 Chromium。
- **签到**：`parttime_sign_in` 和 `parttime_sign_out` 会写入真实的出勤记录，需要 `confirm=true`。先用 `dry_run` 试。

## 配置

| 设置 | 位置 | 默认值 |
|------|------|--------|
| 门户令牌 | `NYCU_PORTAL_CONFIG` | `~/.config/nycu/portal.json` |
| E3 令牌 | `NYCU_E3P_CONFIG` | `~/.config/nycu/e3p.json` |
| E3 覆盖 | `NYCU_E3P_TOKEN`、`NYCU_E3P_USERID`、`NYCU_E3P_BASE`、`NYCU_E3P_SERVICE` | 取自 E3 令牌文件 |
| 门户密码 | 钥匙串 `kilo/nycu-portal`，账号是学号 | 门户工具必填 |
| 门户 TOTP | 钥匙串 `kilo/nycu-totp`，账号是学号 | 门户工具必填 |
| 平台覆盖(仅测试用) | `NYCU_FORCE_PLATFORM` | 实际平台 |

令牌文件权限是 600，会遵循 `XDG_CONFIG_HOME`。旧的 `UTILS_NYCU_CONFIG`、`UTILS_E3P_CONFIG` 和 `UTILS_E3P_*` 仍然有效，但 `NYCU_*` 优先。

## 工作原理

Bun 的 MCP server 启动时按平台注册工具，只看平台和 uv，不会登录或连接。每次调用都通过 uv 运行一个 Python 脚本，每个脚本都在文件内声明自己的依赖(PEP 723)。

- 门户的缓存令牌过期时会重新登录一次，仍然失败就报告错误。
- E3 下载只会把令牌发送到已配置的 Moodle `pluginfile` HTTPS 地址，会拒绝跨域重定向，错误信息也不会包含带令牌的地址。

## 限制

- 签到写入是真的。超时不代表已经回滚，超时后请调用 `parttime_get_status` 确认。
- 签到需要校内网络，因为打卡系统只能从校内访问。
- 门户和签到工具需要 macOS，因为要用钥匙串。

## 其他

给 AI agent 的结构化信息与开发说明见[英文版](README.md#for-ai-agents)。

## 许可证

[MIT](LICENSE)
