import fleetCatalog from "../../../src/planes/runtime/catalog/fleet_catalog.json";

import type { JsonObject } from "./types";
import {
  extractKmlPolygons,
  type KmlFileRecord,
  type XmlParser,
} from "./kml";

export type SurveyType = "RGB" | "multispectral" | "infrared" | "LiDAR" | "geophysical";

export interface CatalogOption {
  id: string;
  name: string;
}

export interface CameraOption extends CatalogOption {
  spectra: readonly string[];
}

export interface AerodromeInput {
  lon: number;
  lat: number;
}

export interface BoardInput {
  modelId: string;
  cameraId: string;
  aerodromeIndex: number | null;
  count: number;
}

export interface ScenarioInputs {
  scenarioId: string;
  aerodromes: AerodromeInput[];
  boards: BoardInput[];
  surveyType: SurveyType;
  gsdCmPerPx: number;
  forwardOverlap: number;
  sideOverlap: number;
  stripDirectionDeg: number;
  windSpeedMps: number;
  windDirectionFromDeg: number | null;
  surveyTask: KmlFileRecord | null;
  restrictedZones: KmlFileRecord | null;
}

export const DEFAULT_AERODROME_LON = 37.6;
export const DEFAULT_AERODROME_LAT = 55.747;
export const DEFAULT_GSD_CM_PER_PX = 3;
export const DEFAULT_FORWARD_OVERLAP = 0.7;
export const DEFAULT_SIDE_OVERLAP = 0.6;
export const DEFAULT_STRIP_DIRECTION_DEG = 0;

export const DEFAULT_AERODROMES: AerodromeInput[] = [
  { lon: DEFAULT_AERODROME_LON, lat: DEFAULT_AERODROME_LAT },
];

export const DEFAULT_BOARDS: BoardInput[] = [
  { modelId: "", cameraId: "", aerodromeIndex: 0, count: 1 },
];

export function aerodromeId(index: number): string {
  return `аэродром ${index + 1}`;
}

export function boardId(index: number): string {
  return `БВС ${index + 1}`;
}

export function catalogModels(): CatalogOption[] {
  return fleetCatalog.uav_models.map((model) => ({ id: model.id, name: model.name }));
}

export function cameraOptionLabel(camera: Pick<CameraOption, "name" | "spectra">): string {
  return `${camera.name} (${camera.spectra.join(", ")})`;
}

export function camerasForModel(modelId: string): CameraOption[] {
  if (!modelId) return [];
  const byId = new Map(fleetCatalog.cameras.map((camera) => [camera.id, camera]));
  const seen = new Set<string>();
  const options: CameraOption[] = [];
  for (const edge of fleetCatalog.compatibility) {
    if (edge.uav_model_id !== modelId || seen.has(edge.camera_id)) continue;
    const camera = byId.get(edge.camera_id);
    if (!camera?.name) continue;
    seen.add(edge.camera_id);
    options.push({ id: camera.id, name: camera.name, spectra: camera.spectra });
  }
  return options;
}

export function resizeAerodromes(aerodromes: AerodromeInput[], count: number): AerodromeInput[] {
  if (!Number.isInteger(count) || count < 1 || count > 4) {
    throw new Error("Число аэродромов от 1 до 4.");
  }
  if (count === aerodromes.length) return aerodromes;
  if (count < aerodromes.length) return aerodromes.slice(0, count);
  const added = Array.from({ length: count - aerodromes.length }, () => ({
    lon: DEFAULT_AERODROME_LON,
    lat: DEFAULT_AERODROME_LAT,
  }));
  return [...aerodromes, ...added];
}

export function clearMissingAerodromes(boards: BoardInput[], aerodromeCount: number): BoardInput[] {
  return boards.map((board) =>
    board.aerodromeIndex !== null && board.aerodromeIndex >= aerodromeCount
      ? { ...board, aerodromeIndex: null }
      : board,
  );
}

export function addBoard(boards: BoardInput[]): BoardInput[] {
  return [...boards, { modelId: "", cameraId: "", aerodromeIndex: 0, count: 1 }];
}

