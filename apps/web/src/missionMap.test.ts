import { describe, expect, it } from "vitest";

import fixture from "./test-fixtures/mission-result-v0.json";
import { buildMissionMapData, missionPlanToGeoJson } from "./missionMapData";
import type { MissionPlan } from "./types";

const plan = fixture.mission_plan as MissionPlan;

describe("missionPlanToGeoJson", () => {
  it("keeps one route as one LineString with exact waypoint order", () => {
    const oneRoute: MissionPlan = { routes: [plan.routes![0]] };
    const result = missionPlanToGeoJson(oneRoute);

    expect(result.features).toHaveLength(1);
    expect(result.features[0].geometry).toEqual({
      type: "LineString",
      coordinates: [
        [37.604, 55.748],
        [37.607, 55.75],
        [37.604, 55.748],
      ],
    });
  });

  it("uses GeoJSON longitude-latitude order", () => {
    const result = missionPlanToGeoJson({
      routes: [{
        uav_id: "UAV",
        flight_index: 0,
        vpp_id: "VPP",
        waypoints: [
          { lat: 55.75, lon: 37.6, alt_m: 100 },
          { lat: 55.76, lon: 37.61, alt_m: 110 },
        ],
      }],
    });

    expect(result.features[0].geometry.coordinates[0]).toEqual([37.6, 55.75]);
  });

  it("creates separate features for multiple UAVs and flights", () => {
    const result = missionPlanToGeoJson(plan);

    expect(result.features).toHaveLength(3);
    expect(result.features.map((feature) => [
      feature.properties.uav_id,
      feature.properties.flight_index,
    ])).toEqual([
      ["БВС 1", 0],
      ["БВС 1", 1],
      ["БВС 2", 0],
    ]);
    expect(result.features[0].properties.color).toBe(result.features[1].properties.color);
    expect(result.features[0].properties.color).not.toBe(result.features[2].properties.color);
  });

  it("returns an empty collection for empty routes", () => {
    expect(missionPlanToGeoJson({ routes: [] })).toEqual({
      type: "FeatureCollection",
      features: [],
    });
  });

  it("preserves consecutive duplicate XY waypoints", () => {
    const result = missionPlanToGeoJson({
      routes: [{
        uav_id: "UAV",
        flight_index: 0,
        vpp_id: "VPP",
        waypoints: [
          { lat: 55.75, lon: 37.6, alt_m: 100 },
          { lat: 55.75, lon: 37.6, alt_m: 150 },
          { lat: 55.76, lon: 37.61, alt_m: 150 },
        ],
      }],
    });

    expect(result.features[0].geometry.coordinates).toEqual([
      [37.6, 55.75],
      [37.6, 55.75],
      [37.61, 55.76],
    ]);
  });

  it("includes confirmed area, obstacle, constraint, base, and bounds data", () => {
    const result = buildMissionMapData(plan);

    expect(result.areas.features).toHaveLength(1);
    expect(result.obstacles.features).toHaveLength(1);
    expect(result.constraints.features).toHaveLength(1);
    expect(result.bases).toHaveLength(2);
    expect(result.bounds).toEqual([[37.6, 55.748], [37.61, 55.754]]);
  });
});
