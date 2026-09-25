import type { JsonObject } from "./types";
import {
  extractKmlPolygons,
  ringBounds,
  ringIntersectsBounds,
  type KmlFileRecord,
  type KmlPolygonRing,
  type XmlParser,
} from "./kml";

export type SurveyType = "RGB" | "multispectral" | "infrared" | "LiDAR" | "geophysical";

export interface PadInput {
  id: string;
  lat: number;
  lon: number;
  count: number;
}

export interface ScenarioInputs {
  scenarioId: string;
  pads: PadInput[];
  surveyType: SurveyType;
  windSpeedMps: number;
  windDirectionFromDeg: number | null;
  surveyTask: KmlFileRecord | null;
  restrictedZones: KmlFileRecord | null;
  obstacles: KmlFileRecord[];
}

export const DEFAULT_PADS: PadInput[] = [
  {
    id: "pad-01",
    lon: 37.6,
    lat: 55.747,
    count: 1,
  },
];

function nextPadId(pads: PadInput[]): string {
  const used = new Set(pads.map((pad) => pad.id));
  let index = pads.length + 1;
  while (used.has(`pad-${String(index).padStart(2, "0")}`)) index += 1;
  return `pad-${String(index).padStart(2, "0")}`;
}

export function addPad(pads: PadInput[]): PadInput[] {
  const template = pads.at(-1) ?? DEFAULT_PADS[0];
  return [...pads, { ...template, id: nextPadId(pads) }];
}

export function removePad(pads: PadInput[], padId: string): PadInput[] {
  return pads.length <= 1 ? pads : pads.filter((pad) => pad.id !== padId);
}

function requireFinite(value: number, label: string, minimum?: number): void {
  if (!Number.isFinite(value) || (minimum !== undefined && value < minimum)) {
    throw new Error(`${label}: укажите корректное числовое значение.`);
  }
}

function validatePoint(lon: number, lat: number, label: string): void {
  requireFinite(lon, `${label}, долгота`);
  requireFinite(lat, `${label}, широта`);
  if (lon < -180 || lon > 180 || lat < -90 || lat > 90) {
    throw new Error(`${label}: координаты должны быть в диапазонах долготы/широты.`);
  }
}

export function validateScenarioInputs(inputs: ScenarioInputs): void {
  if (!inputs.scenarioId.trim()) throw new Error("Укажите идентификатор сценария.");
  if (!inputs.surveyTask || inputs.surveyTask.status !== "ready") {
    throw new Error("Загрузите корректный KML с границами задания на съёмку.");
  }
  if (inputs.restrictedZones?.status === "error" || inputs.obstacles.some((file) => file.status === "error")) {
    throw new Error("Исправьте ошибки чтения KML перед запуском.");
  }
  if (!inputs.pads.length) throw new Error("Добавьте хотя бы одну площадку.");
  if (inputs.pads.length > 4) throw new Error("Не больше 4 площадок.");
  const ids = new Set<string>();
  for (const [index, pad] of inputs.pads.entries()) {
    const label = `Площадка ${index + 1}`;
    if (!pad.id.trim() || ids.has(pad.id)) throw new Error(`${label}: ID должен быть заполнен и уникален.`);
    ids.add(pad.id);
    validatePoint(pad.lon, pad.lat, label);
    if (!Number.isInteger(pad.count) || pad.count < 1) {
      throw new Error(`${label}: укажите число бортов не меньше 1.`);
    }
  }
  requireFinite(inputs.windSpeedMps, "Скорость ветра", 0);
  if (inputs.windDirectionFromDeg === null) {
    throw new Error("Укажите направление ветра от 0 до 360 градусов.");
  }
  requireFinite(inputs.windDirectionFromDeg, "Направление ветра");
  if (inputs.windDirectionFromDeg < 0 || inputs.windDirectionFromDeg > 360) {
    throw new Error("Направление ветра должно быть от 0 до 360 градусов.");
  }
}

export const DEFAULT_PROFILE_SOURCE =
  "src/planes/model/basic_model/gibrid-optimizer/data/input.json";

export const DEFAULT_PROFILE_NOTE =
  "gsd_cm_per_px, survey overlaps and strip direction, and power_coeffs are the default profile from src/planes/model/basic_model/gibrid-optimizer/data/input.json, not user input.";

const DEFAULT_GSD_CM_PER_PX = 3.0;
const DEFAULT_SURVEY = {
  forward_overlap: 0.7,
  side_overlap: 0.6,
  strip_direction_deg: 0.0,
};
const DEFAULT_POWER_COEFFS = { kh: 90.0, kv: 0.02, kw: 0.008 };

export function solverCriterion(objective: string): "min_time" | "min_flight_hours" {
  if (objective === "min_time") return "min_time";
  if (objective === "min_total_flight_time") return "min_flight_hours";
  throw new Error("Выберите критерий оптимизации.");
}

export function withDefaultProfileLimitation(limitations: readonly string[]): string[] {
  if (limitations.includes(DEFAULT_PROFILE_NOTE)) return [...limitations];
  return [...limitations, DEFAULT_PROFILE_NOTE];
}

