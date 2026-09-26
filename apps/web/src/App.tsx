import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";

import {
  ApiError,
  InputError,
  RequestCoordinator,
  createApiClient,
  pollJobLifecycle,
  submitFromEditors,
} from "./api";
import {
  formatFileSize,
  readKmlFile,
  type KmlCategory,
  type KmlFileRecord,
} from "./kml";
import { formatDecimalInput, normalizeDecimalDraft, parseDecimalInput } from "./numberInput";
import { getResultPresentation } from "./presentation";
import {
  DEFAULT_AERODROMES,
  DEFAULT_BOARDS,
  DEFAULT_FORWARD_OVERLAP,
  DEFAULT_GSD_CM_PER_PX,
  DEFAULT_SIDE_OVERLAP,
  DEFAULT_STRIP_DIRECTION_DEG,
  DEFAULT_TIME_LIMIT,
  MAX_TIME_LIMIT_SECONDS,
  addBoard,
  aerodromeId,
  buildOptimization,
  buildPrototypeScenario,
  cameraOptionLabel,
  camerasForModel,
  catalogModels,
  clearMissingAerodromes,
  removeBoard,
  resizeAerodromes,
  validateScenarioInputs,
  withModel,
  type AerodromeInput,
  type BoardInput,
  type ScenarioInputs,
  type SurveyType,
} from "./scenario";
import {
  CONTRACT_VERSION,
  type JobResult,
  type JobStatus,
  type JsonObject,
  type LifecycleState,
} from "./types";

const DEFAULT_OBJECTIVE = "min_time";
const DEFAULT_SEED = "7";
const TIME_LIMIT_TOO_LONG = `Лимит расчёта не больше ${MAX_TIME_LIMIT_SECONDS} секунд.`;

const STATE_LABELS: Record<LifecycleState, string> = {
  queued: "В очереди",
  running: "Выполняется",
  completed: "Завершено",
  timed_out: "Тайм-аут",
  failed: "Ошибка",
};

const CATEGORY_LABELS: Record<KmlCategory, string> = {
  survey_task: "Задание на съёмку",
  restricted_zones: "Зоны ограничений",
  obstacle: "Высотные препятствия",
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
        {limitations.length ? <ul>{limitations.map((item) => <li key={item}>{item}</li>)}</ul> : <p>Backend не передал дополнительных ограничений.</p>}
      </div>
    </div>
  );
}

