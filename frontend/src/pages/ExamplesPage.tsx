import type { Example, Intent } from "../api/types";
import { freshClick } from "../components/ExampleBanner";
import { Link } from "../components/Link";
import { Page, PageHead, useDocumentTitle, useFocusOnMount } from "../components/Page";
import { cssVars } from "../lib/css";
import { INTENTS } from "../lib/format";
import { BRIEF_URL } from "../lib/routes";
import { exampleFound, exampleTesting, exampleWho, useExamples } from "../state/examples";
import "../styles/examples.css";

const isIntent = (value: string): value is Intent => Object.hasOwn(INTENTS, value);

/** One finished survey: where, what it found and the concepts it designed, with the links that open them. */
function ExampleCard({ example, index }: { example: Example; index: number }) {
  const who = exampleWho(example);
  const testing = exampleTesting(example);
  const [lead, ...others] = example.concepts;
  const titleId = `ex-${example.run_id}`;
  return (
    <li style={cssVars({ "--i": index })}>
      <article className="ex-item" aria-labelledby={titleId}>
        <header>
          <p className="ex-kicker mono">{isIntent(example.intent) ? INTENTS[example.intent].label : "Survey"}</p>
          <h2 className="ex-site" id={titleId}>
            {example.label}
          </h2>
          <p className="ex-tags mono">{[example.area, who].filter(Boolean).join(" · ")}</p>
        </header>
        {testing ? (
          <div className="ex-idea">
            <p className="ex-idea-what">{testing}</p>
            {example.verdict ? <p className="ex-verdict serif">{example.verdict}</p> : null}
          </div>
        ) : null}
        <dl className="ex-facts">
          <div>
            <dt className="mono">What it found</dt>
            <dd>{exampleFound(example)}</dd>
          </div>
          {lead ? (
            <div>
              <dt className="mono">{example.concepts.length === 1 ? "Concept" : "Concepts"}</dt>
              <dd>
                <span className="hl">{lead}</span>
                {others.map((name) => ` · ${name}`).join("")}
              </dd>
            </div>
          ) : null}
        </dl>
        <div className="ex-links">
          <Link className="ink-button" href={example.url}>
            Open the survey <span aria-hidden="true">→</span>
          </Link>
          {example.kit ? (
            <p className="ex-kit-links">
              <Link className="text-link" href={example.kit.url}>
                Launch kit <span aria-hidden="true">→</span>
              </Link>
              <Link className="text-link" href={example.kit.report_url}>
                Report <span aria-hidden="true">→</span>
              </Link>
            </p>
          ) : null}
        </div>
      </article>
    </li>
  );
}

/** "See what you get": the finished examples, free to open, before running a survey of one's own. */
export function ExamplesPage({ onFresh }: { onFresh: () => void }) {
  const { phase, list } = useExamples();
  const titleRef = useFocusOnMount();
  useDocumentTitle("Examples");

  return (
    <Page className="examples-page">
      <PageHead
        eyebrow="Examples · Finished surveys"
        title="See what you get"
        titleRef={titleRef}
        standfirst="Finished surveys, so you can see what Walk-in gives before you run one. Opening them costs nothing."
      />
      <section className="pg-sec" aria-label="Finished surveys" aria-busy={phase === "loading"}>
        {phase === "loading" ? (
          <div className="ex-wait-cards" aria-hidden="true">
            <div className="sk" />
            <div className="sk" />
            <div className="sk" />
          </div>
        ) : null}
        {list.length ? (
          <ol className="ex-list">
            {list.map((example, index) => (
              <ExampleCard key={example.run_id} example={example} index={index} />
            ))}
          </ol>
        ) : null}
        <div className="ex-own">
          <a className="go" href={BRIEF_URL} onClick={freshClick(onFresh)}>
            <span>Survey your own storefront</span>
            <i aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M4 12h15M13 6l6 6-6 6" />
              </svg>
            </i>
          </a>
        </div>
      </section>
    </Page>
  );
}
