<div align="center">

<h1>NYCU</h1>

<p><strong>NYCU portal, E3, timetable and part-time attendance as MCP tools for your agent.</strong></p>

[![CI](https://img.shields.io/github/actions/workflow/status/zyx1121/nycu/check.yml?branch=main&style=flat-square&label=CI)](https://github.com/zyx1121/nycu/actions)
[![Claude Code](https://img.shields.io/badge/Claude_Code-plugin-D97757?style=flat-square)](https://github.com/zyx1121/marketplace)
[![License](https://img.shields.io/github/license/zyx1121/nycu?style=flat-square)](LICENSE)

**English** | [繁體中文](README.zh-TW.md) | [简体中文](README.zh-CN.md)

</div>

```
> "Which E3 assignments are due this week?"
  ⚡ e3p_list_due { "days": 7 }
✓ 3 assignments: 2 on Friday, 1 next Monday.
```

NYCU students use three websites for E3 coursework, the course timetable and part-time attendance. This plugin gives Codex and Claude Code 21 tools for them, and every tool that writes needs an explicit confirmation.

## Features

- **Reads E3**: courses, assignments, deadlines, grades, submissions and material downloads (9 tools).
- **Searches the public timetable**: courses, class times and periods, with no login (4 tools).
- **Uses the portal session**: identity, systems and events through NYCU single sign-on (5 tools).
- **Signs part-time attendance**: status, sign-in and sign-out, with `confirm` and `dry_run` (3 tools).
- **Registers by platform**: macOS gets all 21 tools. Linux gets the 13 E3 and timetable tools.

## Quick start

```sh
claude plugin marketplace add zyx1121/marketplace
claude plugin install nycu@zyx1121
```

Codex: `codex plugin marketplace add zyx1121/marketplace`, then `codex plugin add nycu@zyx1121`. Start a new session and ask "Which E3 assignments are due this week?".

The plugin needs Bun 1.3.13 or later, uv, and Python 3.11 or later. uv can install Python. The MCP server ships bundled, so the plugin directory needs no `bun install`.

## Usage

| Service | Tools | Needs |
|---------|-------|-------|
| E3 | `e3p_whoami`, `e3p_list_courses`, `e3p_list_assignments`, `e3p_list_due`, `e3p_get_submission`, `e3p_list_grades`, `e3p_get_content`, `e3p_download_file`, `e3p_logout` | an E3 token, macOS or Linux |
| Timetable | `timetable_list_semesters`, `timetable_search_courses`, `timetable_lookup_courses`, `timetable_get_periods` | nothing, macOS or Linux |
| Portal | `nycu_setup`, `nycu_whoami`, `nycu_list_systems`, `nycu_list_events`, `nycu_logout` | macOS Keychain and Playwright Chromium |
| Attendance | `parttime_get_status`, `parttime_sign_in`, `parttime_sign_out` | the portal session and the campus network |

- **E3 login**: in the plugin directory, run `uv run scripts/e3p.py login` once. It asks for the password at a hidden prompt, so the password never passes through the conversation.
- **Portal login**: store your student ID and password in the Keychain item `kilo/nycu-portal`, and the `otpauth://` URI in `kilo/nycu-totp`. Then ask the agent to run `nycu_setup`, which prepares Chromium.
- **Attendance**: `parttime_sign_in` and `parttime_sign_out` write real attendance records. They need `confirm=true`. Use `dry_run` first.

## Configuration

| Setting | Where | Default |
|---------|-------|---------|
| Portal token | `NYCU_PORTAL_CONFIG` | `~/.config/nycu/portal.json` |
| E3 token | `NYCU_E3P_CONFIG` | `~/.config/nycu/e3p.json` |
| E3 overrides | `NYCU_E3P_TOKEN`, `NYCU_E3P_USERID`, `NYCU_E3P_BASE`, `NYCU_E3P_SERVICE` | from the E3 token file |
| Portal password | Keychain `kilo/nycu-portal`, account = student ID | required for portal tools |
| Portal TOTP | Keychain `kilo/nycu-totp`, account = student ID | required for portal tools |
| Platform override, tests only | `NYCU_FORCE_PLATFORM` | the real platform |

Token files have mode 600 and follow `XDG_CONFIG_HOME`. The older `UTILS_NYCU_CONFIG`, `UTILS_E3P_CONFIG` and `UTILS_E3P_*` names still work, but the `NYCU_*` names win.

## How it works

The Bun MCP server registers the tools for the platform at startup. It looks only at the platform and uv, and it does not log in or connect. Each call runs a Python script through uv, and each script declares its packages inline (PEP 723).

- The portal relogs once when its cached token expires, then reports the error.
- E3 downloads send the token only to the configured Moodle `pluginfile` URL over HTTPS. They reject cross-origin redirects, and error messages never contain the token URL.

## Limits

- Attendance writes are real. A timeout does not mean a rollback, so call `parttime_get_status` after a timeout.
- Attendance needs the campus network, because the timeclock is reachable only from there.
- Portal and attendance tools need macOS, for the Keychain.

## For AI agents

Facts for coding agents and LLM tools. The rules for changing the code are in [AGENTS.md](AGENTS.md).

- **Summary**: Claude Code and Codex plugin with 21 MCP tools for NYCU E3, the public timetable, the portal and part-time attendance.
- **Type**: plugin
- **Interfaces**: MCP `nycu` (stdio, `dist/server.js`). Python scripts in `scripts/` run under uv.
- **Install**: `claude plugin install nycu@zyx1121`, after `claude plugin marketplace add zyx1121/marketplace`
- **Run**: the host starts the MCP server
- **Verify**: call `timetable_list_semesters`, which needs no login
- **Config**: `NYCU_PORTAL_CONFIG`, `NYCU_E3P_CONFIG`, `NYCU_E3P_TOKEN`, `NYCU_E3P_USERID`, `NYCU_E3P_BASE`, `NYCU_E3P_SERVICE`
- **Secrets**: Keychain `kilo/nycu-portal` and `kilo/nycu-totp`, and the token files in `~/.config/nycu/`
- **Limits**: attendance writes are real and need `confirm=true`. Portal tools are macOS only.

## Development

```sh
bun install --frozen-lockfile
bun run check
```

`plugin.json` and `mcp.json` are the manifest sources. The build writes the Claude-compatible files and `dist/server.js`, and CI fails when the committed copies differ. The tests use synthetic data, so CI needs no NYCU account and never signs attendance.

## License

[MIT](LICENSE)