export function removeBoard(boards: BoardInput[], index: number): BoardInput[] {
  return boards.filter((_, itemIndex) => itemIndex !== index);
}

export function withModel(board: BoardInput, modelId: string): BoardInput {
  const allowed = new Set(camerasForModel(modelId).map((camera) => camera.id));
  return {
    ...board,
    modelId,
    cameraId: allowed.has(board.cameraId) ? board.cameraId : "",
  };
}

function requireFinite(value: number, label: string, minimum?: number): void {
  if (!Number.isFinite(value) || (minimum !== undefined && value < minimum)) {
    throw new Error(`${label}: укажите корректное числовое значение.`);
  }
}

function constraintsFileText(file: KmlFileRecord | null): string {
  if (!file) return "";
  if (file.status !== "ready") {
    throw new Error("Загрузите корректный KML с зонами ограничений.");
  }
  return file.raw_text ?? "";
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
  constraintsFileText(inputs.restrictedZones);
  if (inputs.aerodromes.length < 1 || inputs.aerodromes.length > 4) {
    throw new Error("Число аэродромов от 1 до 4.");
  }
  for (const [index, aerodrome] of inputs.aerodromes.entries()) {
    validatePoint(aerodrome.lon, aerodrome.lat, aerodromeId(index));
  }
  if (!inputs.boards.length) throw new Error("Добавьте хотя бы один борт.");
  for (const [index, board] of inputs.boards.entries()) {
    const label = boardId(index);
    if (!board.modelId.trim() || !catalogModels().some((model) => model.id === board.modelId)) {
      throw new Error(`${label}: выберите модель.`);
    }
    if (!board.cameraId || !camerasForModel(board.modelId).some((camera) => camera.id === board.cameraId)) {
      throw new Error(`${label}: выберите камеру, совместимую с моделью.`);
    }
    if (
      board.aerodromeIndex === null ||
      !Number.isInteger(board.aerodromeIndex) ||
      board.aerodromeIndex < 0 ||
      board.aerodromeIndex >= inputs.aerodromes.length
    ) {
      throw new Error(`${label}: выберите аэродром.`);
    }
    if (!Number.isInteger(board.count) || board.count < 1) {
      throw new Error(`${label}: укажите количество не меньше 1.`);
    }
  }
  requireFinite(inputs.gsdCmPerPx, "GSD", 0);
  if (inputs.gsdCmPerPx <= 0) throw new Error("GSD: укажите корректное числовое значение.");
  requireFinite(inputs.forwardOverlap, "Перекрытие вдоль");
  requireFinite(inputs.sideOverlap, "Перекрытие поперёк");
  if (inputs.forwardOverlap < 0 || inputs.forwardOverlap >= 1) {
    throw new Error("Перекрытие вдоль должно быть от 0 до 1, не включая 1.");
  }
  if (inputs.sideOverlap < 0 || inputs.sideOverlap >= 1) {
    throw new Error("Перекрытие поперёк должно быть от 0 до 1, не включая 1.");
  }
  requireFinite(inputs.stripDirectionDeg, "Направление полос");
  requireFinite(inputs.windSpeedMps, "Скорость ветра", 0);
  if (inputs.windDirectionFromDeg === null) {
    throw new Error("Укажите направление ветра от 0 до 360 градусов.");
  }
  requireFinite(inputs.windDirectionFromDeg, "Направление ветра");
  if (inputs.windDirectionFromDeg < 0 || inputs.windDirectionFromDeg > 360) {
    throw new Error("Направление ветра должно быть от 0 до 360 градусов.");
  }
}

export function solverCriterion(objective: string): "min_time" | "min_flight_hours" {
  if (objective === "min_time") return "min_time";
  if (objective === "min_total_flight_time") return "min_flight_hours";
  throw new Error("Выберите критерий оптимизации.");
}

function surveyRing(file: KmlFileRecord, parser?: XmlParser): void {
  if (!file.raw_text) throw new Error("В KML задания нет полигона съёмки.");
  const polygons = extractKmlPolygons(file.raw_text, parser);
  if (polygons.length === 0) throw new Error("В KML задания нет полигона съёмки.");
}

