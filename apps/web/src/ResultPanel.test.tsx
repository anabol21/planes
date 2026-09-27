// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import fixture from "./test-fixtures/mission-result-v0.json";
import type { JobResult } from "./types";

vi.mock("./MissionMap", () => ({
  MissionMap: () => <div data-testid="mission-map" />,
}));

import { ResultPanel } from "./App";

afterEach(cleanup);

describe("ResultPanel mission map gating", () => {
  it("renders the map for a completed feasible result", async () => {
    render(<ResultPanel result={fixture as JobResult} />);
    expect(await screen.findByTestId("mission-map")).toBeTruthy();
  });

  it.each([
    {
      ...fixture,
      state: "completed",
      outcome: "infeasible",
      mission_plan: null,
    },
    {
      ...fixture,
      state: "timed_out",
      outcome: "timed_out",
      mission_plan: null,
    },
    {
      contract_version: "v0",
      job_id: "job-failed",
      state: "failed",
      error: { message: "failed" },
    },
  ] as const)("does not render a fake map for $state/$outcome", (result) => {
    render(<ResultPanel result={result as JobResult} />);
    expect(screen.queryByTestId("mission-map")).toBeNull();
  });
});
