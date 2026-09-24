export const CONTRACT_VERSION = "v0" as const;

export type JsonObject = Record<string, unknown>;
export type LifecycleState =
  | "queued"
  | "running"
  | "completed"
  | "timed_out"
  | "failed";
export type EngineOutcome = "feasible" | "infeasible" | "timed_out" | "error";

export interface SubmitJobRequest {
  contract_version: typeof CONTRACT_VERSION;
  scenario: JsonObject;
  optimization: JsonObject;
  seed: number;
}

export interface JobStatus {
  contract_version: typeof CONTRACT_VERSION;
  job_id: string;
  state: LifecycleState;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

interface ComputeResultBase {
  contract_version: typeof CONTRACT_VERSION;
  job_id: string;
  mission_plan: JsonObject | null;
  solver_report: JsonObject;
  artifacts: unknown[];
}

export interface CompletedResult extends ComputeResultBase {
  state: "completed";
  outcome: "feasible" | "infeasible";
}

export interface TimedOutResult extends ComputeResultBase {
  state: "timed_out";
  outcome: "timed_out";
}

export interface FailedResult {
  contract_version: typeof CONTRACT_VERSION;
  job_id: string;
  state: "failed";
  error: JsonObject | null;
}

export type JobResult = CompletedResult | TimedOutResult | FailedResult;

export function isTerminalState(state: LifecycleState): boolean {
  return state === "completed" || state === "timed_out" || state === "failed";
}
