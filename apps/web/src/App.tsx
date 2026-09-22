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
import { CONTRACT_VERSION, type JobResult, type JobStatus, type JsonObject } from "./types";

const DEFAULT_SCENARIO = `{
  "name": "Demo mission"
}`;

const DEFAULT_OPTIMIZATION = `{
  "test_outcome": "feasible"
}`;

function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatError(error: unknown): string {
  if (error instanceof InputError) return error.message;
  if (error instanceof ApiError) {
    const context = error.status ? ` (HTTP ${error.status}, ${error.code})` : ` (${error.code})`;
    return `${error.message}${context}`;
  }
  if (error instanceof Error) return error.message;
  return "Unexpected client error.";
}

function JsonPanel({ title, value }: { title: string; value: unknown }) {
  return (
    <section className="json-panel">
      <h3>{title}</h3>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </section>
  );
}

function ResultPanel({ result }: { result: JobResult }) {
  const presentation = getResultPresentation(result);
  if (result.state === "failed") {
    return (
      <section className="card result-card result-failed" aria-labelledby="result-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Terminal result</p>
            <h2 id="result-title">{presentation.title}</h2>
          </div>
          <span className="status-badge failed">failed</span>
        </div>
        <p className="result-summary">{presentation.summary}</p>
        <JsonPanel title="Backend error" value={result.error} />
      </section>
    );
  }

  const synthetic =
    result.mission_plan !== null &&
    (result.mission_plan as JsonObject).test_data === true;
  return (
    <section
      className={`card result-card result-${result.outcome}`}
      aria-labelledby="result-title"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">Terminal result</p>
          <h2 id="result-title">{presentation.title}</h2>
        </div>
        <span className={`status-badge ${result.outcome}`}>{result.outcome}</span>
      </div>

      {synthetic && (
        <div className="synthetic-notice">
          Test data only — this plan is synthetic and is not a flyable UAV mission.
        </div>
      )}
      <p className="result-summary">{presentation.summary}</p>

      {result.mission_plan && <JsonPanel title="Mission plan" value={result.mission_plan} />}
      <JsonPanel title="Solver report" value={result.solver_report} />
      {result.artifacts.length > 0 && <JsonPanel title="Artifacts" value={result.artifacts} />}
    </section>
  );
}

export default function App() {
  const api = useMemo(() => createApiClient(), []);
  const [scenarioText, setScenarioText] = useState(DEFAULT_SCENARIO);
  const [optimizationText, setOptimizationText] = useState(DEFAULT_OPTIMIZATION);
  const [seedText, setSeedText] = useState("17");
  const [job, setJob] = useState<JobStatus | null>(null);
  const [result, setResult] = useState<JobResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const coordinatorRef = useRef(new RequestCoordinator());

  useEffect(
    () => () => {
      coordinatorRef.current.cancel();
    },
    [],
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const { generation, signal } = coordinatorRef.current.begin();

    setError(null);
    setResult(null);
    setJob(null);
    setIsPolling(false);
    setIsSubmitting(true);

    try {
      const submitted = await submitFromEditors(
        api,
        scenarioText,
        optimizationText,
        seedText,
        signal,
      );
      if (!coordinatorRef.current.isCurrent(generation)) return;
      setJob(submitted);
      setIsSubmitting(false);
      setIsPolling(true);

      const terminalResult = await pollJobLifecycle({
        api,
        jobId: submitted.job_id,
        signal,
        onStatus: (status) => {
          if (coordinatorRef.current.isCurrent(generation)) setJob(status);
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

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">Asynchronous planning prototype</p>
          <h1>UAV Mission Planner</h1>
          <p className="subtitle">
            Submit a scenario, follow its backend lifecycle, and inspect the authoritative result.
          </p>
        </div>
        <div className="contract-chip">
          <span>Contract</span>
          <strong>{CONTRACT_VERSION}</strong>
        </div>
      </header>

      <section className="card form-card" aria-labelledby="job-form-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Job input</p>
            <h2 id="job-form-title">Configure a lifecycle run</h2>
          </div>
          <span className="api-route">POST /api/jobs</span>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="editor-grid">
            <label>
              <span>Scenario JSON</span>
              <textarea
                value={scenarioText}
                onChange={(event) => setScenarioText(event.target.value)}
                spellCheck={false}
                rows={9}
              />
            </label>
            <label>
              <span>Optimization JSON</span>
              <textarea
                value={optimizationText}
                onChange={(event) => setOptimizationText(event.target.value)}
                spellCheck={false}
                rows={9}
              />
            </label>
          </div>

          <div className="form-footer">
            <label className="seed-field">
              <span>Deterministic seed</span>
              <input
                type="number"
                step="1"
                value={seedText}
                onChange={(event) => setSeedText(event.target.value)}
              />
            </label>
            <div className="form-action">
              <p>Submitting another job cancels the previous poll.</p>
              <button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "Submitting…" : job ? "Run another optimization" : "Run optimization"}
              </button>
            </div>
          </div>
        </form>
      </section>

      {error && (
        <div className="error-banner" role="alert">
          <strong>Request failed</strong>
          <span>{error}</span>
        </div>
      )}

      {job && (
        <section className="card status-card" aria-labelledby="job-status-title" aria-live="polite">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Job state</p>
              <h2 id="job-status-title">Backend lifecycle</h2>
            </div>
            <span className={`status-badge ${job.state}`}>{job.state}</span>
          </div>

          <dl className="job-details">
            <div className="job-id-row">
              <dt>Job ID</dt>
              <dd>{job.job_id}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{formatTimestamp(job.created_at)}</dd>
            </div>
            <div>
              <dt>Started</dt>
              <dd>{formatTimestamp(job.started_at)}</dd>
            </div>
            <div>
              <dt>Finished</dt>
              <dd>{formatTimestamp(job.finished_at)}</dd>
            </div>
          </dl>

          {isPolling && (
            <div className="polling-indicator">
              <span className="pulse" /> Polling the backend without overlapping requests…
            </div>
          )}
        </section>
      )}

      {result && <ResultPanel result={result} />}

      <footer>
        Lifecycle client only. Route calculation and feasibility decisions stay in the backend engine.
      </footer>
    </main>
  );
}
