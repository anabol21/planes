export const CONTRACT_VERSION = "v0" as const;

export type JsonObject = Record<string, unknown>;
export type LifecycleState =
  | "queued"
  | "running"
  | "completed"
  | "timed_out"
  | "failed";
export type EngineOutcome = "feasible" | "infeasible" | "timed_out" | "error";

export interface PolygonGeometry extends JsonObject {
  type: "Polygon";
  coordinates: number[][][];
}

export interface ScenarioV0 extends JsonObject {
  scenario_id: string;
  crs: "EPSG:4326";
  survey_areas: Array<{ id: string; geometry: PolygonGeometry }>;
  restricted_zones: Array<{
    id: string;
    name: string | null;
    kind: string | null;
    altitudes_text: string | null;
    geometry: PolygonGeometry;
  }>;
  obstacles: Array<{
    id: string;
    kind: string | null;
    height_m: number;
    geometry: PolygonGeometry;
  }>;
  aerodromes: Array<{ id: string; lat_deg: number; lon_deg: number }>;
  board_cards: Array<{
    id: string;
    model_id: string;
    camera_id: string;
    aerodrome_id: string;
    count: number;
  }>;
  survey: {
    survey_type: string;
    required_spectrum: string;
    gsd_cm_per_px: number;
    overlap_front: number;
    overlap_side: number;
    strip_direction_deg: number;
  };
  wind: { speed_mps: number; direction_deg: number };
}

export interface OptimizationV0 extends JsonObject {
  objective: "min_time" | "min_total_flight_time";
  time_limit_seconds: number;
}

export interface SubmitJobRequest {
  contract_version: typeof CONTRACT_VERSION;
  scenario: ScenarioV0;
  optimization: OptimizationV0;
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
