import { describe, expect, it } from "vitest";

import enduranceFixture from "./test-fixtures/B2_recharge_OFF.response.json";
import catalogFixture from "./test-fixtures/catalog_validation.json";
import {
  inferErrorCode,
  publicLimitations,
  resolveOutcomeCard,
} from "./errorCards";
import type { JobResult } from "./types";

describe("error card classification", () => {
  it("maps the live endurance-no-recharge capture to a business-refusal card", () => {
    const result = {
      ...enduranceFixture,
      state: "completed",
      mission_plan: null,
      artifacts: [],
    } as JobResult;
    const card = resolveOutcomeCard(result);
    expect(inferErrorCode(result)).toBe("INFEASIBLE_ENDURANCE_NO_RECHARGE");
    expect(card?.title).toBe("Не хватает ресурса одного вылета");
    expect(card?.tone).toBe("infeasible");
    expect(card?.highlight.boards).toBe(true);
    expect(publicLimitations(enduranceFixture.solver_report).join(" ")).not.toMatch(/sitecustomize|iso f2c|f2c_isolated/i);
  });

  it("maps live catalog validation messages to field-highlight cards", () => {
    const uav = resolveOutcomeCard({
      contract_version: "v0",
      job_id: "cat-uav",
      state: "failed",
      error: { outcome: "error", message: catalogFixture.invalid_uav.message },
    });
    expect(uav?.code).toBe("ERROR_UAV_NOT_IN_CATALOG");
    expect(uav?.title).toBe("Модель БВС не найдена в каталоге");
    expect(uav?.highlight.model).toBe(true);

    const camera = resolveOutcomeCard({
      contract_version: "v0",
      job_id: "cat-cam",
      state: "failed",
      error: { outcome: "error", message: catalogFixture.invalid_camera.message },
    });
    expect(camera?.code).toBe("ERROR_CAMERA_NOT_IN_CATALOG");
    expect(camera?.highlight.camera).toBe(true);

    const pair = resolveOutcomeCard({
      contract_version: "v0",
      job_id: "cat-pair",
      state: "failed",
      error: { outcome: "error", message: catalogFixture.incompatible.message },
    });
    expect(pair?.code).toBe("ERROR_CAMERA_UAV_INCOMPATIBLE");
    expect(pair?.highlight.model).toBe(true);
    expect(pair?.highlight.camera).toBe(true);
  });

  it("uses an API error_code when present", () => {
    const card = resolveOutcomeCard({
      contract_version: "v0",
      job_id: "job-1",
      state: "timed_out",
      outcome: "timed_out",
      mission_plan: null,
      solver_report: {},
      artifacts: [],
      error_code: "TIMED_OUT_BUDGET",
    });
    expect(card?.title).toBe("Расчёт прерван по времени");
    expect(card?.highlight.timeLimit).toBe(true);
  });
});
