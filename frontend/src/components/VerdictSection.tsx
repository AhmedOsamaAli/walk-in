import type { Verdict } from "../api/types";
import { VERDICT_STAMPS } from "../lib/format";
import { SectionHead } from "./SectionHead";

/** What happens next, by verdict: a measurable idea that fits leads the concepts. */
function nextLine(verdict: Verdict): string {
  if (verdict.level === "unknown") return "Qloo has no category for it, so the concepts below are the block's strongest gaps.";
  if (verdict.level === "misfit") return "The concepts below are the strongest gaps that the unit and your notes allow.";
  return "It leads the concepts below, designed to win here, next to the two strongest alternatives.";
}

/** Where the idea ranks among the site's gaps: strongest on the left, its own tick marked. */
function Scale({ position, of }: { position: number; of: number }) {
  return (
    <div className="scale" role="img" aria-label={`#${position} of ${of} categories measured, ranked by gap score`}>
      <div className="scale-ticks" aria-hidden="true">
        {Array.from({ length: of }, (_, index) => (
          <i key={index} className={index + 1 === position ? "here" : undefined}>
            {index + 1 === position ? <b className="mono">#{position}</b> : null}
          </i>
        ))}
      </div>
      <div className="scale-ends mono" aria-hidden="true">
        <span>Strongest gap</span>
        <span>Weakest of {of}</span>
      </div>
    </div>
  );
}

export function VerdictSection({ no, verdict }: { no: string; verdict: Verdict }) {
  const subject = verdict.found && verdict.genre ? verdict.genre : verdict.query;
  return (
    <section id="s-verdict" className="sec reveal verdict" data-level={verdict.level}>
      <SectionHead
        no={no}
        title={`Your idea: ${subject}`}
        note="The business you asked about, measured like every other category on the block and ranked among them."
      />
      <div className="verdict-card">
        <p className="stamp mono">{VERDICT_STAMPS[verdict.level]}</p>
        <p className="verdict-headline">{verdict.headline}</p>
        {verdict.position && verdict.of ? <Scale position={verdict.position} of={verdict.of} /> : null}
        {verdict.evidence.length ? (
          <ul className="why-list">
            {verdict.evidence.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : null}
        <p className="verdict-next serif">{nextLine(verdict)}</p>
      </div>
    </section>
  );
}
