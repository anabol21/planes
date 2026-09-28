import { DOMParser } from "@xmldom/xmldom";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { createApiClient, submitFromEditors } from "./api";
import { extractKmlPolygons, readKmlFile } from "./kml";
import { buildOptimization, buildPrototypeScenario, validateScenarioInputs, type ScenarioInputs } from "./scenario";

function ringKml(coordinates: string): string {
  return `<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>
<Polygon><outerBoundaryIs><LinearRing><coordinates>${coordinates}</coordinates>
</LinearRing></outerBoundaryIs></Polygon></Placemark></Document></kml>`;
}

const POINT_COUNT = 225_000;
const CORNERS = ["37,55", "38,55", "38,56", "37,56"];
// Generate one closed outer ring; its maximum altitude occurs at the last point.
const LARGE_KML = ringKml(Array.from({ length: POINT_COUNT }, (_, index) => {
  if (index === POINT_COUNT - 1) return `${CORNERS[0]},125`;
  const corner = Math.min(3, Math.floor(index / ((POINT_COUNT - 1) / 4)));
  return `${CORNERS[corner]},${index % 3 - 1}`;
}).join(" "));

describe("FE-001 altitude ring regression", () => {
  beforeAll(() => vi.stubGlobal("DOMParser", DOMParser));
  afterAll(() => vi.unstubAllGlobals());

  it.each([
    ["ordinary small ring", "37,55,12 38,55,48 38,56,24 37,55,12", 48],
    ["absent altitude", "37,55 38,55 38,56 37,55", null],
    ["mixed positive, zero and negative", "37,55,-10 38,55,0 38,56,7 37,55,-10", 7],
    ["negative only", "37,55,-30 38,55,-5 38,56,-10 37,55,-30", -5],
    ["invalid altitude only", "37,55,NaN 38,55,Infinity 38,56,-Infinity 37,55,", null],
    ["invalid and finite altitude", "37,55,NaN 38,55,-2 38,56,Infinity 37,55,", -2],
    ["signed zeros", "37,55,-0 38,55,0 38,56,-0 37,55,-0", 0],
    ["negative zero only", "37,55,-0 38,55,-0 38,56,-0 37,55,-0", -0],
  ])("preserves %s semantics", (_label, coordinates, height) => {
    const polygons = extractKmlPolygons(ringKml(coordinates));
    expect(polygons).toHaveLength(1);
    expect(polygons[0].ring).toEqual([[37, 55], [38, 55], [38, 56], [37, 55]]);
    expect(polygons[0].height_m).toBe(height);
  });

  it("extracts 225,000 altitude points without RangeError or truncation", () => {
    const polygons = extractKmlPolygons(LARGE_KML);
    expect(polygons).toHaveLength(1);
    expect(polygons[0].ring).toHaveLength(POINT_COUNT);
    expect(polygons[0].ring[0]).toEqual([37, 55]);
    expect(polygons[0].ring.at(-1)).toEqual([37, 55]);
    expect(polygons[0].height_m).toBe(125);
  }, 10_000);

  it("uploads, previews and submits the large raw KML through production fetch", async () => {
    const record = await readKmlFile(new File([LARGE_KML], "large.kml"), "survey_task", "large");
    expect(record.status).toBe("ready");
    expect(record.error).toBeNull();
    expect(record.summary?.coordinate_tuple_count).toBe(POINT_COUNT);
    expect(record.summary?.altitude_coordinate_count).toBe(POINT_COUNT);
    expect(record.sha256).toMatch(/^[a-f0-9]{64}$/);
    const inputs: ScenarioInputs = {
      scenarioId: "fe001-large",
      surveyTask: record,
      restrictedZones: null,
      aerodromes: [{ lon: 37.6, lat: 55.747 }],
      boards: [{ modelId: "geoscan-gemini", cameraId: "geoscan-pf1b", aerodromeIndex: 0, count: 1 }],
      surveyType: "RGB",
      gsdCmPerPx: 2,
      forwardOverlap: 0.6,
      sideOverlap: 0.5,
      stripDirectionDeg: 0,
      windSpeedMps: 1,
      windDirectionFromDeg: 90,
    };
    const preview = JSON.stringify(buildPrototypeScenario(inputs), null, 2);
    expect(JSON.parse(preview).survey_kml).toBe(LARGE_KML);
    validateScenarioInputs(inputs);
    const scenario = buildPrototypeScenario(inputs);
    const queued = {
      contract_version: "v0", job_id: "fe001-job", state: "queued",
      created_at: null, started_at: null, finished_at: null,
    };
    const fetchSpy = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(queued), {
      status: 202, headers: { "Content-Type": "application/json" },
    }));
    const api = createApiClient(fetchSpy);
    const submitSpy = vi.spyOn(api, "submitJob");
    const result = await submitFromEditors(api, JSON.stringify(scenario), JSON.stringify(buildOptimization("min_time", 60)), "42");
    expect(result).toEqual(queued);
    expect(submitSpy).toHaveBeenCalledOnce();
    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("/api/jobs");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toMatchObject({
      contract_version: "v0", scenario: { survey_kml: LARGE_KML, constraints_kml: "" }, seed: 42,
    });
  }, 10_000);
});
