import type { DonePayload } from "../api/types";
import { secondsText } from "../lib/format";
import type { LogLine } from "../state/survey";
import { SectionHead } from "./SectionHead";

interface SurveyLogProps {
  log: LogLine[];
  summary: DonePayload | null;
}

/** Newest line first; a step's line stays where it started and turns from running to a check mark with its time. */
export function SurveyLog({ log, summary }: SurveyLogProps) {
  return (
    <section id="s-log" className="sec reveal">
      <SectionHead no="01" title="Survey log" />
      {summary ? (
        <p className="log-meta mono">
          {secondsText(summary.seconds)} · {summary.qloo_calls} Qloo calls · {summary.cache_hits} served from cache
        </p>
      ) : null}
      <ol className="log mono" reversed>
        {log.toReversed().map((line) => (
          <li key={line.id} className={line.kind}>
            <div className="log-clip">
              <div className="log-row">
                <span className="t">{secondsText(line.at)}</span>
                <span className="msg">{line.text}</span>
                <span className="state">{line.status}</span>
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
