import { test, expect, beforeEach } from "bun:test";
import type { ZodType } from "zod";
import { allTools } from "../src/tools/index.ts";
import { selectRunnableTools } from "../src/core/tool.ts";
import { clearRequirementCache } from "../src/core/requires.ts";

beforeEach(clearRequirementCache);
test("macOS registers 22 tools; Linux keeps 14 E3/timetable tools", async () => {
  const mac = await selectRunnableTools(allTools, { check: async r => ["platform:darwin", "binary:uv"].includes(r) });
  expect(mac.registered).toHaveLength(22);
  expect(mac.hidden).toHaveLength(0);
  clearRequirementCache();
  const linux = await selectRunnableTools(allTools, { check: async r => ["platform:linux", "binary:uv"].includes(r) });
  expect(linux.registered).toHaveLength(14);
  expect([...new Set(linux.registered.map(t => t.name.split("_")[0]))].sort()).toEqual(["e3p", "timetable"]);
  expect(linux.hidden).toHaveLength(8);
});
test("failed dependency probes hide tools without crashing the server", async () => {
  const selected = await selectRunnableTools(allTools, { check: async () => { throw Error("missing dependency"); } });
  expect(selected.registered).toHaveLength(0);
  expect(selected.hidden).toHaveLength(22);
});
test("tool names stay unique and destructive operations retain confirmation", () => {
  expect(new Set(allTools.map(t => t.name)).size).toBe(22);
  for (const tool of allTools) {
    if (tool.annotations.destructiveHint) {
      expect((tool.inputSchema.confirm as ZodType).safeParse(true).success).toBe(true);
      expect((tool.inputSchema.confirm as ZodType).safeParse(false).success).toBe(false);
      expect((tool.inputSchema.confirm as ZodType).safeParse(undefined).success).toBe(false);
    }
  }
});
