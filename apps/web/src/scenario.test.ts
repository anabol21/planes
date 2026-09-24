import { DOMParser } from "@xmldom/xmldom";
import { describe, expect, it } from "vitest";

import { parseSubmission } from "./api";
import type { KmlFileRecord, KmlSummary, XmlParser } from "./kml";
import {
  DEFAULT_PROFILE_NOTE,
  DEFAULT_UAVS,
  addUav,
  buildOptimization,
  buildPrototypeScenario,
  removeUav,
  validateScenarioInputs,
  withDefaultProfileLimitation,
  type ScenarioInputs,
} from "./scenario";

function xmlParser(): XmlParser {
  const errors: string[] = [];
  const parser = new DOMParser({
    onError(level, message) {
      if (level !== "warning") errors.push(message);
    },
  });
  return {
    parseFromString(source, mimeType) {
      errors.length = 0;
      let document;
      try {
        document = parser.parseFromString(source, mimeType);
      } catch {
        throw new Error("KML contains malformed XML.");
      }
      if (errors.length) throw new Error("KML contains malformed XML.");
      return document as unknown as Document;
    },
  };
}

const SURVEY_KML = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>survey</name>
<Polygon><outerBoundaryIs><LinearRing><coordinates>
37.601,55.7480,0 37.609,55.7480,0 37.609,55.7525,0 37.601,55.7525,0 37.601,55.7480,0
</coordinates></LinearRing></outerBoundaryIs></Polygon>
</Placemark></Document></kml>`;

const ZONE_KML = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>placemark</name>
<ExtendedData>
  <Data name="Name"><value>Сектор А</value></Data>
  <Data name="Type"><value>врем_ограничение</value></Data>
  <Data name="Altitudes"><value>от 800 м AMSL до FL90</value></Data>
</ExtendedData>
<Polygon><outerBoundaryIs><LinearRing><coordinates>
37.602,55.749,0 37.603,55.749,0 37.603,55.750,0 37.602,55.749,0
</coordinates></LinearRing></outerBoundaryIs></Polygon>
</Placemark></Document></kml>`;

const OBSTACLE_KML = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>BUILDING</name><Polygon><altitudeMode>relativeToGround</altitudeMode>
<outerBoundaryIs><LinearRing><coordinates>
37.602,55.749,48 37.603,55.749,48 37.603,55.750,48 37.602,55.749,48
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>COMMUNICATION_TOWER</name><Polygon><altitudeMode>relativeToGround</altitudeMode>
<outerBoundaryIs><LinearRing><coordinates>
37.0,55.0,80 38.0,55.0,80 38.0,56.0,80 37.0,56.0,80 37.0,55.0,80
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>FAR_BUILDING</name><Polygon><altitudeMode>relativeToGround</altitudeMode>
<outerBoundaryIs><LinearRing><coordinates>
10,10,20 10.1,10,20 10.1,10.1,20 10,10,20
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
</Document></kml>`;

const EMPTY_SURVEY_KML = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>takeoff</name>
<Point><coordinates>37.6,55.747,0</coordinates></Point>
</Placemark></Document></kml>`;

