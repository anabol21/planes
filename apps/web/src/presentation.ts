import { resolveOutcomeCard } from "./errorCards";
import type { JobResult } from "./types";

export interface ResultPresentation {
  title: string;
  badge: "feasible" | "infeasible" | "timed_out" | "failed";
  summary: string;
}

export function getResultPresentation(result: JobResult): ResultPresentation {
  const card = resolveOutcomeCard(result);
  if (result.state === "failed") {
    return {
      title: card?.title ?? "Ошибка вычислительного контура",
      badge: "failed",
      summary: card?.body ?? "Backend сообщил об ошибке и не сформировал результат миссии.",
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
      title: card?.title ?? "Допустимый план не найден",
      badge: "infeasible",
      summary: card?.body ?? "Расчёт завершён корректно, но при заданных условиях выполнимого плана нет. Это отказ сценария, а не сбой сервиса.",
    };
  }
  return {
    title: card?.title ?? "Время расчёта истекло",
    badge: "timed_out",
    summary: card?.body ?? "Вычислительный контур достиг лимита времени до получения итогового плана.",
  };
}
