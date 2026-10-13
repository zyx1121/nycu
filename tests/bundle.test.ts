import { test, expect } from "bun:test";
import { mkdtemp, cp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

for (const platform of ["darwin", "linux"]) {
  test(`standalone ${platform} bundle: registration, static read, missing credentials and confirmation`, async () => {
    const temp = await mkdtemp(join(tmpdir(), "nycu plugin "));
    const client = new Client({ name: "nycu-test", version: "1" });
    try {
      for (const dir of ["dist", "scripts", "lib"]) await cp(new URL("../" + dir, import.meta.url), join(temp, dir), { recursive: true });
      const env = Object.fromEntries(Object.entries(process.env).filter(([key, value]) => value !== undefined && !key.startsWith("NYCU_") && !key.startsWith("UTILS_"))) as Record<string,string>;
      Object.assign(env, { XDG_CONFIG_HOME: join(temp, "config"), NYCU_FORCE_PLATFORM: platform });
      await client.connect(new StdioClientTransport({ command: process.execPath, args: [join(temp, "dist/server.js")], cwd: temp, env, stderr: "pipe" }));
      const listed = await client.listTools();
      expect(listed.tools).toHaveLength(platform === "darwin" ? 26 : 18);
      const result = await client.callTool({ name: "timetable_get_periods", arguments: {} });
      expect(result.isError).not.toBe(true);
      expect((result.structuredContent as {data: {days: Record<string,string>}}).data.days.M).toBe("Mon");
      const missing = await client.callTool({ name: "e3p_whoami", arguments: {} });
      expect(missing.isError).toBe(true);
      expect(JSON.stringify(missing)).toContain("not logged in");
      const rejected = await client.callTool({ name: "e3p_logout", arguments: {} });
      expect(rejected.isError).toBe(true);
      if (platform === "darwin") {
        const attendance = await client.callTool({ name: "parttime_sign_in", arguments: {} });
        expect(attendance.isError).toBe(true);
        expect(JSON.stringify(attendance)).toContain("confirm");
      }
    } finally { await client.close(); await rm(temp, { recursive: true, force: true }); }
  }, 60000);
}