const MULTI_SURVEY_KML = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>North</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
37.601,55.748,0 37.609,55.748,0 37.609,55.7525,0 37.601,55.748,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>South</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
37.601,55.740,0 37.609,55.740,0 37.609,55.745,0 37.601,55.740,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
</Document></kml>`;

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

function kml(
  id: string,
  category: KmlFileRecord["category"],
  rawText: string,
): KmlFileRecord {
  return {
    id,
    category,
    file_name: `${id}.kml`,
    size_bytes: rawText.length,
    status: "ready",
    summary: SUMMARY,
    sha256: "abc123",
    raw_text: rawText,
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
    surveyTask: kml("survey", "survey_task", SURVEY_KML),
    restrictedZones: kml("restricted", "restricted_zones", ZONE_KML),
    obstacles: [kml("obstacle-a", "obstacle", OBSTACLE_KML)],
  };
}

function scenario(objective = "min_time") {
  return buildPrototypeScenario(inputs(), objective, xmlParser());
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
  it("builds an InputData scenario from one survey polygon and the first UAV", () => {
    expect(scenario()).toMatchObject({
      criterion: "min_time",
      crs: "EPSG:4326",
      gsd_cm_per_px: 3,
      area: [
        [37.601, 55.748],
        [37.609, 55.748],
        [37.609, 55.7525],
        [37.601, 55.7525],
        [37.601, 55.748],
      ],
      takeoff: { lat: DEFAULT_UAVS[0].launch_lat_deg, lon: DEFAULT_UAVS[0].launch_lon_deg },
      uav: {
        model: "Geoscan Gemini",
        count: 2,
        mass_kg: 2,
        battery_wh: 144.7,
        max_flight_time_s: 2400,
        v_air_ms: 15,
        v_vertical_ms: 5,
        max_wind_ms: 10,
      },
      camera: { focal_length_mm: 20, image_width_px: 6000 },
      survey: { forward_overlap: 0.7, side_overlap: 0.6, strip_direction_deg: 0 },
      wind: { speed_ms: 3, direction_deg: 270 },
      power_coeffs: { kh: 90, kv: 0.02, kw: 0.008 },
    });
  });

  it("maps the total flight-time form value onto min_flight_hours", () => {
    expect(scenario("min_total_flight_time").criterion).toBe("min_flight_hours");
  });

  it("keeps restriction text and obstacles whose footprint meets the survey bbox", () => {
    const built = scenario();
    expect(built.zone_constraints).toEqual([
      {
        ring: [
          [37.602, 55.749],
          [37.603, 55.749],
          [37.603, 55.75],
          [37.602, 55.749],
        ],
        name: "Сектор А",
        type: "врем_ограничение",
        altitudes_text: "от 800 м AMSL до FL90",
      },
    ]);
    expect(built.obstacles).toEqual([
      {
        ring: [
          [37.602, 55.749],
          [37.603, 55.749],
          [37.603, 55.75],
          [37.602, 55.749],
        ],
        height_m: 48,
        kind: "BUILDING",
      },
      {
        ring: [
          [37, 55],
          [38, 55],
          [38, 56],
          [37, 56],
          [37, 55],
        ],
        height_m: 80,
        kind: "COMMUNICATION_TOWER",
      },
    ]);
    expect(built.default_profile).toMatchObject({ note: DEFAULT_PROFILE_NOTE });
  });

  it("rejects a survey KML without a polygon as an error", () => {
    const invalid = inputs();
    invalid.surveyTask = kml("survey", "survey_task", EMPTY_SURVEY_KML);
    expect(() => buildPrototypeScenario(invalid, "min_time", xmlParser())).toThrow(
      /нет полигона съёмки/,
    );
    expect(() => buildPrototypeScenario(invalid, "min_time", xmlParser())).not.toThrow(/infeasible/i);
  });

  it("lists every survey polygon instead of keeping the first", () => {
    const invalid = inputs();
    invalid.surveyTask = kml("survey", "survey_task", MULTI_SURVEY_KML);
    expect(() => buildPrototypeScenario(invalid, "min_time", xmlParser())).toThrow(/North/);
    expect(() => buildPrototypeScenario(invalid, "min_time", xmlParser())).toThrow(/South/);
  });

  it("shows the default profile next to client-side limitations", () => {
    expect(withDefaultProfileLimitation(["heuristic result is not globally optimal"])).toEqual([
      "heuristic result is not globally optimal",
      DEFAULT_PROFILE_NOTE,
    ]);
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

  it("places solver fields and KML rings in the existing backend envelope", () => {
    const built = scenario();
    const request = parseSubmission(
      JSON.stringify(built),
      JSON.stringify(buildOptimization("min_time", 30)),
      "7",
    );
    expect(request.contract_version).toBe("v0");
    expect(request.scenario.uav).toMatchObject({ count: 2 });
    expect(request.scenario.area).toHaveLength(5);
    expect(request.scenario.obstacles).toHaveLength(2);
    expect(request.scenario.zone_constraints).toHaveLength(1);
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
