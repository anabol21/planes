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

export interface FleetUav {
  uav_id: string;
  model: string;
  payload_model: string;
  cruise_speed_m_s: number;
  battery_capacity_wh: number;
  max_flight_time_s: number;
  launch_lon_deg: number;
  launch_lat_deg: number;
  landing_lon_deg: number;
  landing_lat_deg: number;
}

export interface ScenarioInputs {
  scenarioId: string;
  uavs: FleetUav[];
  surveyType: SurveyType;
  windSpeedMps: number;
  windDirectionFromDeg: number | null;
  surveyTask: KmlFileRecord | null;
  restrictedZones: KmlFileRecord | null;
  obstacles: KmlFileRecord[];
}

export const DEFAULT_UAVS: FleetUav[] = [
  {
    uav_id: "uav-01",
    model: "Geoscan Gemini",
    payload_model: "Sony UMC-R10C",
    cruise_speed_m_s: 15,
    battery_capacity_wh: 144.7,
    max_flight_time_s: 2400,
    launch_lon_deg: 30.31,
    launch_lat_deg: 59.94,
    landing_lon_deg: 30.31,
    landing_lat_deg: 59.94,
  },
  {
    uav_id: "uav-02",
    model: "Geoscan Gemini",
    payload_model: "Sony UMC-R10C",
    cruise_speed_m_s: 15,
    battery_capacity_wh: 144.7,
    max_flight_time_s: 2400,
    launch_lon_deg: 30.312,
    launch_lat_deg: 59.941,
    landing_lon_deg: 30.312,
    landing_lat_deg: 59.941,
  },
];

function nextUavId(uavs: FleetUav[]): string {
  const used = new Set(uavs.map((uav) => uav.uav_id));
  let index = uavs.length + 1;
  while (used.has(`uav-${String(index).padStart(2, "0")}`)) index += 1;
  return `uav-${String(index).padStart(2, "0")}`;
}

export function addUav(uavs: FleetUav[]): FleetUav[] {
  const template = uavs.at(-1) ?? DEFAULT_UAVS[0];
  return [...uavs, { ...template, uav_id: nextUavId(uavs) }];
}

export function removeUav(uavs: FleetUav[], uavId: string): FleetUav[] {
  return uavs.length <= 1 ? uavs : uavs.filter((uav) => uav.uav_id !== uavId);
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
  if (!inputs.uavs.length) throw new Error("Добавьте хотя бы один БВС.");
  const ids = new Set<string>();
  for (const [index, uav] of inputs.uavs.entries()) {
    const label = `БВС ${index + 1}`;
    if (!uav.uav_id.trim() || ids.has(uav.uav_id)) throw new Error(`${label}: ID должен быть заполнен и уникален.`);
    ids.add(uav.uav_id);
    if (!uav.model.trim()) throw new Error(`${label}: укажите модель.`);
    if (!uav.payload_model.trim()) throw new Error(`${label}: укажите полезную нагрузку.`);
    requireFinite(uav.cruise_speed_m_s, `${label}, крейсерская скорость`, 0.01);
    requireFinite(uav.battery_capacity_wh, `${label}, ёмкость батареи`, 0.01);
    requireFinite(uav.max_flight_time_s, `${label}, максимальное время полёта`, 0.01);
    validatePoint(uav.launch_lon_deg, uav.launch_lat_deg, `${label}, точка старта`);
    validatePoint(uav.landing_lon_deg, uav.landing_lat_deg, `${label}, точка посадки`);
  }
  if (inputs.uavs.length > 4) throw new Error("Не больше 4 типов БВС.");
  if (launchPads(inputs.uavs).length > 4) throw new Error("Не больше 4 площадок.");
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
  "gsd_cm_per_px, camera, survey overlaps and strip direction, power_coeffs, mass_kg, v_vertical_ms, and max_wind_ms are the default profile from src/planes/model/basic_model/gibrid-optimizer/data/input.json, not user input.";

const DEFAULT_GSD_CM_PER_PX = 3.0;
const DEFAULT_CAMERA = {
  sensor_width_mm: 23.5,
  sensor_height_mm: 15.6,
  focal_length_mm: 20.0,
  image_width_px: 6000,
  image_height_px: 4000,
};
const DEFAULT_SURVEY = {
  forward_overlap: 0.7,
  side_overlap: 0.6,
  strip_direction_deg: 0.0,
};
const DEFAULT_POWER_COEFFS = { kh: 90.0, kv: 0.02, kw: 0.008 };
const DEFAULT_MASS_KG = 2.0;
const DEFAULT_V_VERTICAL_MS = 5.0;
const DEFAULT_MAX_WIND_MS = 10.0;
// Prototype cards carry the default RGB camera. The survey type is the
// spectrum the zone requires, and it is not copied onto the card.
const PROTOTYPE_CARD_SPECTRUM = "RGB";

function launchPads(uavs: FleetUav[]): FleetUav[][] {
  const groups: FleetUav[][] = [];
  const index = new Map<string, number>();
  for (const uav of uavs) {
    const key = `${uav.launch_lat_deg}\u0000${uav.launch_lon_deg}`;
    const slot = index.get(key);
    if (slot === undefined) {
      index.set(key, groups.length);
      groups.push([uav]);
    } else {
      groups[slot].push(uav);
    }
  }
  return groups;
}

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
  if (!inputs.uavs.length) throw new Error("Добавьте хотя бы один БВС.");
  if (inputs.uavs.length > 4) throw new Error("Не больше 4 типов БВС.");
  const pads = launchPads(inputs.uavs);
  if (pads.length > 4) throw new Error("Не больше 4 площадок.");
  const area = surveyRing(inputs.surveyTask, parser);
  const bounds = ringBounds(area);
  if (!bounds) throw new Error("В KML задания нет полигона съёмки.");
  const lead = inputs.uavs[0];
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
    required_camera: lead.payload_model,
    required_spectrum: inputs.surveyType,
    uav_types: inputs.uavs.map((uav) => ({
      id: uav.uav_id,
      camera: { name: uav.payload_model, ...DEFAULT_CAMERA },
      spectra: [PROTOTYPE_CARD_SPECTRUM],
      model: uav.model,
      mass_kg: DEFAULT_MASS_KG,
      max_flight_time_s: uav.max_flight_time_s,
      battery_wh: uav.battery_capacity_wh,
      v_air_ms: uav.cruise_speed_m_s,
      v_vertical_ms: DEFAULT_V_VERTICAL_MS,
      max_wind_ms: DEFAULT_MAX_WIND_MS,
    })),
    pads: pads.map((group, index) => ({
      id: `pad-${String(index + 1).padStart(2, "0")}`,
      lat: group[0].launch_lat_deg,
      lon: group[0].launch_lon_deg,
      types: group.map((uav) => ({ id: uav.uav_id, count: 1 })),
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
      "Each card is one UAV type with count 1 on a pad at its launch point. A card is admitted only when its payload matches required_camera and its spectrum matches required_spectrum.",
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
