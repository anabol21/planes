// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import enduranceFixture from "./test-fixtures/B2_recharge_OFF.response.json";
import catalogFixture from "./test-fixtures/catalog_validation.json";
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

  it("renders the map for a completed feasible result", async () => {
    render(<ResultPanel result={fixture as JobResult} />);
    expect(await screen.findByTestId("mission-map")).toBeTruthy();
  });

  it("shows a Russian refusal card for the live endurance-no-recharge capture", () => {
    const result = {
      ...enduranceFixture,
      state: "completed",
      mission_plan: null,
      artifacts: [],
    } as JobResult;
    render(<ResultPanel result={result} />);
    const card = document.querySelector(".outcome-card");
    expect(card?.getAttribute("data-error-code")).toBe("INFEASIBLE_ENDURANCE_NO_RECHARGE");
    expect(card?.textContent).toContain("Не хватает ресурса одного вылета");
    expect(card?.textContent).toMatch(/запрете дозарядки/);
    expect(screen.getByText("Сценарий нельзя выполнить")).toBeTruthy();
    expect(document.querySelector(".limitations")?.textContent).not.toMatch(/sitecustomize|iso f2c|f2c_isolated_worker|traceback/i);
    expect(card?.textContent).not.toMatch(/sitecustomize|iso f2c|f2c_isolated_worker|traceback/i);
  });

  it("shows a Russian catalog card without the bridge traceback", () => {
    render(
      <ResultPanel
        result={{
          contract_version: "v0",
          job_id: "cat-uav",
          state: "failed",
          error: { outcome: "error", message: catalogFixture.invalid_uav.message },
        }}
      />,
    );
    const card = document.querySelector(".outcome-card");
    expect(card?.getAttribute("data-error-code")).toBe("ERROR_UAV_NOT_IN_CATALOG");
    expect(card?.textContent).toContain("Модель БВС не найдена в каталоге");
    expect(card?.textContent).toMatch(/нет в каталоге флота/);
    expect(card?.textContent).not.toMatch(/grisha_f2c_bridge|traceback|sitecustomize/i);
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
