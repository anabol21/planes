import type { JobResult, JsonObject } from "./types";

export type ErrorCode =
  | "INFEASIBLE_ENDURANCE_NO_RECHARGE"
  | "INFEASIBLE_NO_SWATHS"
  | "INFEASIBLE_TERRAIN_CLEARANCE"
  | "TIMED_OUT_BUDGET"
  | "ERROR_UAV_NOT_IN_CATALOG"
  | "ERROR_CAMERA_NOT_IN_CATALOG"
  | "ERROR_CAMERA_UAV_INCOMPATIBLE"
  | "ERROR_MISSING_AERODROMES"
  | "ERROR_UNKNOWN_AERODROME"
  | "ERROR_NO_BOARDS"
  | "ERROR_MODEL_NO_ENDURANCE_OR_SPEED"
  | "ERROR_WORKER_EXCEPTION"
  | "OFFLINE_ENERGY_UNCOVERED";

export type CardTone = "infeasible" | "error" | "timed_out" | "offline";

export interface HighlightFields {
  model?: boolean;
  camera?: boolean;
  aerodrome?: boolean;
  boards?: boolean;
  survey?: boolean;
  timeLimit?: boolean;
}

export interface OutcomeCardCopy {
  code: ErrorCode;
  tone: CardTone;
  title: string;
  body: string;
  cta: string;
  highlight: HighlightFields;
}

const CARDS: Record<ErrorCode, Omit<OutcomeCardCopy, "code">> = {
  INFEASIBLE_ENDURANCE_NO_RECHARGE: {
    tone: "infeasible",
    title: "Не хватает ресурса одного вылета",
    body: "При запрете дозарядки борт не успевает покрыть все галсы за один вылет. Включите дозарядку или добавьте борта / сократите зону.",
    cta: "Добавьте борта или сократите зону съёмки и запустите снова.",
    highlight: { boards: true },
  },
  INFEASIBLE_NO_SWATHS: {
    tone: "infeasible",
    title: "Не удалось построить галсы",
    body: "По зонам съёмки не получилось сгенерировать маршрутные галсы. Проверьте полигоны съёмки и запретные зоны — возможно, зона слишком мала или полностью перекрыта ограничениями.",
    cta: "Проверьте KML съёмки и зон ограничений.",
    highlight: { survey: true },
  },
  INFEASIBLE_TERRAIN_CLEARANCE: {
    tone: "infeasible",
    title: "Маршрут не проходит проверку рельефа",
    body: "При строгой проверке рельефа найдены нарушения запаса высоты над землёй. Ослабьте safety_margin, поднимите AGL или отключите strict_terrain_check для демо.",
    cta: "Измените сценарий и запустите снова.",
    highlight: {},
  },
  TIMED_OUT_BUDGET: {
    tone: "timed_out",
    title: "Расчёт прерван по времени",
    body: "Оптимизатор не успел построить план за отведённый лимит. Упростите сценарий или увеличьте time_limit_seconds.",
    cta: "Упростите сценарий или увеличьте лимит расчёта и повторите.",
    highlight: { timeLimit: true },
  },
  ERROR_UAV_NOT_IN_CATALOG: {
    tone: "error",
    title: "Модель БВС не найдена в каталоге",
    body: "Выбранная модель БВС нет в каталоге флота. Выберите модель из списка каталога.",
    cta: "Выберите модель из списка каталога.",
    highlight: { model: true, boards: true },
  },
  ERROR_CAMERA_NOT_IN_CATALOG: {
    tone: "error",
    title: "Камера не найдена в каталоге",
    body: "Выбранная камера отсутствует в каталоге. Выберите камеру из списка.",
    cta: "Выберите камеру из списка каталога.",
    highlight: { camera: true, boards: true },
  },
  ERROR_CAMERA_UAV_INCOMPATIBLE: {
    tone: "error",
    title: "Камера не совместима с БВС",
    body: "Эта камера не совместима с выбранной моделью БВС по каталогу. Выберите другую пару.",
    cta: "Выберите совместимую пару модель + камера.",
    highlight: { model: true, camera: true, boards: true },
  },
  ERROR_MISSING_AERODROMES: {
    tone: "error",
    title: "Не заданы аэродромы",
    body: "В сценарии нет ни одной ВПП. Добавьте хотя бы один аэродром с координатами.",
    cta: "Добавьте аэродром с координатами.",
    highlight: { aerodrome: true },
  },
  ERROR_UNKNOWN_AERODROME: {
    tone: "error",
    title: "Борт привязан к неизвестной ВПП",
    body: "У борта указан аэродром, которого нет в списке ВПП сценария.",
    cta: "Выберите аэродром из списка сценария.",
    highlight: { aerodrome: true, boards: true },
  },
  ERROR_NO_BOARDS: {
    tone: "error",
    title: "Нет бортов в сценарии",
    body: "Добавьте хотя бы один борт (модель + камера + аэродром).",
    cta: "Добавьте карточку борта.",
    highlight: { boards: true },
  },
  ERROR_MODEL_NO_ENDURANCE_OR_SPEED: {
    tone: "error",
    title: "У модели БВС нет скорости или ресурса полёта",
    body: "В каталоге у выбранной модели не заданы корректные survey/airspeed или время полёта. Проверьте карточку модели.",
    cta: "Выберите другую модель из каталога.",
    highlight: { model: true, boards: true },
  },
  ERROR_WORKER_EXCEPTION: {
    tone: "error",
    title: "Ошибка расчёта",
    body: "Внутренняя ошибка ядра планирования. Сохраните job_id и текст ошибки для команды.",
    cta: "Сохраните Job ID и повторите запуск позже.",
    highlight: {},
  },
  OFFLINE_ENERGY_UNCOVERED: {
    tone: "offline",
    title: "Энергии не хватает на полное покрытие",
    body: "При текущем запасе энергии часть зон остаётся непокрытой. Разрешите возврат на дозарядку или увеличьте энергобюджет / число бортов.",
    cta: "Добавьте борта или сократите зону. Код пока не live-контракт v0 (OPEN-008).",
    highlight: { boards: true },
  },
};

