import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import {
  ApiError,
  InputError,
  RequestCoordinator,
  createApiClient,
  pollJobLifecycle,
  submitFromEditors,
} from "./api";
import { getResultPresentation } from "./presentation";
import {
  CONTRACT_VERSION,
  type JobResult,
  type JobStatus,
  type JsonObject,
  type LifecycleState,
} from "./types";

const DEFAULT_MISSION = "Demo mission";
const DEFAULT_UAV = "Geoscan Gemini";
const DEFAULT_PAYLOAD = "Sony UMC-R10C";
const DEFAULT_OBJECTIVE = "min_time";
const DEFAULT_TIME_LIMIT = "30";
const DEFAULT_SEED = "7";

const DEFAULT_SCENARIO = JSON.stringify(
  { name: DEFAULT_MISSION, uav_model: DEFAULT_UAV, payload_model: DEFAULT_PAYLOAD },
  null,
  2,
);

const DEFAULT_OPTIMIZATION = JSON.stringify(
  {
    objective: DEFAULT_OBJECTIVE,
    time_limit_seconds: Number(DEFAULT_TIME_LIMIT),
    test_outcome: "feasible",
  },
  null,
  2,
);

const STATE_LABELS: Record<LifecycleState, string> = {
  queued: "В очереди",
  running: "Выполняется",
  completed: "Завершено",
  timed_out: "Тайм-аут",
  failed: "Ошибка",
};

function formatTimestamp(value: string | null): string {
  if (!value) return "Ожидается";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("ru-RU");
}

function formatError(error: unknown): string {
  if (error instanceof InputError) return error.message;
  if (error instanceof ApiError) {
    const context = error.status ? ` (HTTP ${error.status}, ${error.code})` : ` (${error.code})`;
    return `${error.message}${context}`;
  }
  if (error instanceof Error) return error.message;
  return "Неожиданная ошибка интерфейса.";
}

function parseObject(text: string): JsonObject | null {
  try {
    const value: unknown = JSON.parse(text);
    return typeof value === "object" && value !== null && !Array.isArray(value)
      ? (value as JsonObject)
      : null;
  } catch {
    return null;
  }
}

