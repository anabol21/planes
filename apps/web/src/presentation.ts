import type { JobResult } from "./types";

export interface ResultPresentation {
  title: string;
  badge: "feasible" | "infeasible" | "timed_out" | "failed";
  summary: string;
}

export function getResultPresentation(result: JobResult): ResultPresentation {
  if (result.state === "failed") {
    return {
      title: "Backend job failed",
      badge: "failed",
      summary: "The backend reported a structured execution failure.",
    };
  }
  if (result.outcome === "feasible") {
    return {
      title: "Feasible synthetic plan",
      badge: "feasible",
      summary: "The backend returned a feasible synthetic mission plan.",
    };
  }
  if (result.outcome === "infeasible") {
    return {
      title: "Scenario is infeasible",
      badge: "infeasible",
      summary: "Infeasible is a valid solver outcome, not an infrastructure failure.",
    };
  }
  return {
    title: "Solver timed out",
    badge: "timed_out",
    summary: "The backend reached its solver time limit without reporting feasibility.",
  };
}