function boardRows(inputs: ScenarioInputs) {
  if (!inputs.boards.length) throw new Error("Добавьте хотя бы один борт.");
  return inputs.boards.map((board, index) => {
    const label = boardId(index);
    if (!board.modelId.trim() || !catalogModels().some((model) => model.id === board.modelId)) {
      throw new Error(`${label}: выберите модель.`);
    }
    if (!board.cameraId || !camerasForModel(board.modelId).some((camera) => camera.id === board.cameraId)) {
      throw new Error(`${label}: выберите камеру, совместимую с моделью.`);
    }
    if (
      board.aerodromeIndex === null ||
      !Number.isInteger(board.aerodromeIndex) ||
      board.aerodromeIndex < 0 ||
      board.aerodromeIndex >= inputs.aerodromes.length
    ) {
      throw new Error(`${label}: выберите аэродром.`);
    }
    if (!Number.isInteger(board.count) || board.count < 1) {
      throw new Error(`${label}: укажите количество не меньше 1.`);
    }
    return {
      id: label,
      model_id: board.modelId,
      camera_id: board.cameraId,
      aerodrome_id: aerodromeId(board.aerodromeIndex),
      count: board.count,
    };
  });
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
  if (!inputs.surveyTask || inputs.surveyTask.status !== "ready" || !inputs.surveyTask.raw_text) {
    throw new Error("Загрузите корректный KML с границами задания на съёмку.");
  }
  const constraintsKml = constraintsFileText(inputs.restrictedZones);
  if (inputs.aerodromes.length < 1 || inputs.aerodromes.length > 4) {
    throw new Error("Число аэродромов от 1 до 4.");
  }
  for (const [index, aerodrome] of inputs.aerodromes.entries()) {
    validatePoint(aerodrome.lon, aerodrome.lat, aerodromeId(index));
  }
  requireFinite(inputs.gsdCmPerPx, "GSD", 0);
  if (inputs.gsdCmPerPx <= 0) throw new Error("GSD: укажите корректное числовое значение.");
  requireFinite(inputs.forwardOverlap, "Перекрытие вдоль");
  requireFinite(inputs.sideOverlap, "Перекрытие поперёк");
  if (inputs.forwardOverlap < 0 || inputs.forwardOverlap >= 1) {
    throw new Error("Перекрытие вдоль должно быть от 0 до 1, не включая 1.");
  }
  if (inputs.sideOverlap < 0 || inputs.sideOverlap >= 1) {
    throw new Error("Перекрытие поперёк должно быть от 0 до 1, не включая 1.");
  }
  requireFinite(inputs.stripDirectionDeg, "Направление полос");
  surveyRing(inputs.surveyTask, parser);
  return {
    scenario_id: inputs.scenarioId.trim(),
    crs: "EPSG:4326",
    criterion: solverCriterion(objective),
    gsd_cm_per_px: inputs.gsdCmPerPx,
    survey_kml: inputs.surveyTask.raw_text,
    constraints_kml: constraintsKml,
    required_spectrum: inputs.surveyType,
    aerodromes: inputs.aerodromes.map((aerodrome, index) => ({
      id: aerodromeId(index),
      lat: aerodrome.lat,
      lon: aerodrome.lon,
    })),
    boards: boardRows(inputs),
    survey: {
      forward_overlap: inputs.forwardOverlap,
      side_overlap: inputs.sideOverlap,
      strip_direction_deg: inputs.stripDirectionDeg,
    },
    survey_type: inputs.surveyType,
    wind: {
      speed_ms: inputs.windSpeedMps,
      direction_deg: windDirectionDeg(inputs.windDirectionFromDeg),
    },
    prototype_limitations: [
      "The survey KML is required. A missing constraints KML is an empty file and adds no polygons.",
      "Altitude sentences are copied as text and are not parsed in the browser.",
      "Each board card names a catalog model, a compatible camera, an aerodrome, and a count of identical aircraft. Survey spectrum does not filter cameras.",
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
