import type { DonePayload } from "../api/types";
import { dataAsOfText, queriesText, secondsText } from "../lib/format";
import type { LogLine } from "../state/survey";
import { SectionHead } from "./SectionHead";

interface SurveyLogProps {
  log: LogLine[];
  summary: DonePayload | null;
}

/** Newest line first; a step's line stays where it started and turns from running to a check mark with its time. */
export function SurveyLog({ log, summary }: SurveyLogProps) {
  const asOf = summary ? dataAsOfText(summary.data_as_of) : null;
  return (
    <section id="s-log" className="sec reveal">
      <SectionHead no="01" title="Survey log" />
      {summary ? (
        <p className="log-meta mono">
          {secondsText(summary.seconds)} · {queriesText(summary)}
          {asOf ? ` · ${asOf}` : ""}
        </p>
      ) : null}
      <ol className="log mono" reversed>
        {log.toReversed().map((line) => (
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
    </section>
  );
}
