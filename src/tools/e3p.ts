import { z } from "zod";
import { pushFlag, pushPos } from "../core/argv.ts";
import { scriptTool, type ToolboxTool } from "../core/tool.ts";

const script = "e3p.py";
/** Pure HTTP against Moodle; the only host dependency is the uv runtime. */
const requires = ["binary:uv"];
const envelope = true;
const timeoutMs = 60000;

/** Every call hits the NYCU E3 Moodle API with a stored token. */
const read = { readOnlyHint: true, openWorldHint: true } as const;

export const e3pTools: ToolboxTool[] = [
  scriptTool({
    name: "e3p_logout",
    description: "Forget the stored E3 token/config file. Destructive credential reset: every other e3p tool fails until the user logs in again interactively. Requires confirm=true.",
    inputSchema: { confirm: z.literal(true).describe("Required explicit confirmation.") },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
    script,
    requires,
    envelope,
    timeoutMs,
    buildArgs: () => ["logout"],
  }),
  scriptTool({
    name: "e3p_whoami",
    description: "Show the authenticated E3 user and site info. Cheapest way to check whether the stored token is still valid.",
    inputSchema: {},
    annotations: read,
    script,
    requires,
    envelope,
    timeoutMs,
    buildArgs: () => ["whoami"],
  }),
  scriptTool({
    name: "e3p_list_courses",
    description: "List enrolled E3 courses, sorted newest first, with the enrolment count per course (teachers and TAs included). Past semesters are often hidden; pass show_hidden=true when a course seems missing.",
    inputSchema: { show_hidden: z.boolean().optional().describe("Include hidden/archived courses.") },
    annotations: read,
    script,
    requires,
    envelope,
    timeoutMs,
    buildArgs: (input) => {
      const argv = ["courses"];
      pushFlag(argv, "--hidden", input.show_hidden);
      return argv;
    },
  }),
  scriptTool({
    name: "e3p_list_assignments",
    description: "List assignments for one course or all enrolled courses. status=true costs one extra API call per assignment, so scope it with courseid.",
    inputSchema: { courseid: z.number().optional().describe("Course ID. Omit for all courses."), status: z.boolean().optional().describe("Also fetch submission status per assignment.") },
    annotations: read,
    script,
    requires,
    envelope,
    timeoutMs,
    truncationHint: "pass courseid to scope to one course, or drop status",
    buildArgs: (input) => {
      const argv = ["assignments"];
      pushPos(argv, input.courseid);
      pushFlag(argv, "--status", input.status);
      return argv;
    },
  }),
  scriptTool({
    name: "e3p_list_due",
    description: "List upcoming E3 action events and deadlines. Shows only what E3 itself tracks, so deadlines announced only in class are absent.",
    inputSchema: { days: z.number().optional().describe("Look-ahead days. Default: 14."), limit: z.number().optional().describe("Maximum events. Default: 50.") },
    annotations: read,
    script,
    requires,
    envelope,
    timeoutMs,
    truncationHint: "lower days or limit",
    buildArgs: (input) => {
      const argv = ["due"];
      pushFlag(argv, "--days", input.days);
      pushFlag(argv, "--limit", input.limit);
      return argv;
    },
  }),
  scriptTool({
    name: "e3p_list_announcements",
    description: "List recent posts from the announcements forum of one course or all visible enrolled courses, newest first, with the full message text and attachment URLs (input to e3p_download_file).",
    inputSchema: {
      courseid: z.number().optional().describe("Course ID. Omit for all visible courses."),
      days: z.number().optional().describe("Look-back days. Default: 30."),
      limit: z.number().optional().describe("Maximum posts per course. Default: 20."),
    },
    annotations: read,
    script,
    requires,
    envelope,
    timeoutMs,
    truncationHint: "pass courseid to scope to one course, or lower days",
    buildArgs: (input) => {
      const argv = ["announcements"];
      pushPos(argv, input.courseid);
      pushFlag(argv, "--days", input.days);
      pushFlag(argv, "--limit", input.limit);
      return argv;
    },
  }),
  scriptTool({
    name: "e3p_get_submission",
    description: "Get detailed submission status for one assignment.",
    inputSchema: { assignid: z.number().describe("Assignment ID.") },
    annotations: read,
    script,
    requires,
    envelope,
    timeoutMs,
    buildArgs: (input) => ["submission", String(input.assignid)],
  }),
  scriptTool({
    name: "e3p_list_grades",
    description: "List gradebook items for one course or all enrolled courses. Grades not released by the instructor read as empty rather than missing.",
    inputSchema: { courseid: z.number().optional().describe("Course ID. Omit for all courses.") },
    annotations: read,
    script,
    requires,
    envelope,
    timeoutMs,
    truncationHint: "pass courseid to scope to one course",
    buildArgs: (input) => {
      const argv = ["grades"];
      pushPos(argv, input.courseid);
      return argv;
    },
  }),
  scriptTool({
    name: "e3p_get_content",
    description: "Get a course outline with sections and activities. Whole-semester outlines are long and get truncated; file URLs here are the input to e3p_download_file.",
    inputSchema: { courseid: z.number().describe("Course ID.") },
    annotations: read,
    script,
    requires,
    envelope,
    timeoutMs,
    truncationHint: "read the outline section by section",
    buildArgs: (input) => ["content", String(input.courseid)],
  }),
  scriptTool({
    name: "e3p_download_file",
    description: "Download a Moodle pluginfile.php URL with the stored auth token. A plain fetch of the same URL returns a login page instead of the file.",
    inputSchema: { url: z.string().describe("pluginfile.php URL."), out: z.string().optional().describe("Output path. Default: URL basename.") },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: true },
    script,
    requires,
    envelope,
    timeoutMs,
    buildArgs: (input) => {
      const argv = ["download", input.url];
      pushFlag(argv, "--out", input.out);
      return argv;
    },
  }),
];
