import type { JsonObject } from "./types";
import type { KmlFileRecord } from "./kml";

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
  requireFinite(inputs.windSpeedMps, "Скорость ветра", 0);
  if (inputs.windDirectionFromDeg !== null) {
    requireFinite(inputs.windDirectionFromDeg, "Направление ветра");
    if (inputs.windDirectionFromDeg < 0 || inputs.windDirectionFromDeg > 360) {
      throw new Error("Направление ветра должно быть от 0 до 360 градусов.");
    }
  }
}

function serializeKml(file: KmlFileRecord | null): JsonObject | null {
  if (!file || file.status !== "ready" || !file.summary) return null;
  return {
    source_format: "KML",
    file_name: file.file_name,
    size_bytes: file.size_bytes,
    sha256: file.sha256,
    transfer_profile: "structural_summary_only",
    summary: file.summary,
  };
}

export function buildPrototypeScenario(inputs: ScenarioInputs): JsonObject {
  const restricted = serializeKml(inputs.restrictedZones);
  return {
    scenario_id: inputs.scenarioId.trim(),
    crs: "EPSG:4326",
    scenario_profile: "team_assumption_multi_uav_kml_v0",
    semantic_validation_performed: false,
    uavs: inputs.uavs.map((uav) => ({
      uav_id: uav.uav_id,
      model: uav.model,
      payload_model: uav.payload_model,
      cruise_speed_m_s: uav.cruise_speed_m_s,
      battery_capacity_wh: uav.battery_capacity_wh,
      max_flight_time_s: uav.max_flight_time_s,
      launch_point: {
        crs: "EPSG:4326",
        lon_deg: uav.launch_lon_deg,
        lat_deg: uav.launch_lat_deg,
      },
      landing_point: {
        crs: "EPSG:4326",
        lon_deg: uav.landing_lon_deg,
        lat_deg: uav.landing_lat_deg,
      },
    })),
    survey: {
      survey_type: inputs.surveyType,
      task_geometry: serializeKml(inputs.surveyTask),
    },
    restricted_zones: restricted ? [restricted] : [],
    obstacles: inputs.obstacles.map(serializeKml).filter((item): item is JsonObject => item !== null),
    wind: {
      speed_m_s: inputs.windSpeedMps,
      ...(inputs.windDirectionFromDeg === null
        ? {}
        : { direction_from_deg: inputs.windDirectionFromDeg }),
    },
    prototype_limitations: [
      "KML is structurally summarized in the browser; geometry and flight safety are not validated.",
      "Full source files remain browser-local and are identified in this request by SHA-256.",
      "The runtime v0 contract treats scenario contents as opaque JSON.",
    ],
  };
}

export function buildOptimization(objective: string, timeLimitSeconds: number): JsonObject {
  if (!objective.trim()) throw new Error("Выберите критерий оптимизации.");
  if (!Number.isFinite(timeLimitSeconds) || timeLimitSeconds < 0) {
    throw new Error("Лимит расчёта должен быть неотрицательным числом секунд.");
  }
  return { objective, time_limit_seconds: timeLimitSeconds };
}
