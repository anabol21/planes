import { describe, expect, it } from "vitest";

import { getResultPresentation } from "./presentation";
import type { JobResult } from "./types";

const BASE = {
  contract_version: "v0",
  job_id: "job-001",
  solver_report: {},
  artifacts: [],
} as const;

describe("terminal result presentation", () => {
  it.each([
    [
      { ...BASE, state: "completed", outcome: "feasible", mission_plan: {} },
      "feasible",
      "Feasible synthetic plan",
    ],
    [
      { ...BASE, state: "completed", outcome: "infeasible", mission_plan: null },
      "infeasible",
      "Scenario is infeasible",
    ],
    [
      { ...BASE, state: "timed_out", outcome: "timed_out", mission_plan: null },
      "timed_out",
      "Solver timed out",
    ],
    [
      {
        contract_version: "v0",
        job_id: "job-001",
        state: "failed",
        error: { message: "simulated" },
      },
      "failed",
      "Backend job failed",
    ],
  ] as const)("maps an authoritative result to the %s presentation", (result, badge, title) => {
    const presentation = getResultPresentation(result as JobResult);
    expect(presentation.badge).toBe(badge);
    expect(presentation.title).toBe(title);
  });
});
