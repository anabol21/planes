import { describe, expect, it } from "vitest";

import { parseSubmission } from "./api";
import type { KmlFileRecord, KmlSummary } from "./kml";
import {
  DEFAULT_UAVS,
  addUav,
  buildOptimization,
  buildPrototypeScenario,
  removeUav,
  validateScenarioInputs,
  type ScenarioInputs,
} from "./scenario";

const SUMMARY: KmlSummary = {
  document_count: 1,
  document_names: ["Demo"],
  document_descriptions: [],
  placemark_count: 2,
  placemark_name_samples: ["Area 1"],
  placemark_description_samples: [],
  geometry_counts: { Polygon: 2 },
  coordinate_tuple_count: 10,
  altitude_coordinate_count: 0,
  nonzero_altitude_coordinate_count: 0,
  altitude_modes: { clampToGround: 2 },
  extended_data_fields: [],
  bounds: {
    west_lon_deg: 30.1,
    south_lat_deg: 59.1,
    east_lon_deg: 30.2,
    north_lat_deg: 59.2,
    min_altitude_m: null,
    max_altitude_m: null,
  },
};

function kml(id: string, category: KmlFileRecord["category"]): KmlFileRecord {
  return {
    id,
    category,
    file_name: `${id}.kml`,
    size_bytes: 2048,
    status: "ready",
    summary: SUMMARY,
    sha256: "abc123",
    raw_text: "<kml />",
    error: null,
  };
}

function inputs(): ScenarioInputs {
  return {
    scenarioId: "demo-multi-uav-001",
    uavs: DEFAULT_UAVS.map((uav) => ({ ...uav })),
    surveyType: "RGB",
    windSpeedMps: 3,
    windDirectionFromDeg: 270,
    surveyTask: kml("survey", "survey_task"),
    restrictedZones: kml("restricted", "restricted_zones"),
    obstacles: [kml("obstacle-a", "obstacle"), kml("obstacle-b", "obstacle")],
  };
}

describe("prototype fleet", () => {
  it("adds a UAV with a stable unique local ID", () => {
    const expanded = addUav(DEFAULT_UAVS);
    expect(expanded.map((uav) => uav.uav_id)).toEqual(["uav-01", "uav-02", "uav-03"]);
  });

  it("removes one UAV while retaining at least one", () => {
    expect(removeUav(DEFAULT_UAVS, "uav-01").map((uav) => uav.uav_id)).toEqual(["uav-02"]);
    expect(removeUav([DEFAULT_UAVS[0]], "uav-01")).toHaveLength(1);
  });
});

describe("prototype scenario", () => {
  it("constructs a scenario with an explicit UAV array", () => {
    const scenario = buildPrototypeScenario(inputs());
    expect(scenario.uavs).toHaveLength(2);
    expect(scenario).toMatchObject({
      scenario_profile: "team_assumption_multi_uav_kml_v0",
      semantic_validation_performed: false,
    });
  });

  it("keeps multiple obstacle files and KML-derived summaries", () => {
    const scenario = buildPrototypeScenario(inputs());
    expect(scenario.obstacles).toHaveLength(2);
    expect(scenario.survey).toMatchObject({
      task_geometry: {
        file_name: "survey.kml",
        sha256: "abc123",
        summary: { placemark_count: 2, geometry_counts: { Polygon: 2 } },
      },
    });
  });

  it("serializes both supported objectives consistently", () => {
    expect(buildOptimization("min_time", 30)).toEqual({
      objective: "min_time",
      time_limit_seconds: 30,
    });
    expect(buildOptimization("min_total_flight_time", 45)).toEqual({
      objective: "min_total_flight_time",
      time_limit_seconds: 45,
    });
  });

  it("places the UAV array and KML-derived data in the existing backend envelope", () => {
    const scenario = buildPrototypeScenario(inputs());
    const request = parseSubmission(
      JSON.stringify(scenario),
      JSON.stringify(buildOptimization("min_time", 30)),
      "7",
    );
    expect(request.contract_version).toBe("v0");
    expect(request.scenario.uavs).toHaveLength(2);
    expect(request.scenario.obstacles).toHaveLength(2);
  });

  it("rejects missing required survey KML", () => {
    const invalid = { ...inputs(), surveyTask: null };
    expect(() => validateScenarioInputs(invalid)).toThrow("Загрузите корректный KML");
  });

  it("rejects duplicate UAV IDs and invalid required fleet data", () => {
    const invalid = inputs();
    invalid.uavs[1] = { ...invalid.uavs[1], uav_id: "uav-01" };
    expect(() => validateScenarioInputs(invalid)).toThrow("ID должен быть заполнен и уникален");
  });
});