function updateJsonFields(text: string, updates: JsonObject): string {
  const current = parseObject(text);
  return current ? JSON.stringify({ ...current, ...updates }, null, 2) : text;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function getLimitations(report: JsonObject): string[] {
  return Array.isArray(report.limitations)
    ? report.limitations.filter((item): item is string => typeof item === "string")
    : [];
}

function SolverSummary({ report }: { report: JsonObject }) {
  const method = readString(report.method);
  const objective = readString(report.objective);
  const runtime = readNumber(report.runtime_seconds);
  const limitations = getLimitations(report);

  return (
    <div className="result-section">
      <h3>Сводка расчёта</h3>
      <dl className="result-facts">
        <div><dt>Метод</dt><dd>{method ?? "Не указан"}</dd></div>
        <div><dt>Цель</dt><dd>{objective ?? "Не указана"}</dd></div>
        <div><dt>Время работы</dt><dd>{runtime === null ? "Не указано" : `${runtime.toFixed(2)} с`}</dd></div>
      </dl>
      <div className="limitations">
        <h4>Ограничения и замечания</h4>
        {limitations.length ? (
          <ul>{limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        ) : (
          <p>Backend не передал дополнительных ограничений.</p>
        )}
      </div>
    </div>
  );
}

function MissionPlanSummary({ plan }: { plan: JsonObject }) {
  const sorties = Array.isArray(plan.sorties) ? plan.sorties : null;
  return (
    <div className="result-section mission-summary">
      <h3>План миссии</h3>
      <div className="mission-summary-grid">
        <div><strong>{sorties ? sorties.length : "—"}</strong><span>полётных заданий</span></div>
        <p>План получен от backend и показан без браузерных расчётов или изменения результата.</p>
      </div>
    </div>
  );
}

function failureMessage(error: JsonObject | null): string {
  if (!error) return "Backend не передал описание ошибки.";
  const directMessage = readString(error.message);
  if (directMessage) return directMessage;
  const report = error.solver_report;
  if (typeof report === "object" && report !== null && !Array.isArray(report)) {
    const limitations = getLimitations(report as JsonObject);
    if (limitations.length) return limitations[0];
  }
  return "Вычислительный контур не смог сформировать результат.";
}

function ResultPanel({ result }: { result: JobResult }) {
  const presentation = getResultPresentation(result);
  const synthetic =
    result.state !== "failed" &&
    result.mission_plan !== null &&
    result.mission_plan.test_data === true;
  const icon = presentation.badge === "feasible"
    ? "✓"
    : presentation.badge === "infeasible"
      ? "—"
      : presentation.badge === "timed_out" ? "◷" : "!";

  return (
    <section className={`card result-card result-${presentation.badge}`} aria-labelledby="result-title">
      <div className="result-hero">
        <div className={`result-icon ${presentation.badge}`} aria-hidden="true">{icon}</div>
        <div>
          <p className="eyebrow">Результат расчёта</p>
          <h2 id="result-title">{presentation.title}</h2>
          <p className="result-summary">{presentation.summary}</p>
        </div>
        <span className={`status-badge ${presentation.badge}`}>{presentation.badge}</span>
      </div>

      {synthetic && (
        <div className="synthetic-notice">
          <strong>Демонстрационные данные</strong>
          <span>Backend пометил этот план как синтетический — он не предназначен для полёта.</span>
        </div>
      )}

      {result.state === "failed" ? (
        <div className="result-section error-detail">
          <h3>Сообщение вычислительного контура</h3>
          <p>{failureMessage(result.error)}</p>
        </div>
      ) : (
        <>
          {result.mission_plan && <MissionPlanSummary plan={result.mission_plan} />}
          <SolverSummary report={result.solver_report} />
        </>
      )}

      <details className="raw-response">
        <summary>Raw response JSON</summary>
        <pre>{JSON.stringify(result, null, 2)}</pre>
      </details>
    </section>
  );
}

function Lifecycle({
  observedStates,
  result,
}: {
  observedStates: LifecycleState[];
  result: JobResult | null;
}) {
  return (
    <div className="lifecycle" aria-label="Прогресс задачи">
      <div className={`lifecycle-step ${observedStates.includes("queued") ? "observed" : ""}`}>
        <span>1</span><div><strong>QUEUED</strong><small>Задача принята</small></div>
      </div>
      <div className="lifecycle-line" />
      <div className={`lifecycle-step ${observedStates.includes("running") ? "active" : ""}`}>
        <span>2</span><div><strong>RUNNING</strong><small>Расчёт выполняется</small></div>
      </div>
      <div className="lifecycle-line" />
      <div className={`lifecycle-step ${result ? "terminal" : ""}`}>
        <span>3</span><div><strong>RESULT</strong><small>Ответ backend</small></div>
      </div>
    </div>
  );
}

export default function App() {
  const api = useMemo(() => createApiClient(), []);
  const [missionName, setMissionName] = useState(DEFAULT_MISSION);
  const [uavModel, setUavModel] = useState(DEFAULT_UAV);
  const [payloadModel, setPayloadModel] = useState(DEFAULT_PAYLOAD);
  const [objective, setObjective] = useState(DEFAULT_OBJECTIVE);
  const [timeLimit, setTimeLimit] = useState(DEFAULT_TIME_LIMIT);
  const [scenarioText, setScenarioText] = useState(DEFAULT_SCENARIO);
  const [optimizationText, setOptimizationText] = useState(DEFAULT_OPTIMIZATION);
  const [seedText, setSeedText] = useState(DEFAULT_SEED);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [result, setResult] = useState<JobResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const [observedStates, setObservedStates] = useState<LifecycleState[]>([]);
  const coordinatorRef = useRef(new RequestCoordinator());

  useEffect(() => () => coordinatorRef.current.cancel(), []);

  function updateScenarioField(field: string, value: string) {
    setScenarioText((current) => updateJsonFields(current, { [field]: value }));
  }

  function updateOptimizationField(field: string, value: string) {
    const storedValue = field === "time_limit_seconds" && value !== "" ? Number(value) : value;
    setOptimizationText((current) => updateJsonFields(current, { [field]: storedValue }));
  }

  function handleScenarioRaw(value: string) {
    setScenarioText(value);
    const parsed = parseObject(value);
    if (!parsed) return;
    if (typeof parsed.name === "string") setMissionName(parsed.name);
    if (typeof parsed.uav_model === "string") setUavModel(parsed.uav_model);
    if (typeof parsed.payload_model === "string") setPayloadModel(parsed.payload_model);
  }

  function handleOptimizationRaw(value: string) {
    setOptimizationText(value);
    const parsed = parseObject(value);
    if (!parsed) return;
    if (typeof parsed.objective === "string") setObjective(parsed.objective);
    if (typeof parsed.time_limit_seconds === "number") setTimeLimit(String(parsed.time_limit_seconds));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const { generation, signal } = coordinatorRef.current.begin();
    setError(null);
    setResult(null);
    setJob(null);
    setObservedStates([]);
    setIsPolling(false);
    setIsSubmitting(true);

    try {
      const submitted = await submitFromEditors(api, scenarioText, optimizationText, seedText, signal);
      if (!coordinatorRef.current.isCurrent(generation)) return;
      setJob(submitted);
      setObservedStates([submitted.state]);
      setIsSubmitting(false);
      setIsPolling(true);
      const terminalResult = await pollJobLifecycle({
        api,
        jobId: submitted.job_id,
        signal,
        onStatus: (status) => {
          if (coordinatorRef.current.isCurrent(generation)) {
            setJob(status);
            setObservedStates((states) =>
              states.includes(status.state) ? states : [...states, status.state],
            );
          }
        },
      });
      if (coordinatorRef.current.isCurrent(generation)) setResult(terminalResult);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      if (coordinatorRef.current.isCurrent(generation)) setError(formatError(caught));
    } finally {
      if (coordinatorRef.current.isCurrent(generation)) {
        setIsSubmitting(false);
        setIsPolling(false);
      }
    }
  }

  const backendLabel = job ? STATE_LABELS[job.state] : error ? "Ошибка запроса" : "Ожидает запуска";
  const backendTone = job?.state ?? (error ? "failed" : "idle");

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="header-copy">
          <p className="eyebrow">Инженерный прототип планирования</p>
          <h1>UAV Mission Planner</h1>
          <p className="subtitle">Планирование групповых миссий БВС: отправьте сценарий, проследите расчёт и получите единый результат.</p>
          <div className="connection-row" aria-label="Состояние приложения">
            <div className="connection-pill ready"><span className="status-dot" /><small>Frontend</small><strong>Готов</strong></div>
            <div className={`connection-pill ${backendTone}`}><span className="status-dot" /><small>Backend / задача</small><strong>{backendLabel}</strong></div>
          </div>
        </div>
        <div className="contract-chip"><span>contract</span><strong>{CONTRACT_VERSION}</strong></div>
      </header>

      <section className="card form-card" aria-labelledby="job-form-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Новая задача</p>
            <h2 id="job-form-title">Параметры миссии</h2>
            <p className="section-description">Эти поля формируют запрос. Маршрут и выполнимость определяет только backend.</p>
          </div>
          <span className="step-chip">Шаг 1 из 2</span>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="primary-form-grid">
            <label className="wide-field"><span>Название миссии</span><input value={missionName} required onChange={(event) => { setMissionName(event.target.value); updateScenarioField("name", event.target.value); }} /></label>
            <label><span>Модель БВС</span><input value={uavModel} required onChange={(event) => { setUavModel(event.target.value); updateScenarioField("uav_model", event.target.value); }} /></label>
            <label><span>Полезная нагрузка</span><input value={payloadModel} required onChange={(event) => { setPayloadModel(event.target.value); updateScenarioField("payload_model", event.target.value); }} /></label>
            <label>
              <span>Критерий оптимизации</span>
              <select value={objective} onChange={(event) => { setObjective(event.target.value); updateOptimizationField("objective", event.target.value); }}>
                <option value="min_time">Минимальное время выполнения</option>
                <option value="min_total_flight_time">Минимальный суммарный налёт</option>
              </select>
              <small className="field-hint">Код: {objective}</small>
            </label>
            <label><span>Лимит расчёта, секунд</span><input type="number" min="0" step="1" required value={timeLimit} onChange={(event) => { setTimeLimit(event.target.value); updateOptimizationField("time_limit_seconds", event.target.value); }} /></label>
            <label><span>Seed</span><input type="number" step="1" required value={seedText} onChange={(event) => setSeedText(event.target.value)} /><small className="field-hint">Для воспроизводимого запуска</small></label>
          </div>

          <details className="advanced-panel">
            <summary><span>Расширенные настройки / Raw JSON</span><small>Для разработчиков и точной настройки запроса</small></summary>
            <p className="advanced-note">При отправке используются значения JSON ниже. Валидные изменения синхронизируются с основной формой.</p>
            <div className="editor-grid">
              <label><span>Scenario JSON</span><textarea value={scenarioText} onChange={(event) => handleScenarioRaw(event.target.value)} spellCheck={false} rows={11} /></label>
              <label><span>Optimization JSON</span><textarea value={optimizationText} onChange={(event) => handleOptimizationRaw(event.target.value)} spellCheck={false} rows={11} /></label>
            </div>
          </details>

          <div className="form-footer">
            <div className="submit-copy"><strong>Готово к отправке</strong><span>Повторный запуск безопасно остановит текущий опрос.</span></div>
            <button type="submit" disabled={isSubmitting}>{isSubmitting ? "Отправляем задачу…" : job ? "Запустить ещё раз" : "Запустить расчёт"}</button>
          </div>
        </form>
      </section>

      {error && <div className="error-banner" role="alert"><span className="error-mark" aria-hidden="true">!</span><div><strong>Не удалось выполнить запрос</strong><span>{error}</span></div></div>}

      {job && (
        <section className="card status-card" aria-labelledby="job-status-title" aria-live="polite">
          <div className="section-heading"><div><p className="eyebrow">Шаг 2 из 2</p><h2 id="job-status-title">Ход выполнения</h2></div><span className={`status-badge ${job.state}`}>{STATE_LABELS[job.state]}</span></div>
          <Lifecycle observedStates={observedStates} result={result} />
          <dl className="job-details">
            <div className="job-id-row"><dt>Job ID</dt><dd>{job.job_id}</dd></div>
            <div><dt>Создано</dt><dd>{formatTimestamp(job.created_at)}</dd></div>
            <div><dt>Запущено</dt><dd>{formatTimestamp(job.started_at)}</dd></div>
            <div><dt>Завершено</dt><dd>{formatTimestamp(job.finished_at)}</dd></div>
          </dl>
          {isPolling && <div className="polling-indicator"><span className="pulse" /> Backend выполняет задачу, статус обновляется автоматически</div>}
        </section>
      )}

      {result && <ResultPanel result={result} />}
      <footer>Интерфейс отображает авторитетный ответ backend. Расчёты маршрутов и выполнимости в браузере не выполняются.</footer>
    </main>
  );
}
