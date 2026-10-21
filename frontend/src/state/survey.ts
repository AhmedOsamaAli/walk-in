import type {
  BaselineConcept,
  BlockPayload,
  ConceptsPayload,
  DonePayload,
  GapRow,
  ImprovePayload,
  Intent,
  PlaceCard,
  StatusPayload,
  StepState,
  SurveyEvent,
  TastePayload,
  Verdict,
  Walk,
} from "../api/types";
import { agentText, replayText, secondsText, VERDICT_STAMPS } from "../lib/format";

/** Each intent's fixed pipeline. Only these steps move the progress bar: the agent's "agent-N" steps vary in number. */
export const PIPELINE_STEPS: Record<Intent, readonly string[]> = {
  explore: ["walk", "block", "demand", "taste", "gaps", "concepts"],
  open: ["walk", "block", "demand", "taste", "gaps", "verdict", "concepts"],
  improve: ["place", "walk", "block", "demand", "taste", "gaps", "improve"],
};

/** Steps of features removed from the product as inaccurate, which older servers still report. */
const RETIRED_STEPS: ReadonlySet<string> = new Set(["crowd"]);

export type LogKind = "info" | "running" | "done" | "failed" | "agent" | "finding" | "warn" | "err";

export interface LogLine {
  id: number;
  /** Seconds since the survey started. */
  at: number;
  kind: LogKind;
  text: string;
  /** The right-hand column: "Run" while a step runs, then a check mark and its time. */
  status: string;
}

export interface Step {
  step: string;
  label: string;
  state: StepState;
  line: number;
}

export type SurveyStatus = "idle" | "running" | "complete" | "failed";

export interface SurveyState {
  /** Counts runs, so views can tell a new run from an update of the same one. */
  run: number;
  intent: Intent;
  status: SurveyStatus;
  /** The event stream is open; it can outlast "complete" while late events arrive. */
  streaming: boolean;
  /** performance.now() when the run started. */
  startedAt: number;
  runId: string | null;
  log: LogLine[];
  steps: Step[];
  /** The owner's place, when improving it. */
  place: PlaceCard | null;
  catchment: Walk | null;
  block: BlockPayload | null;
  cues: string[] | null;
  gaps: GapRow[] | null;
  openGap: number | null;
  verdict: Verdict | null;
  improve: ImprovePayload | null;
  concepts: ConceptsPayload | null;
  baseline: BaselineConcept[];
  taste: TastePayload | null;
  summary: DonePayload | null;
  /** The owner's notes as the server understood them. */
  understood: string[];
  /** The latest action or finding, for the live status. */
  latest: string | null;
  error: string | null;
}

export const initialSurvey: SurveyState = {
  run: 0,
  intent: "explore",
  status: "idle",
  streaming: false,
  startedAt: 0,
  runId: null,
  log: [],
  steps: [],
  place: null,
  catchment: null,
  block: null,
  cues: null,
  gaps: null,
  openGap: null,
  verdict: null,
  improve: null,
  concepts: null,
  baseline: [],
  taste: null,
  summary: null,
  understood: [],
  latest: null,
  error: null,
};

export type SurveyAction =
  | { type: "start"; startedAt: number; intent?: Intent }
  | { type: "event"; event: SurveyEvent; at: number }
  | { type: "failed"; message: string; at: number }
  | { type: "closed"; at: number }
  | { type: "toggleGap"; index: number }
  | { type: "reset" };

function append(state: SurveyState, line: Omit<LogLine, "id">): SurveyState {
  return { ...state, log: [...state.log, { ...line, id: state.log.length }] };
}

function note(state: SurveyState, at: number, kind: LogKind, text: string): SurveyState {
  return { ...append(state, { at, kind, text, status: "" }), latest: text };
}

function settle(state: SurveyState, step: string, phase: Exclude<StepState, "running">, at: number): SurveyState {
  const record = state.steps.find((item) => item.step === step);
  if (record?.state !== "running") return state;
  return {
    ...state,
    steps: state.steps.map((item) => (item === record ? { ...item, state: phase } : item)),
    log: state.log.map((line) =>
      line.id === record.line
        ? { ...line, kind: phase, status: phase === "done" ? `✓ ${secondsText(at)}` : "✕" }
        : line,
    ),
  };
}

function onStatus(state: SurveyState, { step, state: phase, label }: StatusPayload, at: number): SurveyState {
  if (RETIRED_STEPS.has(step)) return state;
  let next = state;
  if (!next.steps.some((item) => item.step === step)) {
    const line = next.log.length;
    next = append(next, { at, kind: "running", text: label, status: "Run" });
    next = { ...next, steps: [...next.steps, { step, label, state: "running", line }] };
  }
  return phase === "running" ? next : settle(next, step, phase, at);
}

