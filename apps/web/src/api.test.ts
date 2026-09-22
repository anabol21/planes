import { describe, expect, it, vi } from "vitest";

import {
  createApiClient,
  pollJobLifecycle,
  RequestCoordinator,
  submitFromEditors,
  type JobApi,
} from "./api";
import type { JobResult, JobStatus, SubmitJobRequest } from "./types";

const QUEUED: JobStatus = {
  contract_version: "v0",
  job_id: "job-001",
  state: "queued",
  created_at: "2026-09-22T10:00:00+00:00",
  started_at: null,
  finished_at: null,
};

const RUNNING: JobStatus = {
  ...QUEUED,
  state: "running",
  started_at: "2026-09-22T10:00:01+00:00",
};

const COMPLETED: JobStatus = {
  ...RUNNING,
  state: "completed",
  finished_at: "2026-09-22T10:00:02+00:00",
};

const FEASIBLE: JobResult = {
  contract_version: "v0",
  job_id: "job-001",
  state: "completed",
  outcome: "feasible",
  mission_plan: { test_data: true },
  solver_report: { method: "fake" },
  artifacts: [],
};

function response(status: number, payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function createFakeApi(statuses: JobStatus[], result: JobResult = FEASIBLE) {
  let statusIndex = 0;
  const api: JobApi = {
    submitJob: vi.fn(async () => QUEUED),
    getJob: vi.fn(async () => statuses[Math.min(statusIndex++, statuses.length - 1)]),
    getJobResult: vi.fn(async () => result),
  };
  return api;
}

const noWait = async () => Promise.resolve();

describe("API client", () => {
  it("serializes the v0 submission request exactly", async () => {
    const fetchMock = vi.fn(async () => response(202, QUEUED));
    const api = createApiClient(fetchMock as typeof fetch);
    const request: SubmitJobRequest = {
      contract_version: "v0",
      scenario: { name: "Demo mission" },
      optimization: { test_outcome: "feasible" },
      seed: 17,
    };

    await api.submitJob(request);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/jobs",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(request),
      }),
    );
  });

  it("returns the submitted job from a successful POST", async () => {
    const api = createApiClient(vi.fn(async () => response(202, QUEUED)) as typeof fetch);
    const submitted = await api.submitJob({
      contract_version: "v0",
      scenario: { name: "Demo" },
      optimization: {},
      seed: 17,
    });
    expect(submitted).toEqual(QUEUED);
  });
});

describe("polling", () => {
  it("continues through queued and running before stopping at completed", async () => {
    const api = createFakeApi([QUEUED, RUNNING, COMPLETED]);
    const observed: string[] = [];
    const result = await pollJobLifecycle({
      api,
      jobId: QUEUED.job_id,
      signal: new AbortController().signal,
      onStatus: (status) => observed.push(status.state),
      wait: noWait,
    });

    expect(observed).toEqual(["queued", "running", "completed"]);
    expect(api.getJob).toHaveBeenCalledTimes(3);
    expect(result).toEqual(FEASIBLE);
  });

  it("fetches the terminal result exactly once", async () => {
    const api = createFakeApi([COMPLETED]);
    await pollJobLifecycle({
      api,
      jobId: QUEUED.job_id,
      signal: new AbortController().signal,
      onStatus: vi.fn(),
      wait: noWait,
    });
    expect(api.getJobResult).toHaveBeenCalledOnce();
  });

  it.each([
    ["feasible", FEASIBLE],
    [
      "infeasible",
      { ...FEASIBLE, outcome: "infeasible", mission_plan: null } satisfies JobResult,
    ],
    [
      "timed_out",
      {
        ...FEASIBLE,
        state: "timed_out",
        outcome: "timed_out",
        mission_plan: null,
      } satisfies JobResult,
    ],
    [
      "failed",
      {
        contract_version: "v0",
        job_id: "job-001",
        state: "failed",
        error: { type: "RuntimeError", message: "simulated" },
      } satisfies JobResult,
    ],
  ] as const)("returns the authoritative %s terminal result", async (_name, expected) => {
    const terminalStatus: JobStatus = {
      ...COMPLETED,
      state: expected.state,
    };
    const api = createFakeApi([terminalStatus], expected);
    const result = await pollJobLifecycle({
      api,
      jobId: QUEUED.job_id,
      signal: new AbortController().signal,
      onStatus: vi.fn(),
      wait: noWait,
    });
    expect(result).toEqual(expected);
  });

  it("stops without fetching a result when polling is cancelled", async () => {
    const controller = new AbortController();
    const api = createFakeApi([QUEUED]);
    const polling = pollJobLifecycle({
      api,
      jobId: QUEUED.job_id,
      signal: controller.signal,
      onStatus: () => controller.abort(),
      wait: noWait,
    });

    await expect(polling).rejects.toMatchObject({ name: "AbortError" });
    expect(api.getJobResult).not.toHaveBeenCalled();
  });
});

describe("request cancellation", () => {
  it("cancels the previous request when a replacement submission begins", () => {
    const coordinator = new RequestCoordinator();
    const first = coordinator.begin();
    const second = coordinator.begin();

    expect(first.signal.aborted).toBe(true);
    expect(second.signal.aborted).toBe(false);
    expect(coordinator.isCurrent(first.generation)).toBe(false);
    expect(coordinator.isCurrent(second.generation)).toBe(true);
  });

  it("cancels the active request when the owning component is disposed", () => {
    const coordinator = new RequestCoordinator();
    const active = coordinator.begin();

    coordinator.cancel();

    expect(active.signal.aborted).toBe(true);
    expect(coordinator.isCurrent(active.generation)).toBe(false);
  });
});

describe("editor validation", () => {
  it("prevents submission when scenario JSON is malformed", async () => {
    const api = createFakeApi([QUEUED]);
    await expect(submitFromEditors(api, "{", "{}", "17")).rejects.toThrow(
      "Scenario must be valid JSON.",
    );
    expect(api.submitJob).not.toHaveBeenCalled();
  });

  it("prevents submission when optimization JSON is malformed", async () => {
    const api = createFakeApi([QUEUED]);
    await expect(submitFromEditors(api, "{}", "{", "17")).rejects.toThrow(
      "Optimization must be valid JSON.",
    );
    expect(api.submitJob).not.toHaveBeenCalled();
  });

  it("prevents submission when the seed is not an integer", async () => {
    const api = createFakeApi([QUEUED]);
    await expect(submitFromEditors(api, "{}", "{}", "1.5")).rejects.toThrow(
      "Seed must be an integer.",
    );
    expect(api.submitJob).not.toHaveBeenCalled();
  });
});
