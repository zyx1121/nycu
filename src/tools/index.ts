import { e3pTools } from "./e3p.ts";
import { nycuTools } from "./nycu.ts";
import { parttimeTools } from "./parttime.ts";
import { paymentsTools } from "./payments.ts";
import { timetableTools } from "./timetable.ts";
export const allTools = [...e3pTools, ...nycuTools, ...paymentsTools, ...parttimeTools, ...timetableTools];