/** Steps still running when a run ends will never finish. */
function abandon(state: SurveyState, at: number): SurveyState {
  return state.steps.reduce((next, item) => settle(next, item.step, "failed", at), state);
}

function stop(state: SurveyState, message: string, at: number): SurveyState {
  const failed = { ...note(abandon(state, at), at, "err", message), status: "failed" as const, streaming: false };
  return { ...failed, error: message };
}

function onEvent(state: SurveyState, event: SurveyEvent, at: number): SurveyState {
  switch (event.event) {
    case "run": {
      const mode = event.data.llm ? "LLM agent with Qloo tools" : "evidence rules (no LLM key set)";
      const understood = event.data.understood ?? [];
      const started = note({ ...state, runId: event.data.run_id, understood }, at, "info", `Survey ${event.data.run_id} started · ${mode}`);
      return understood.length ? note(started, at, "info", `Read from your notes: ${understood.join(", ")}`) : started;
    }
    case "status":
      return onStatus(state, event.data, at);
    case "place": {
      const { place } = event.data;
      const genre = place.genres?.[0];
      return note({ ...state, place }, at, "finding", `Found ${place.name ?? "your place"} on Qloo${genre ? ` · ${genre}` : ""}`);
    }
    case "catchment":
      return { ...state, catchment: event.data };
    case "agent":
      return note(state, at, "agent", agentText(event.data));
    case "replay":
      return note(state, at, "finding", replayText(event.data));
    case "finding":
      return note(state, at, "finding", event.data.text);
    case "explored": {
      const row = event.data.row;
      if (!row) return state;
      const text = `Tested live: ${row.genre} scores ${row.gap_score} · ${row.nearby_count} inside the walk, ~${row.expected_nearby ?? "?"} typical`;
      return note({ ...state, gaps: [...(state.gaps ?? []), row] }, at, "finding", text);
    }
    case "block":
      return { ...state, block: event.data };
    case "demand":
      return { ...state, cues: event.data.cues ?? [] };
    case "gaps": {
      const rows = event.data.rows ?? [];
      return { ...state, gaps: rows, openGap: rows.length ? 0 : null };
    }
    case "taste":
      return { ...state, taste: event.data };
    case "verdict":
      return note({ ...state, verdict: event.data }, at, "finding", `Verdict · ${VERDICT_STAMPS[event.data.level]} · ${event.data.headline}`);
    case "improve": {
      const data = event.data;
      const text = "note" in data ? data.note : `${data.moves.length} ${data.moves.length === 1 ? "move" : "moves"} from the places locals love`;
      return note({ ...state, improve: data }, at, "finding", text);
    }
    case "concepts":
      return { ...state, concepts: event.data };
    case "baseline":
      return { ...state, baseline: event.data.concepts ?? [] };
    case "notice":
      return note(state, at, "warn", event.data.message);
    case "error":
      return { ...note(state, at, "err", event.data.message), error: event.data.message };
    case "done": {
      const failed = state.error !== null;
      const ended = append(abandon(state, at), {
        at,
        kind: failed ? "failed" : "done",
        text: failed ? "Survey stopped" : "Survey complete",
        status: failed ? "✕" : "✓",
      });
      return { ...ended, summary: event.data, status: failed ? "failed" : "complete" };
    }
  }
}

export function surveyReducer(state: SurveyState, action: SurveyAction): SurveyState {
  switch (action.type) {
    case "start":
      return {
        ...initialSurvey,
        run: state.run + 1,
        intent: action.intent ?? "explore",
        status: "running",
        streaming: true,
        startedAt: action.startedAt,
      };
    case "event":
      return onEvent(state, action.event, action.at);
    case "failed":
      if (state.status !== "running") return { ...note(state, action.at, "err", action.message), streaming: false };
      return stop(state, action.message, action.at);
    case "closed":
      if (state.status === "running") return stop(state, "The survey stream closed before the survey finished.", action.at);
      return { ...state, streaming: false };
    case "toggleGap":
      return { ...state, openGap: state.openGap === action.index ? null : action.index };
    case "reset":
      return { ...initialSurvey, run: state.run };
  }
}

/** Share of the intent's fixed pipeline that is done, from 0 to 1. */
export function surveyProgress(state: SurveyState): number {
  if (state.status === "complete") return 1;
  const pipeline = PIPELINE_STEPS[state.intent];
  const done = state.steps.filter((item) => item.state === "done" && pipeline.includes(item.step)).length;
  return done / pipeline.length;
}

/** The step to show as current: the latest one still running, else the latest one. */
export function currentStep(state: SurveyState): Step | null {
  return state.steps.findLast((item) => item.state === "running") ?? state.steps.at(-1) ?? null;
}
