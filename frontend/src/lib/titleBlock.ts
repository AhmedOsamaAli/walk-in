/* A survey's title block, like a drawing's: the site's name, an eyebrow that says what is under survey, and four fields
   (coordinates, catchment, what was asked, the constraints), as the live survey sets them and as a restored one
   rebuilds them from its record. */
import type { PlaceHit, RunRequest, Verdict, Walk } from "../api/types";
import { askedLine, briefOf, catchmentLines, runRequest, unitLine } from "../state/brief";
import type { SurveyState } from "../state/survey";
import { fmtLat, fmtLon, VERDICT_STAMPS } from "./format";
import { siteName } from "./fullmap";

export interface TitleField {
  label: string;
  /** One entry per line, so a value breaks where it should, never mid-coordinate. */
  lines: readonly string[];
  /** Coordinates and other measured values read best in the drafting face. */
  mono?: boolean;
}

/** The site as the survey view names it, fixed when the survey starts. */
export interface Surveyed {
  label: string;
  eyebrow: string;
  fields: TitleField[];
}

const NOTES_SHOWN = 60;
export const EYEBROWS = { explore: "Site under survey", open: "Idea under test", improve: "Place under review" } as const;

/**
 * Four fields, like a drawing's title block; the unit rides under the constraints. The catchment names the area in the
 * server's words once it is traced (`walk`), its size, and the age focus ("For 25–34").
 */
export function briefFields(run: RunRequest, walk: Walk | null, place: PlaceHit | null): TitleField[] {
  const notes = run.notes.length > NOTES_SHOWN ? `${run.notes.slice(0, NOTES_SHOWN - 1).trimEnd()}…` : run.notes;
  const asked = askedLine(run, place);
  const unit = unitLine(run);
  return [
    { label: "Coordinates", lines: [fmtLat(run.lat), fmtLon(run.lon)], mono: true },
    { label: "Catchment", lines: catchmentLines(run, walk) },
    { label: asked.label, lines: [asked.line] },
    run.intent === "improve"
      ? { label: "Compared with", lines: ["The places people here love in its category"] }
      : { label: "Constraints", lines: unit ? [notes || "None", unit] : [notes || "None"] },
  ];
}

/** Once the server has read the owner's notes, the title block shows the rules it applies rather than the raw text. */
export function withUnderstood(fields: TitleField[], understood: string[]): TitleField[] {
  if (!understood.length) return fields;
  const rules = understood.map((rule) => rule.charAt(0).toUpperCase() + rule.slice(1)).join(" · ");
  return fields.map((field) => (field.label === "Constraints" ? { ...field, lines: [rules, ...field.lines.slice(1)] } : field));
}

/** The verdict on the owner's idea joins the idea in the title block, so the answer is at the top of the page. */
export function withVerdict(fields: TitleField[], verdict: Verdict | null): TitleField[] {
  if (!verdict) return fields;
  return fields.map((field) =>
    field.label === "Your idea" ? { ...field, lines: [...field.lines, `Verdict: ${VERDICT_STAMPS[verdict.level]}`] } : field,
  );
}

/** A restored survey's title block, rebuilt from the brief its run recorded, as the live one would have read. */
export function recordedTitle(survey: SurveyState): Surveyed {
  if (!survey.site) return { label: "Survey in progress", eyebrow: EYEBROWS[survey.intent], fields: [] };
  const brief = briefOf(survey.site, survey.place);
  const run = runRequest(brief.site, brief.form);
  const name = siteName(brief.site);
  const label = run.intent === "improve" ? (survey.place?.name ?? name) : name;
  const fields = briefFields(run, survey.catchment, brief.form.place);
  return { label, eyebrow: EYEBROWS[run.intent], fields };
}
