import type { JobResult } from "./types";

export interface ResultPresentation {
  title: string;
  badge: "feasible" | "infeasible" | "timed_out" | "failed";
  summary: string;
}

export function getResultPresentation(result: JobResult): ResultPresentation {
  if (result.state === "failed") {
    return {
      title: "Ошибка вычислительного контура",
      badge: "failed",
      summary: "Backend сообщил об ошибке и не сформировал результат миссии.",
    };
  }
  if (result.outcome === "feasible") {
    return {
      title: "План миссии сформирован",
      badge: "feasible",
      summary: "Backend нашёл допустимый план для переданного сценария.",
    };
  }
  if (result.outcome === "infeasible") {
    return {
      title: "Допустимый план не найден",
      badge: "infeasible",
      summary: "Расчёт завершён корректно, но при заданных условиях выполнимого плана нет.",
    };
  }
  return {
    title: "Время расчёта истекло",
    badge: "timed_out",
    summary: "Вычислительный контур достиг лимита времени до получения итогового плана.",
  };
}
