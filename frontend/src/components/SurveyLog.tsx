import { useId, useState } from "react";
import type { DonePayload } from "../api/types";
import { dataAsOfText, queriesText, secondsText } from "../lib/format";
import { FOLDED_LINES, logView } from "../lib/log";
import type { LogLine } from "../state/survey";
import { SectionHead } from "./SectionHead";
import { NextAction } from "./TabLink";

interface SurveyLogProps {
  /** Its tab's place in the bar: the log is the last tab. */
  no: string;
  log: LogLine[];
  summary: DonePayload | null;
}

/**
 * Newest line first; a step's line stays where it started and turns from running to a check mark with its time. Folded
 * to its newest lines until the owner opens it, so the results are not pushed down a long list.
 */
export function SurveyLog({ no, log, summary }: SurveyLogProps) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const asOf = summary ? dataAsOfText(summary.data_as_of) : null;
  const { shown } = logView(log, open);
  const folds = log.length > FOLDED_LINES;
  return (
    <section id="s-log" className="sec reveal">
      <SectionHead no={no} title="Survey log" />
      {summary ? (
        <p className="log-meta mono">
          {secondsText(summary.seconds)} · {queriesText(summary)}
          {asOf ? ` · ${asOf}` : ""}
        </p>
      ) : null}
      <ol className="log mono" reversed id={listId}>
        {shown.map((line) => (
          <li key={line.id} className={line.kind}>
            <div className="log-clip">
              <div className="log-row">
                <span className="t">{secondsText(line.at)}</span>
                <span className="msg">{line.kind === "warn" ? <span className="hl">{line.text}</span> : line.text}</span>
                <span className="state">{line.status}</span>
              </div>
            </div>
          </li>
        ))}
      </ol>
      {folds ? (
        <button
          className="log-toggle sec-next-link"
          type="button"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => {
            setOpen((value) => !value);
          }}
        >
          {open ? "Show only the latest" : `Show all ${log.length} lines`}
        </button>
      ) : null}
      <NextAction />
    </section>
  );
}
