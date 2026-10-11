# nycu

Claude Code and Codex plugin: a Bun MCP server (`src/`, bundled to `dist/server.js`) that calls Python scripts (`scripts/`) through uv. Read [README.md](README.md) first.

## Rules

- A tool that writes (attendance, logout) needs `confirm=true`, and attendance tools also take `dry_run`. Keep both.
- Never pass a password or a TOTP secret through an MCP tool. Logins read the Keychain or use a hidden prompt.
- Never print a token, a token URL or a password in tool output, errors or logs.
- Keep tool names, parameters and output schemas stable. A change to any of them is a breaking change.
- `plugin.json` and `mcp.json` are the manifest sources. Do not hand-edit the generated `.claude-plugin/plugin.json`, `.mcp.json` or `dist/server.js`.
- Repository documents and code comments are English.

## Where to run things

In Loki's environment, the MacBook is for editing and git only. Run `bun install`, the build and the tests on `ssh sandbox` in a login shell (`bash -lc`). Do not install dependencies in the iCloud clone.

## Verify

```sh
bun install --frozen-lockfile
bun run check
```

- Build with the Bun version that CI uses (`bun-version` in `.github/workflows/check.yml`). Another version produces a different `dist/server.js`, and the CI diff step fails.
- Do not test attendance writes against the real system. Use `dry_run`.

## Release

1. Bump `version` in `package.json` and `plugin.json`, run `bun run check`, and commit the regenerated files.
2. Merge the PR. Then pin the new commit in [zyx1121/marketplace](https://github.com/zyx1121/marketplace) (see its AGENTS.md).