function extendedValue(data: Record<string, string>, key: string): string | null {
  if (data[key]) return data[key];
  const match = Object.entries(data).find(([name]) => name.toLowerCase() === key.toLowerCase());
  return match?.[1] ?? null;
}

function polygonLabel(polygon: KmlPolygonRing, index: number): string {
  const name = polygon.name?.trim() || `polygon ${index + 1}`;
  const lon = polygon.ring[0]?.[0];
  const lat = polygon.ring[0]?.[1];
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return name;
  return `${name} (${lon}, ${lat})`;
}

function polygonsOf(file: KmlFileRecord | null, parser?: XmlParser): KmlPolygonRing[] {
  if (!file || file.status !== "ready" || !file.raw_text) return [];
  return extractKmlPolygons(file.raw_text, parser);
}

function surveyRing(file: KmlFileRecord, parser?: XmlParser): number[][] {
  if (!file.raw_text) throw new Error("В KML задания нет полигона съёмки.");
  const polygons = extractKmlPolygons(file.raw_text, parser);
  if (polygons.length === 0) throw new Error("В KML задания нет полигона съёмки.");
  if (polygons.length > 1) {
    const listed = polygons.map(polygonLabel).join("; ");
    throw new Error(`В KML задания несколько полигонов: ${listed}. Нужен один полигон съёмки.`);
  }
  return polygons[0].ring;
}

function windDirectionDeg(value: number | null): number {
  if (value === null || !Number.isFinite(value) || value < 0 || value > 360) {
    throw new Error("Укажите направление ветра от 0 до 360 градусов.");
  }
  return value === 360 ? 0 : value;
}

export function buildPrototypeScenario(
  inputs: ScenarioInputs,
  objective = "min_time",
  parser?: XmlParser,
): JsonObject {
  if (!inputs.surveyTask || inputs.surveyTask.status !== "ready") {
    throw new Error("Загрузите корректный KML с границами задания на съёмку.");
  }
  if (!inputs.pads.length) throw new Error("Добавьте хотя бы одну площадку.");
  if (inputs.pads.length > 4) throw new Error("Не больше 4 площадок.");
  const area = surveyRing(inputs.surveyTask, parser);
  const bounds = ringBounds(area);
  if (!bounds) throw new Error("В KML задания нет полигона съёмки.");
  const zoneConstraints = polygonsOf(inputs.restrictedZones, parser).map((polygon) => ({
    ring: polygon.ring,
    name: extendedValue(polygon.extended_data, "Name") ?? polygon.name,
    type: extendedValue(polygon.extended_data, "Type"),
    altitudes_text: extendedValue(polygon.extended_data, "Altitudes"),
  }));
  const obstacles = inputs.obstacles.flatMap((file) =>
    polygonsOf(file, parser).flatMap((polygon) => {
      if (!ringIntersectsBounds(polygon.ring, bounds)) return [];
      return [
        {
          ring: polygon.ring,
          height_m: polygon.height_m,
          kind: polygon.name,
        },
      ];
    }),
  );
  return {
    scenario_id: inputs.scenarioId.trim(),
    crs: "EPSG:4326",
    criterion: solverCriterion(objective),
    gsd_cm_per_px: DEFAULT_GSD_CM_PER_PX,
    area,
    required_spectrum: inputs.surveyType,
    pads: inputs.pads.map((pad) => ({
      id: pad.id,
      lat: pad.lat,
      lon: pad.lon,
      count: pad.count,
    })),
    survey: DEFAULT_SURVEY,
    survey_type: inputs.surveyType,
    wind: {
      speed_ms: inputs.windSpeedMps,
      direction_deg: windDirectionDeg(inputs.windDirectionFromDeg),
    },
    power_coeffs: DEFAULT_POWER_COEFFS,
    zone_constraints: zoneConstraints,
    obstacles,
    default_profile: {
      note: DEFAULT_PROFILE_NOTE,
      source: DEFAULT_PROFILE_SOURCE,
    },
    prototype_limitations: [
      "KML rings are extracted in the browser. Source files stay local and are not uploaded.",
      "Altitude sentences in zone constraints are copied as text and are not parsed.",
      "Obstacles are limited to footprints that intersect the survey bounding box.",
      "Each pad supplies latitude, longitude, and a count of identical aircraft. The server pairs that pad with catalog UAV and camera rows whose spectra contain required_spectrum.",
      DEFAULT_PROFILE_NOTE,
    ],
  };
}

export const DEFAULT_TIME_LIMIT = "90";
// 120 s client wait, minus 5 s wrapper slack, minus 2 s listener buffer, is 113.
// 110 is the max the form shows and accepts.
export const MAX_TIME_LIMIT_SECONDS = 110;

export function buildOptimization(objective: string, timeLimitSeconds: number): JsonObject {
  if (!objective.trim()) throw new Error("Выберите критерий оптимизации.");
  if (!Number.isFinite(timeLimitSeconds) || timeLimitSeconds < 0) {
    throw new Error("Лимит расчёта должен быть неотрицательным числом секунд.");
  }
  if (timeLimitSeconds > MAX_TIME_LIMIT_SECONDS) {
    throw new Error(`Лимит расчёта не больше ${MAX_TIME_LIMIT_SECONDS} секунд.`);
  }
  return { objective, time_limit_seconds: timeLimitSeconds };
}
