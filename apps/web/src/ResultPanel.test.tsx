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
  it("summarizes the solver metric without a backend assignment list", () => {
    const result = {
      ...fixture,
      mission_plan: {
        ...fixture.mission_plan,
        criterion: "min_time",
        mission: { mission_time_s: 120.5, total_flight_time_s: 400 },
      },
      solver_report: {
        ...fixture.solver_report,
        limitations: ["PHYS-DEM: Рельеф отсутствует или нечисловой"],
      },
    };
    render(<ResultPanel result={result as JobResult} />);
    expect(screen.getByText("C_max")).toBeTruthy();
    expect(screen.getByText("120.50 с")).toBeTruthy();
    expect(screen.getByText("PHYS-DEM")).toBeTruthy();
    expect(screen.queryByText(/Задание backend/)).toBeNull();
  });

  it("shows a physical diagnostic code", () => {
    const result = {
      ...fixture,
      solver_report: {
        ...fixture.solver_report,
        limitations: ["PHYS-AIRSPACE: Маршрут входит в зону, активную на высоте сегмента"],
      },
    };
    render(<ResultPanel result={result as JobResult} />);
    expect(document.querySelector(".limitations")?.textContent).toContain("PHYS-AIRSPACE");
  });

  it("shows identical limitation lines once and keeps distinct remarks", () => {
    const reason = "uncovered swaths=5378: a swath exceeds endurance even with recharge and best pads";
    const perUav = "БВС 1: one swath exceeds endurance even with best pads";
    const result = {
      ...fixture,
      solver_report: {
        ...fixture.solver_report,
        limitations: [
          reason,
          reason,
          reason,
          "uncovered_swaths=5378",
          perUav,
          perUav,
          perUav,
          "PHYS-ENDURANCE: Вылет длиннее выносливости борта",
        ],
      },
    };
    render(<ResultPanel result={result as JobResult} />);
    const items = [...document.querySelectorAll(".limitations li")].map((item) => item.textContent);
    expect(items).toEqual([
      reason,
      "uncovered_swaths=5378",
      perUav,
      "PHYS-ENDURANCE: Вылет длиннее выносливости борта",
    ]);
  });

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
