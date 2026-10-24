import { useId } from "react";
import { EXAMPLES_URL } from "../lib/routes";
import { exampleChips, exampleLead, useExamples } from "../state/examples";
import "../styles/examples.css";
import { Link } from "./Link";

const SHOWN = 3;

/**
 * "See a finished example": up to three finished surveys, each opening as it ended, and the way to them all. Nothing
 * shows until they have loaded, nor when there are none. `after` says it follows the brief a chosen site reveals.
 */
export function ExampleStrip({ after = false }: { after?: boolean }) {
  const id = useId();
  const { list } = useExamples();
  if (!list.length) return null;
  return (
    <section className="ex-strip" aria-labelledby={`${id}-title`} data-after={after ? "" : undefined}>
      <div className="ex-strip-head">
        <h2 className="ex-strip-title mono" id={`${id}-title`}>
          See a finished example
        </h2>
        <Link className="ex-strip-all mono" href={EXAMPLES_URL}>
          All examples <span aria-hidden="true">→</span>
        </Link>
      </div>
      <ol className="ex-cards">
        {list.slice(0, SHOWN).map((example) => {
          const lead = exampleLead(example);
          const tags = exampleChips(example);
          return (
            <li key={example.run_id}>
              <Link
                className="ex-card"
                href={example.url}
                title={example.label}
                aria-label={`${example.label}, ${tags.join(", ")}${lead ? `: ${lead}` : ""}`}
              >
                <span className="ex-card-site">{example.label}</span>
                <span className="ex-card-tags mono">{tags.join(" · ")}</span>
                {lead ? <span className="ex-card-lead">{lead}</span> : null}
              </Link>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
