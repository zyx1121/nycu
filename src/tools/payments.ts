import { z } from "zod";
import { pushFlag } from "../core/argv.ts";
import { scriptTool, type ToolboxTool } from "../core/tool.ts";

const script = "payments.py";
/** Rides the nycu portal SSO layer: Keychain + headless Chromium, macOS only. Works off campus. */
const requires = ["platform:darwin", "binary:uv"];
const envelope = true;
// Cold path is a ~25s portal login, then a browser sign-in to the payment system; the system sometimes stalls and is retried twice.
const timeoutMs = 180000;

const day = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);

export const paymentsTools: ToolboxTool[] = [
  scriptTool({
    name: "nycu_list_payments",
    description:
      "List what NYCU paid you between two dates, from the cashier's payment inquiry system: reimbursements and other cashier payments (kind cashier, with the voucher memo saying what each was for, the receiving bank and the account's last 4 digits) and payroll batches (kind salary, with the payroll name). Amounts in TWD. Use it to match bank deposits from the university.",
    inputSchema: {
      from: day.optional().describe("First day, YYYY-MM-DD. Default: January 1 of this year."),
      to: day.optional().describe("Last day, YYYY-MM-DD. Default: today."),
      kind: z.enum(["cashier", "salary"]).optional().describe("Only this kind. Default: both."),
    },
    annotations: { readOnlyHint: true, openWorldHint: true },
    script,
    requires,
    envelope,
    timeoutMs,
    buildArgs: (input) => {
      const argv = ["list"];
      pushFlag(argv, "--from", input.from);
      pushFlag(argv, "--to", input.to);
      pushFlag(argv, "--kind", input.kind);
      return argv;
    },
  }),
];
