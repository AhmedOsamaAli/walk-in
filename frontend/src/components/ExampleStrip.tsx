import { useId } from "react";
import { EXAMPLES_URL } from "../lib/routes";
import { preloadLink, usePreloadWhenIdle } from "../preload";
import { exampleChips, exampleLead, exampleLinks, useExamples } from "../state/examples";
import "../styles/examples.css";
import { Link } from "./Link";

const SHOWN = 3;

/**
 * "See a finished example": up to three finished surveys, each opening as it ended, and the way to them all. Nothing
 * shows until they have loaded, nor when there are none. `after` says it follows the brief a chosen site reveals. Once
 * the first screen is idle, their surveys and kits are fetched ahead (the code that shows them loads with the app), and
 * pointing at one fetches its kit too, so either opens from memory.
 */
export function ExampleStrip({ after = false }: { after?: boolean }) {
  const id = useId();
  const { list } = useExamples();
  const shown = list.slice(0, SHOWN);
  usePreloadWhenIdle(shown.flatMap(exampleLinks), { code: false });
  if (!shown.length) return null;
  return (
    <section className="ex-strip" aria-labelledby={`${id}-title`} data-after={after ? "" : undefined}>
      <div className="ex-strip-head">
        <h2 className="ex-strip-title mono" id={`${id}-title`}>
          See a finished example
        </h2>
        <Link className="ex-strip-all mono" href={EXAMPLES_URL}>
          See all examples <span aria-hidden="true">→</span>
        </Link>
      </div>
      <ol className="ex-cards">
        {shown.map((example) => {
          const lead = exampleLead(example);
          const tags = exampleChips(example);
          const kit = example.kit?.url;
          return (
            <li key={example.run_id}>
              <Link
                className="ex-card"
                href={example.url}
                title={example.label}
                aria-label={`${example.label}, ${tags.join(", ")}${lead ? `: ${lead}` : ""}`}
                onPointerEnter={() => {
                  if (kit) preloadLink(kit, { code: false });
                }}
                onFocus={() => {
                  if (kit) preloadLink(kit, { code: false });
                }}
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
