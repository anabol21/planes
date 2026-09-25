import { DOMParser } from "@xmldom/xmldom";
import { describe, expect, it } from "vitest";

import { parseSubmission } from "./api";
import type { KmlFileRecord, KmlSummary, XmlParser } from "./kml";
import {
  DEFAULT_PADS,
  DEFAULT_PROFILE_NOTE,
  DEFAULT_TIME_LIMIT,
  MAX_TIME_LIMIT_SECONDS,
  addPad,
  buildOptimization,
  buildPrototypeScenario,
  removePad,
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
    pads: DEFAULT_PADS.map((pad) => ({ ...pad })),
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

describe("prototype pads", () => {
  it("adds a pad with a stable unique id", () => {
    const expanded = addPad(DEFAULT_PADS);
    expect(expanded.map((pad) => pad.id)).toEqual(["pad-01", "pad-02"]);
    expect(expanded[1]).toMatchObject({ lon: 37.6, lat: 55.747, count: 1 });
  });

  it("removes one pad while retaining at least one", () => {
    const two = addPad(DEFAULT_PADS);
    expect(removePad(two, "pad-01").map((pad) => pad.id)).toEqual(["pad-02"]);
    expect(removePad([DEFAULT_PADS[0]], "pad-01")).toHaveLength(1);
  });
});

describe("prototype scenario", () => {
  it("sends pads with count and the survey spectrum", () => {
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
      required_spectrum: "RGB",
      survey: { forward_overlap: 0.7, side_overlap: 0.6, strip_direction_deg: 0 },
      wind: { speed_ms: 3, direction_deg: 270 },
      power_coeffs: { kh: 90, kv: 0.02, kw: 0.008 },
    });
    const built = scenario();
    expect(built).not.toHaveProperty("uav");
    expect(built).not.toHaveProperty("takeoff");
    expect(built).not.toHaveProperty("required_camera");
    expect(built).not.toHaveProperty("uav_types");
    expect(built.pads).toEqual([
      {
        id: "pad-01",
        lat: 55.747,
        lon: 37.6,
        count: 1,
      },
    ]);
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
    expect(DEFAULT_TIME_LIMIT).toBe("90");
    expect(buildOptimization("min_time", Number(DEFAULT_TIME_LIMIT))).toEqual({
      objective: "min_time",
      time_limit_seconds: 90,
    });
    expect(buildOptimization("min_total_flight_time", 45)).toEqual({
      objective: "min_total_flight_time",
      time_limit_seconds: 45,
    });
    expect(buildOptimization("min_time", MAX_TIME_LIMIT_SECONDS)).toEqual({
      objective: "min_time",
      time_limit_seconds: 110,
    });
    expect(() => buildOptimization("min_time", MAX_TIME_LIMIT_SECONDS + 1)).toThrow(
      "Лимит расчёта не больше 110 секунд.",
    );
  });

  it("places solver fields and KML rings in the existing backend envelope", () => {
    const built = scenario();
    const request = parseSubmission(
      JSON.stringify(built),
      JSON.stringify(buildOptimization("min_time", 30)),
      "7",
    );
    expect(request.contract_version).toBe("v0");
    expect(request.scenario.uav).toBeUndefined();
    expect(request.scenario.pads).toHaveLength(1);
    expect(request.scenario.uav_types).toBeUndefined();
    expect(request.scenario.required_camera).toBeUndefined();
    expect(request.scenario.area).toHaveLength(5);
    expect(request.scenario.obstacles).toHaveLength(2);
    expect(request.scenario.zone_constraints).toHaveLength(1);
  });

  it("rejects missing required survey KML", () => {
    const invalid = { ...inputs(), surveyTask: null };
    expect(() => validateScenarioInputs(invalid)).toThrow("Загрузите корректный KML");
  });

  it("rejects duplicate pad IDs", () => {
    const invalid = inputs();
    invalid.pads = addPad(invalid.pads);
    invalid.pads[1] = { ...invalid.pads[1], id: "pad-01" };
    expect(() => validateScenarioInputs(invalid)).toThrow("ID должен быть заполнен и уникален");
  });
});

describe("enumeration input", () => {
  it("defaults a pad to lon 37.6, lat 55.747, and count 1", () => {
    expect(DEFAULT_PADS).toEqual([{ id: "pad-01", lon: 37.6, lat: 55.747, count: 1 }]);
  });

  it("emits pads and required_spectrum so solver.solve takes the enumeration path", () => {
    const built = scenario();
    expect(built.pads).toEqual([{ id: "pad-01", lat: 55.747, lon: 37.6, count: 1 }]);
    expect(built.required_spectrum).toBe("RGB");
    expect(built).not.toHaveProperty("takeoff");
    expect(built).not.toHaveProperty("uav");
    expect(built).not.toHaveProperty("uav_types");
    expect(built).not.toHaveProperty("required_camera");
  });

  it("sets required_spectrum from the survey type and does not stamp RGB on the pad", () => {
    const built = scenario();
    expect(built.required_spectrum).toBe("RGB");
    expect(built.pads).toEqual([{ id: "pad-01", lat: 55.747, lon: 37.6, count: 1 }]);
    expect(JSON.stringify(built.pads)).not.toContain("RGB");
  });

  it("keeps two pads in the order the user entered, each with its own count", () => {
    const two = inputs();
    two.pads = [
      { id: "pad-01", lat: 55.747, lon: 37.6, count: 2 },
      { id: "pad-02", lat: 55.75, lon: 37.61, count: 1 },
    ];
    const built = buildPrototypeScenario(two, "min_time", xmlParser());
    expect(built.pads).toEqual([
      { id: "pad-01", lat: 55.747, lon: 37.6, count: 2 },
      { id: "pad-02", lat: 55.75, lon: 37.61, count: 1 },
    ]);
    expect(built).not.toHaveProperty("uav_types");
    expect(built).not.toHaveProperty("required_camera");
  });

  it("sends a non-RGB survey as required_spectrum without a camera or type list", () => {
    const infrared = inputs();
    infrared.surveyType = "infrared";
    const built = buildPrototypeScenario(infrared, "min_time", xmlParser());
    expect(built.required_spectrum).toBe("infrared");
    expect(built).not.toHaveProperty("required_camera");
    expect(built).not.toHaveProperty("uav_types");
    expect(built.pads).toHaveLength(1);
  });
});