const INTERNAL_LIMITATION = /sitecustomize|traceback|\biso\s+f2c\s*=|mvp_on_path\s*=|^live path:|f2c_isolated_worker|grisha_sitecustomize/i;

export function isKnownErrorCode(value: unknown): value is ErrorCode {
  return typeof value === "string" && value in CARDS;
}

export function cardForCode(code: string | null | undefined): OutcomeCardCopy | null {
  if (!isKnownErrorCode(code)) return null;
  return { code, ...CARDS[code] };
}

export function publicLimitations(report: JsonObject | null | undefined): string[] {
  if (!report || !Array.isArray(report.limitations)) return [];
  const seen = new Set<string>();
  const items: string[] = [];
  for (const item of report.limitations) {
    if (typeof item !== "string") continue;
    const text = item.trim();
    if (!text || INTERNAL_LIMITATION.test(text) || seen.has(text)) continue;
    seen.add(text);
    items.push(text);
  }
  return items;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function collectTexts(result: JobResult): string[] {
  const texts: string[] = [];
  if (result.state !== "failed") {
    texts.push(...publicLimitations(result.solver_report));
    const reportError = result.solver_report.error;
    if (typeof reportError === "string") texts.push(reportError);
  } else if (result.error) {
    for (const key of ["message", "error", "type"] as const) {
      const value = readString(result.error[key]);
      if (value) texts.push(value);
    }
    const report = result.error.solver_report;
    if (report && typeof report === "object" && !Array.isArray(report)) {
      texts.push(...publicLimitations(report as JsonObject));
    }
  }
  if (typeof result.error_code === "string") texts.push(result.error_code);
  return texts;
}

export function inferErrorCode(result: JobResult): ErrorCode | null {
  if (isKnownErrorCode(result.error_code)) return result.error_code;
  if (result.state === "failed" && result.error && isKnownErrorCode(result.error.error_code)) {
    return result.error.error_code;
  }
  const blob = collectTexts(result).join("\n");
  const outcome = result.state === "failed"
    ? (typeof result.error?.outcome === "string" ? result.error.outcome : "error")
    : result.outcome;

  if (/camera\s+\S+\s+is not compatible with model/i.test(blob)) return "ERROR_CAMERA_UAV_INCOMPATIBLE";
  if (/camera\s+\S+\s+not in catalog|unknown camera:/i.test(blob)) return "ERROR_CAMERA_NOT_IN_CATALOG";
  if (/uav model\s+\S+\s+not in catalog|unknown uav model:/i.test(blob)) return "ERROR_UAV_NOT_IN_CATALOG";
  if (/missing fields:\s*aerodromes(?:\s|$|,)/i.test(blob)) return "ERROR_MISSING_AERODROMES";
  if (/unknown aerodrome:/i.test(blob)) return "ERROR_UNKNOWN_AERODROME";
  if (/\bno boards\b|missing fields:\s*boards(?:\s|$|,)/i.test(blob)) return "ERROR_NO_BOARDS";
  if (/has no positive endurance or (?:survey\/)?airspeed/i.test(blob)) return "ERROR_MODEL_NO_ENDURANCE_OR_SPEED";
  if (
    (outcome === "infeasible" || outcome === undefined) &&
    /allow_recharge\s*=\s*false/i.test(blob) &&
    /uncovered[_\s-]*swaths\s*=\s*\d+|leftover swaths not packed/i.test(blob)
  ) {
    return "INFEASIBLE_ENDURANCE_NO_RECHARGE";
  }
  if (/(?:^|\n)no swaths(?:\n|$)/i.test(blob)) return "INFEASIBLE_NO_SWATHS";
  if (/terrain_clearance_violation|strict_terrain_check refused|clearance violation/i.test(blob)) {
    return "INFEASIBLE_TERRAIN_CLEARANCE";
  }
  if (outcome === "timed_out" || /budgetexhausted|budget exhausted before route/i.test(blob)) {
    return "TIMED_OUT_BUDGET";
  }
  if (outcome === "error" || result.state === "failed") return "ERROR_WORKER_EXCEPTION";
  return null;
}

export function resolveOutcomeCard(result: JobResult): OutcomeCardCopy | null {
  return cardForCode(inferErrorCode(result));
}

export function highlightFromResult(result: JobResult | null): HighlightFields {
  if (!result) return {};
  return resolveOutcomeCard(result)?.highlight ?? {};
}

export function detailLines(details: JsonObject | undefined): Array<{ key: string; value: string }> {
  if (!details) return [];
  return Object.entries(details)
    .filter(([, value]) => value !== null && value !== undefined && typeof value !== "object")
    .map(([key, value]) => ({ key, value: String(value) }));
}