function MissionPlanSummary({ plan }: { plan: JsonObject }) {
  const sorties = Array.isArray(plan.sorties) ? plan.sorties : null;
  const explicitAssignments = sorties?.flatMap((sortie, index) => {
    if (typeof sortie !== "object" || sortie === null || Array.isArray(sortie)) return [];
    const item = sortie as JsonObject;
    const uavId = readString(item.uav_id) ?? readString(item.aircraft_id);
    return uavId ? [{ key: `${uavId}-${index}`, uavId }] : [];
  }) ?? [];
  return (
    <div className="result-section mission-summary">
      <h3>План миссии</h3>
      <div className="mission-summary-grid">
        <div><strong>{sorties ? sorties.length : "—"}</strong><span>полётных заданий</span></div>
        <p>План показан без браузерных расчётов. Привязка к БВС отображается только при наличии явного идентификатора в ответе backend.</p>
      </div>
      {explicitAssignments.length > 0 && (
        <ul className="assignment-list">
          {explicitAssignments.map((assignment) => <li key={assignment.key}>Задание backend: <strong>{assignment.uavId}</strong></li>)}
        </ul>
      )}
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
  const synthetic = result.state !== "failed" && result.mission_plan !== null && result.mission_plan.test_data === true;
  const icon = presentation.badge === "feasible" ? "✓" : presentation.badge === "infeasible" ? "—" : presentation.badge === "timed_out" ? "◷" : "!";
  return (
    <section className={`card result-card result-${presentation.badge}`} aria-labelledby="result-title">
      <div className="result-hero">
        <div className={`result-icon ${presentation.badge}`} aria-hidden="true">{icon}</div>
        <div><p className="eyebrow">Результат расчёта</p><h2 id="result-title">{presentation.title}</h2><p className="result-summary">{presentation.summary}</p></div>
        <span className={`status-badge ${presentation.badge}`}>{presentation.badge}</span>
      </div>
      {synthetic && <div className="synthetic-notice"><strong>Демонстрационные данные</strong><span>Backend пометил этот план как синтетический — это не реальное полётное задание.</span></div>}
      {result.state === "failed" ? (
        <div className="result-section error-detail"><h3>Сообщение вычислительного контура</h3><p>{failureMessage(result.error)}</p></div>
      ) : (
        <>{result.mission_plan && <MissionPlanSummary plan={result.mission_plan} />}<SolverSummary report={result.solver_report} /></>
      )}
      <details className="raw-response"><summary>Raw response JSON</summary><pre>{JSON.stringify(result, null, 2)}</pre></details>
    </section>
  );
}

function Lifecycle({ observedStates, result }: { observedStates: LifecycleState[]; result: JobResult | null }) {
  return (
    <div className="lifecycle" aria-label="Прогресс задачи">
      <div className={`lifecycle-step ${observedStates.includes("queued") ? "observed" : ""}`}><span>1</span><div><strong>QUEUED</strong><small>Задача принята</small></div></div>
      <div className="lifecycle-line" />
      <div className={`lifecycle-step ${observedStates.includes("running") ? "active" : ""}`}><span>2</span><div><strong>RUNNING</strong><small>Расчёт выполняется</small></div></div>
      <div className="lifecycle-line" />
      <div className={`lifecycle-step ${result ? "terminal" : ""}`}><span>3</span><div><strong>RESULT</strong><small>Ответ backend</small></div></div>
    </div>
  );
}

function FileSummary({ file, onRemove }: { file: KmlFileRecord; onRemove: () => void }) {
  const geometry = file.summary
    ? Object.entries(file.summary.geometry_counts).map(([name, count]) => `${name}: ${count}`).join(" · ")
    : null;
  return (
    <article className={`file-record ${file.status}`}>
      <div className="file-record-head">
        <div><strong>{file.file_name}</strong><span>{CATEGORY_LABELS[file.category]} · {formatFileSize(file.size_bytes)}</span></div>
        <button className="icon-button" type="button" onClick={onRemove} aria-label={`Удалить ${file.file_name}`}>×</button>
      </div>
      {file.status === "error" ? <p className="file-error">{file.error}</p> : file.summary && (
        <div className="file-facts">
          <span className="parse-ok">Прочитан</span>
          <span>{file.summary.document_count.toLocaleString("ru-RU")} Document</span>
          <span>{file.summary.placemark_count.toLocaleString("ru-RU")} Placemark</span>
          <span>{file.summary.coordinate_tuple_count.toLocaleString("ru-RU")} координат</span>
          <span>{file.summary.altitude_coordinate_count ? `Высота: ${file.summary.altitude_coordinate_count.toLocaleString("ru-RU")} координат` : "Без высотных координат"}</span>
          {geometry && <p>{geometry}</p>}
          {file.summary.document_names.length > 0 && <p>Документ: {file.summary.document_names.join("; ")}</p>}
          {file.summary.placemark_name_samples.length > 0 && <p>Примеры: {file.summary.placemark_name_samples.slice(0, 3).join("; ")}</p>}
          {file.summary.placemark_description_samples.length > 0 && <p>Описание: {file.summary.placemark_description_samples[0]}</p>}
          {file.summary.extended_data_fields.length > 0 && <p>Поля KML: {file.summary.extended_data_fields.join(", ")}</p>}
        </div>
      )}
    </article>
  );
}

interface UploadCardProps {
  category: KmlCategory;
  title: string;
  description: string;
  sourceHint: string;
  files: KmlFileRecord[];
  multiple?: boolean;
  loading: boolean;
  onFiles: (files: FileList | null) => void;
  onRemove: (id: string) => void;
}

function UploadCard({ category, title, description, sourceHint, files, multiple = false, loading, onFiles, onRemove }: UploadCardProps) {
  return (
    <div className="upload-card">
      <div className="upload-card-copy"><span className="upload-number">KML</span><div><h3>{title}</h3><p>{description}</p></div></div>
      <label className="file-picker">
        <span>{loading ? "Чтение KML…" : files.length ? "Выбрать снова" : "Выбрать файл"}</span>
        <input
          type="file"
          accept=".kml,application/vnd.google-earth.kml+xml"
          multiple={multiple}
          disabled={loading}
          aria-label={title}
          onChange={(event: ChangeEvent<HTMLInputElement>) => {
            onFiles(event.currentTarget.files);
            event.currentTarget.value = "";
          }}
        />
      </label>
      <small className="source-hint">Пример организатора: {sourceHint}</small>
      <div className="file-list">{files.map((file) => <FileSummary key={file.id} file={file} onRemove={() => onRemove(file.id)} />)}</div>
      {category === "restricted_zones" && <p className="category-note">Высотные и временные ограничения в примере не имеют единого стандартного формата и показываются только как исходные метаданные.</p>}
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  unit,
  placeholder,
  hint,
  integer = false,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  unit?: string;
  placeholder?: string;
  hint?: string;
  integer?: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? formatDecimalInput(value);
  return (
    <label>
      <span>{label}{unit ? `, ${unit}` : ""}</span>
      <input
        type="text"
        inputMode={integer ? "numeric" : "decimal"}
        autoComplete="off"
        spellCheck={false}
        placeholder={placeholder}
        value={shown}
        onChange={(event) => {
          const next = normalizeDecimalDraft(event.target.value);
          setDraft(next);
          const parsed = parseDecimalInput(next);
          if (parsed === null) return;
          if (integer && !Number.isSafeInteger(parsed)) return;
          onChange(parsed);
        }}
        onBlur={() => setDraft(null)}
      />
      {hint ? <small className="field-hint">{hint}</small> : null}
    </label>
  );
}

function BoardCard({
  board,
  index,
  aerodromeCount,
  onChange,
  onRemove,
}: {
  board: BoardInput;
  index: number;
  aerodromeCount: number;
  onChange: (next: BoardInput) => void;
  onRemove: () => void;
}) {
  const cameras = camerasForModel(board.modelId);
  return (
    <article className="uav-card">
      <div className="uav-card-head">
        <div><strong>БВС {index + 1}</strong></div>
        <button className="text-button danger" type="button" onClick={onRemove}>Удалить</button>
      </div>
      <div className="uav-grid">
        <label>
          <span>Модель</span>
          <select value={board.modelId} onChange={(event) => onChange(withModel(board, event.target.value))}>
            <option value="">Выберите модель</option>
            {catalogModels().map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}
          </select>
        </label>
        <label>
          <span>Камера</span>
          <select
            value={board.cameraId}
            disabled={!board.modelId}
            onChange={(event) => onChange({ ...board, cameraId: event.target.value })}
          >
            <option value="">Выберите камеру</option>
            {cameras.map((camera) => <option key={camera.id} value={camera.id}>{cameraOptionLabel(camera)}</option>)}
          </select>
        </label>
        <label>
          <span>Аэродром</span>
          <select
            value={board.aerodromeIndex ?? ""}
            onChange={(event) => onChange({
              ...board,
              aerodromeIndex: event.target.value === "" ? null : Number(event.target.value),
            })}
          >
            <option value="">Выберите аэродром</option>
            {Array.from({ length: aerodromeCount }, (_, aerodromeIndex) => (
              <option key={aerodromeId(aerodromeIndex)} value={aerodromeIndex}>{aerodromeId(aerodromeIndex)}</option>
            ))}
          </select>
        </label>
        <NumberField
          label="Количество"
          unit="шт"
          placeholder="1"
          integer
          value={board.count}
          onChange={(value) => {
            if (!Number.isInteger(value) || value < 1) return;
            onChange({ ...board, count: value });
          }}
        />
      </div>
    </article>
  );
}

export default function App() {
  const api = useMemo(() => createApiClient(), []);
  const [scenarioId, setScenarioId] = useState("demo-multi-uav-001");
  const [aerodromes, setAerodromes] = useState<AerodromeInput[]>(() => DEFAULT_AERODROMES.map((item) => ({ ...item })));
  const [boards, setBoards] = useState<BoardInput[]>(() => DEFAULT_BOARDS.map((item) => ({ ...item })));
  const [surveyType, setSurveyType] = useState<SurveyType>("RGB");
  const [gsdCmPerPx, setGsdCmPerPx] = useState(DEFAULT_GSD_CM_PER_PX);
  const [forwardOverlap, setForwardOverlap] = useState(DEFAULT_FORWARD_OVERLAP);
  const [sideOverlap, setSideOverlap] = useState(DEFAULT_SIDE_OVERLAP);
  const [stripDirectionDeg, setStripDirectionDeg] = useState(DEFAULT_STRIP_DIRECTION_DEG);
  const [windSpeed, setWindSpeed] = useState(3);
  const [windDirection, setWindDirection] = useState(270);
  const [objective, setObjective] = useState(DEFAULT_OBJECTIVE);
  const [timeLimit, setTimeLimit] = useState(Number(DEFAULT_TIME_LIMIT));
  const [seedText, setSeedText] = useState(DEFAULT_SEED);
  const [surveyTask, setSurveyTask] = useState<KmlFileRecord | null>(null);
  const [restrictedZones, setRestrictedZones] = useState<KmlFileRecord | null>(null);
  const [obstacles, setObstacles] = useState<KmlFileRecord[]>([]);
  const [loadingCategory, setLoadingCategory] = useState<KmlCategory | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [result, setResult] = useState<JobResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const [observedStates, setObservedStates] = useState<LifecycleState[]>([]);
  const coordinatorRef = useRef(new RequestCoordinator());
  const fileSequence = useRef(0);

  useEffect(() => () => coordinatorRef.current.cancel(), []);

  const scenarioInputs = useMemo<ScenarioInputs>(() => ({
    scenarioId,
    aerodromes,
    boards,
    surveyType,
    gsdCmPerPx,
    forwardOverlap,
    sideOverlap,
    stripDirectionDeg,
    windSpeedMps: windSpeed,
    windDirectionFromDeg: windDirection,
    surveyTask,
    restrictedZones,
    obstacles,
  }), [scenarioId, aerodromes, boards, surveyType, gsdCmPerPx, forwardOverlap, sideOverlap, stripDirectionDeg, windSpeed, windDirection, surveyTask, restrictedZones, obstacles]);

  function changeAerodromeCount(count: number) {
    setAerodromes((current) => resizeAerodromes(current, count));
    setBoards((current) => clearMissingAerodromes(current, count));
  }

  const scenarioPreview = useMemo(() => {
    try {
      return {
        text: JSON.stringify(buildPrototypeScenario(scenarioInputs, objective), null, 2),
        error: null as string | null,
      };
    } catch (caught) {
      return {
        text: "",
        error: caught instanceof Error ? caught.message : "Не удалось собрать сценарий.",
      };
    }
  }, [scenarioInputs, objective]);
  const optimizationText = useMemo(() => JSON.stringify({ objective, time_limit_seconds: timeLimit }, null, 2), [objective, timeLimit]);

  async function handleKmlFiles(category: KmlCategory, list: FileList | null) {
    const files = Array.from(list ?? []);
    if (!files.length) return;
    setLoadingCategory(category);
    try {
      const records = await Promise.all(files.map((file) => readKmlFile(file, category, `kml-${++fileSequence.current}`)));
      if (category === "survey_task") setSurveyTask(records[0]);
      else if (category === "restricted_zones") setRestrictedZones(records[0]);
      else setObstacles((current) => [...current, ...records]);
    } finally {
      setLoadingCategory(null);
    }
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
      validateScenarioInputs(scenarioInputs);
      const scenario = buildPrototypeScenario(scenarioInputs, objective);
      const optimization = buildOptimization(objective, timeLimit);
      const submitted = await submitFromEditors(api, JSON.stringify(scenario), JSON.stringify(optimization), seedText, signal);
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
            setObservedStates((states) => states.includes(status.state) ? states : [...states, status.state]);
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
          <p className="subtitle">Подготовка групповой миссии БВС на основе KML-геоданных, аэродромов, бортов и выбранного критерия оптимизации.</p>
          <div className="connection-row" aria-label="Состояние приложения">
            <div className="connection-pill ready"><span className="status-dot" /><small>Frontend</small><strong>Готов</strong></div>
            <div className={`connection-pill ${backendTone}`}><span className="status-dot" /><small>Backend / задача</small><strong>{backendLabel}</strong></div>
          </div>
        </div>
        <div className="contract-chip"><span>contract</span><strong>{CONTRACT_VERSION}</strong></div>
      </header>

      <div className="honesty-banner">
        <strong>Prototype scenario profile</strong>
        <p>KML читается локально. В запрос уходят кольца полигонов, аэродромы, борты, GSD, перекрытия и направление полос. Камера берётся из рёбер совместимости выбранной модели. Скорость, батарея, оптика и коэффициенты мощности подставляются на сервере из справочника модели. Маршруты рассчитывает только backend/runtime.</p>
      </div>

      <form onSubmit={handleSubmit} noValidate>
        <section className="card workflow-section" aria-labelledby="source-title">
          <div className="section-heading"><div><p className="eyebrow">01 · Исходные данные</p><h2 id="source-title">Профиль сценария</h2><p className="section-description">Идентификатор нужен для демонстрационного сценария. Внутренняя структура остаётся командным допущением до фиксации общего контракта.</p></div><span className="step-chip">EPSG:4326</span></div>
          <label className="scenario-id-field"><span>Идентификатор сценария</span><input value={scenarioId} onChange={(event) => setScenarioId(event.target.value)} placeholder="demo-multi-uav-001" /></label>
        </section>

        <section className="card workflow-section" aria-labelledby="geo-title">
          <div className="section-heading"><div><p className="eyebrow">02 · Геоданные</p><h2 id="geo-title">KML-файлы организатора</h2><p className="section-description">Исходные файлы остаются в браузере. В запрос попадают кольца: один полигон задания, зоны ограничений и препятствия, чей след пересекает bbox съёмки.</p></div><span className="step-chip">.kml</span></div>
          <div className="upload-grid">
            <UploadCard category="survey_task" title="Границы задания на съёмку" description="Основная область работ. Один файл обязателен для запуска." sourceHint="Границы полетов.kml" files={surveyTask ? [surveyTask] : []} loading={loadingCategory === "survey_task"} onFiles={(files) => void handleKmlFiles("survey_task", files)} onRemove={() => setSurveyTask(null)} />
            <UploadCard category="restricted_zones" title="Зоны ограничений" description="Временные и постоянные запретные зоны из примера организатора." sourceHint="Московская зона.kml" files={restrictedZones ? [restrictedZones] : []} loading={loadingCategory === "restricted_zones"} onFiles={(files) => void handleKmlFiles("restricted_zones", files)} onRemove={() => setRestrictedZones(null)} />
            <UploadCard category="obstacle" title="Высотные препятствия" description="Можно выбрать несколько KML с 3D-примитивами препятствий." sourceHint="obstacles_Московская область.kml; высотные препятствия Приморский край.kml" files={obstacles} multiple loading={loadingCategory === "obstacle"} onFiles={(files) => void handleKmlFiles("obstacle", files)} onRemove={(id) => setObstacles((current) => current.filter((file) => file.id !== id))} />
          </div>
        </section>

        <section className="card workflow-section" aria-labelledby="aerodrome-title">
          <div className="section-heading"><div><p className="eyebrow">03 · Аэродромы</p><h2 id="aerodrome-title">Аэродромы</h2><p className="section-description">Число от 1 до 4. У каждой строки долгота и широта, EPSG:4326. Подпись «аэродром 1» ставит система.</p></div></div>
          <label className="bounded-count"><span>Число аэродромов</span><select value={aerodromes.length} onChange={(event) => changeAerodromeCount(Number(event.target.value))}><option value={1}>1</option><option value={2}>2</option><option value={3}>3</option><option value={4}>4</option></select></label>
          <div className="fleet-list">{aerodromes.map((aerodrome, index) => (
            <article className="uav-card" key={aerodromeId(index)}>
              <div className="uav-card-head"><strong>{aerodromeId(index)}</strong></div>
              <div className="uav-grid">
                <NumberField label="Долгота" unit="°" placeholder="37.6000" value={aerodrome.lon} onChange={(value) => setAerodromes((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, lon: value } : item))} />
                <NumberField label="Широта" unit="°" placeholder="55.7470" value={aerodrome.lat} onChange={(value) => setAerodromes((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, lat: value } : item))} />
              </div>
              <small className="field-hint point-hint">Координаты EPSG:4326.</small>
            </article>
          ))}</div>
        </section>

        <section className="card workflow-section" aria-labelledby="fleet-title">
          <div className="section-heading"><div><p className="eyebrow">04 · Борта</p><h2 id="fleet-title">Борта</h2><p className="section-description">Карточка задаёт модель, совместимую с ней камеру, аэродром и количество одинаковых бортов. Список камер зависит только от модели. Потолка карточек нет.</p></div><button className="secondary-button" type="button" onClick={() => setBoards((current) => addBoard(current))}>+ Добавить борт</button></div>
          <div className="fleet-list">{boards.map((board, index) => <BoardCard key={`board-${index}`} board={board} index={index} aerodromeCount={aerodromes.length} onChange={(next) => setBoards((current) => current.map((item, itemIndex) => itemIndex === index ? next : item))} onRemove={() => setBoards((current) => removeBoard(current, index))} />)}</div>
        </section>

        <section className="card workflow-section" aria-labelledby="survey-title">
          <div className="section-heading"><div><p className="eyebrow">05 · Параметры съёмки</p><h2 id="survey-title">Сенсорный профиль и ветер</h2><p className="section-description">GSD, перекрытия и направление полос задаются здесь и уходят в конверт. Единицы указаны явно. Браузер не рассчитывает покрытие, энергетику или выполнимость. Тип съёмки не фильтрует список камер.</p></div></div>
          <div className="control-grid">
            <label><span>Тип съёмки</span><select value={surveyType} onChange={(event) => setSurveyType(event.target.value as SurveyType)}><option value="RGB">RGB</option><option value="multispectral">Мультиспектральная</option><option value="infrared">Инфракрасная</option><option value="LiDAR">LiDAR</option><option value="geophysical">Геофизическая</option></select></label>
            <NumberField label="GSD" unit="см/пикс" placeholder="3" value={gsdCmPerPx} onChange={setGsdCmPerPx} />
            <NumberField label="Перекрытие вдоль" placeholder="0.7" value={forwardOverlap} onChange={setForwardOverlap} hint="Доля кадра, от 0 до 1, не включая 1." />
            <NumberField label="Перекрытие поперёк" placeholder="0.6" value={sideOverlap} onChange={setSideOverlap} hint="Доля кадра, от 0 до 1, не включая 1." />
            <NumberField label="Направление полос" unit="°" placeholder="0" value={stripDirectionDeg} onChange={setStripDirectionDeg} />
            <NumberField label="Скорость ветра" unit="м/с" placeholder="3" value={windSpeed} onChange={setWindSpeed} />
            <NumberField label="Направление ветра, откуда · °" placeholder="270" value={windDirection} onChange={setWindDirection} hint="0 — север. Значение 360 записывается как 0." />
          </div>
        </section>

        <section className="card workflow-section" aria-labelledby="optimization-title">
          <div className="section-heading"><div><p className="eyebrow">06 · Критерий оптимизации</p><h2 id="optimization-title">Настройки расчёта</h2><p className="section-description">Значения передаются в существующем envelope v0 без браузерной оптимизации.</p></div></div>
          <div className="control-grid">
            <label><span>Критерий</span><select value={objective} onChange={(event) => setObjective(event.target.value)}><option value="min_time">Минимальное время выполнения</option><option value="min_total_flight_time">Минимальный суммарный налёт</option></select><small className="field-hint">scenario.criterion: {objective === "min_total_flight_time" ? "min_flight_hours" : objective}</small></label>
            <NumberField label="Лимит расчёта, с" placeholder={DEFAULT_TIME_LIMIT} value={timeLimit} onChange={setTimeLimit} hint={timeLimit > MAX_TIME_LIMIT_SECONDS ? TIME_LIMIT_TOO_LONG : `Не больше ${MAX_TIME_LIMIT_SECONDS}`} />
            <NumberField label="Seed" placeholder="7" integer value={Number(seedText)} onChange={(value) => setSeedText(formatDecimalInput(value))} hint="Для воспроизводимого запуска." />
          </div>

          <details className="advanced-panel">
            <summary><span>Расширенные настройки / Raw scenario</span><small>Фактическое тело запроса для инженерной проверки</small></summary>
            <p className="advanced-note">Сценарий формируется из полей выше. Исходные KML остаются в памяти браузера; в запрос уходят кольца, аэродромы, борты, GSD, перекрытия, направление полос и ветер. Коэффициенты мощности читает сервер из записи модели.</p>
            {scenarioPreview.error && <p className="file-error">{scenarioPreview.error}</p>}
            <div className="editor-grid"><label><span>Scenario JSON · только чтение</span><textarea readOnly value={scenarioPreview.text} spellCheck={false} rows={18} /></label><label><span>Optimization JSON · только чтение</span><textarea readOnly value={optimizationText} spellCheck={false} rows={18} /></label></div>
          </details>

          <div className="form-footer"><div className="submit-copy"><strong>Проверить профиль и запустить</strong><span>Повторный запуск остановит текущий опрос. Результат и состояния определяет backend.</span></div><button className="primary-button" type="submit" disabled={isSubmitting || loadingCategory !== null}>{isSubmitting ? "Отправляем задачу…" : job ? "Запустить ещё раз" : "Запустить расчёт"}</button></div>
        </section>
      </form>

      {error && <div className="error-banner" role="alert"><span className="error-mark" aria-hidden="true">!</span><div><strong>Не удалось выполнить запрос</strong><span>{error}</span></div></div>}
      {job && <section className="card status-card" aria-labelledby="job-status-title" aria-live="polite"><div className="section-heading"><div><p className="eyebrow">07 · Статус задачи</p><h2 id="job-status-title">Ход выполнения</h2></div><span className={`status-badge ${job.state}`}>{STATE_LABELS[job.state]}</span></div><Lifecycle observedStates={observedStates} result={result} /><dl className="job-details"><div className="job-id-row"><dt>Job ID</dt><dd>{job.job_id}</dd></div><div><dt>Создано</dt><dd>{formatTimestamp(job.created_at)}</dd></div><div><dt>Запущено</dt><dd>{formatTimestamp(job.started_at)}</dd></div><div><dt>Завершено</dt><dd>{formatTimestamp(job.finished_at)}</dd></div></dl>{isPolling && <div className="polling-indicator"><span className="pulse" /> Backend выполняет задачу, статус обновляется автоматически</div>}</section>}
      {result && <ResultPanel result={result} />}
      <footer>Интерфейс отображает авторитетный ответ backend. Импорт KML не является проверкой геометрии, безопасности или выполнимости полёта.</footer>
    </main>
  );
}
