import {
  CONTRACT_VERSION,
  isTerminalState,
  type JobResult,
  type JobStatus,
  type JsonObject,
  type LifecycleState,
  type SubmitJobRequest,
} from "./types";

const LIFECYCLE_STATES = new Set<LifecycleState>([
  "queued",
  "running",
  "completed",
  "timed_out",
  "failed",
]);

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number | null = null,
    readonly details: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class InputError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InputError";
  }
}

export interface JobApi {
  submitJob(request: SubmitJobRequest, signal?: AbortSignal): Promise<JobStatus>;
  getJob(jobId: string, signal?: AbortSignal): Promise<JobStatus>;
  getJobResult(jobId: string, signal?: AbortSignal): Promise<JobResult>;
}

interface JsonResponse {
  status: number;
  payload: JsonObject;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function assertStatus(value: unknown): JobStatus {
  if (!isObject(value)) {
    throw new ApiError("Backend returned an invalid job status.", "invalid_response");
  }
  const timestampsValid = ["created_at", "started_at", "finished_at"].every(
    (key) => typeof value[key] === "string" || value[key] === null,
  );
  if (
    value.contract_version !== CONTRACT_VERSION ||
    typeof value.job_id !== "string" ||
    typeof value.state !== "string" ||
    !LIFECYCLE_STATES.has(value.state as LifecycleState) ||
    !timestampsValid
  ) {
    throw new ApiError("Backend returned an invalid job status.", "invalid_response", null, value);
  }
  return value as unknown as JobStatus;
}

function assertResult(value: unknown): JobResult {
  if (
    !isObject(value) ||
    value.contract_version !== CONTRACT_VERSION ||
    typeof value.job_id !== "string" ||
    (value.state !== "completed" && value.state !== "timed_out" && value.state !== "failed")
  ) {
    throw new ApiError("Backend returned an invalid job result.", "invalid_response", null, value);
  }
  if (value.state === "failed") {
    if (value.error !== null && !isObject(value.error)) {
      throw new ApiError("Backend returned an invalid failure result.", "invalid_response", null, value);
    }
    return value as unknown as JobResult;
  }
  if (
    ((value.state === "completed" &&
      value.outcome !== "feasible" &&
      value.outcome !== "infeasible") ||
      (value.state === "timed_out" && value.outcome !== "timed_out")) ||
    !isObject(value.solver_report) ||
    !Array.isArray(value.artifacts) ||
    (value.mission_plan !== null && !isObject(value.mission_plan))
  ) {
    throw new ApiError("Backend returned an invalid compute result.", "invalid_response", null, value);
  }
  return value as unknown as JobResult;
}

export class RequestCoordinator {
  private generation = 0;
  private controller: AbortController | null = null;

  begin(): { generation: number; signal: AbortSignal } {
    this.controller?.abort();
    this.generation += 1;
    this.controller = new AbortController();
    return { generation: this.generation, signal: this.controller.signal };
  }

  cancel(): void {
    this.generation += 1;
    this.controller?.abort();
    this.controller = null;
  }

  isCurrent(generation: number): boolean {
    return generation === this.generation;
  }
}

async function readJson(response: Response): Promise<JsonObject> {
  const text = await response.text();
  try {
    const parsed: unknown = JSON.parse(text);
    if (!isObject(parsed)) {
      throw new Error("response is not an object");
    }
    return parsed;
  } catch (error) {
    throw new ApiError(
      "Backend returned invalid JSON.",
      "invalid_response",
      response.status,
      error,
    );
  }
}

async function requestJson(
  fetchImpl: typeof fetch,
  url: string,
  init: RequestInit,
): Promise<JsonResponse> {
  let response: Response;
  try {
    response = await fetchImpl(url, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError("Cannot reach the backend API.", "network_error", null, error);
  }

  const payload = await readJson(response);
  if (!response.ok) {
    const code = typeof payload.error === "string" ? payload.error : "http_error";
    const message =
      typeof payload.message === "string"
        ? payload.message
        : `Backend request failed with HTTP ${response.status}.`;
    throw new ApiError(message, code, response.status, payload);
  }
  return { status: response.status, payload };
}

function expectStatus(actual: number, expected: number, payload: JsonObject): void {
  if (actual !== expected) {
    throw new ApiError(
      `Backend returned unexpected HTTP ${actual}; expected ${expected}.`,
      "unexpected_status",
      actual,
      payload,
    );
  }
}

export function createApiClient(fetchImpl: typeof fetch = fetch): JobApi {
  return {
    async submitJob(request, signal) {
      const response = await requestJson(fetchImpl, "/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
        signal,
      });
      expectStatus(response.status, 202, response.payload);
      return assertStatus(response.payload);
    },
    async getJob(jobId, signal) {
      const response = await requestJson(
        fetchImpl,
        `/api/jobs/${encodeURIComponent(jobId)}`,
        { method: "GET", signal },
      );
      expectStatus(response.status, 200, response.payload);
      return assertStatus(response.payload);
    },
    async getJobResult(jobId, signal) {
      const response = await requestJson(
        fetchImpl,
        `/api/jobs/${encodeURIComponent(jobId)}/result`,
        { method: "GET", signal },
      );
      expectStatus(response.status, 200, response.payload);
      return assertResult(response.payload);
    },
  };
}

function parseJsonObject(label: string, text: string): JsonObject {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new InputError(`${label} must be valid JSON.`);
  }
  if (!isObject(value)) {
    throw new InputError(`${label} must be a JSON object.`);
  }
  return value;
}

export function parseSubmission(
  scenarioText: string,
  optimizationText: string,
  seedText: string,
): SubmitJobRequest {
  const scenario = parseJsonObject("Scenario", scenarioText);
  const optimization = parseJsonObject("Optimization", optimizationText);
  if (!/^-?\d+$/.test(seedText.trim())) {
    throw new InputError("Seed must be an integer.");
  }
  const seed = Number(seedText);
  if (!Number.isSafeInteger(seed)) {
    throw new InputError("Seed must be a safe integer.");
  }
  return { contract_version: CONTRACT_VERSION, scenario, optimization, seed };
}

export async function submitFromEditors(
  api: JobApi,
  scenarioText: string,
  optimizationText: string,
  seedText: string,
  signal?: AbortSignal,
): Promise<JobStatus> {
  return api.submitJob(parseSubmission(scenarioText, optimizationText, seedText), signal);
}

function abortableDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(resolve, milliseconds);
    signal.addEventListener(
      "abort",
      () => {
        window.clearTimeout(timer);
        reject(new DOMException("Polling cancelled.", "AbortError"));
      },
      { once: true },
    );
  });
}

export interface PollOptions {
  api: JobApi;
  jobId: string;
  signal: AbortSignal;
  onStatus: (status: JobStatus) => void;
  intervalMs?: number;
  wait?: (milliseconds: number, signal: AbortSignal) => Promise<void>;
}

export async function pollJobLifecycle({
  api,
  jobId,
  signal,
  onStatus,
  intervalMs = 1000,
  wait = abortableDelay,
}: PollOptions): Promise<JobResult> {
  while (true) {
    signal.throwIfAborted();
    const status = await api.getJob(jobId, signal);
    onStatus(status);
    if (isTerminalState(status.state)) {
      return api.getJobResult(jobId, signal);
    }
    await wait(intervalMs, signal);
  }
}
