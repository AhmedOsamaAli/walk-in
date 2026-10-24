import { use, type ReactNode } from "react";
import { JourneyContext } from "../lib/journey";
import { isPlainClick } from "../lib/navigation";
import { nextAction, type SurveyTab } from "../lib/surveyTabs";

/**
 * A "next" link to another tab of the survey: a plain click shows that tab, its top in view and its heading in focus;
 * the link's address names the tab, so it can also be opened or copied.
 */
export function TabLink({ to, children }: { to: SurveyTab; children: ReactNode }) {
  const journey = use(JourneyContext);
  return (
    <a
      className="sec-next-link"
      href={`#${to}`}
      onClick={(event) => {
        if (!journey || !isPlainClick(event)) return;
        event.preventDefault();
        journey.show(to);
      }}
    >
      {children}
    </a>
  );
}

/**
 * The last line of the evidence tabs and the log: back to what the owner can act on, the concepts or the moves. It shows
 * once they are on the page (styles/journey.css).
 */
export function NextAction() {
  const journey = use(JourneyContext);
  if (!journey) return null;
  const { tab, line, label, gate } = nextAction(journey.intent);
  return (
    <p className="sec-next" data-next-to={gate}>
      <b className="sec-next-label mono">Next</b>
      <span>{line}</span>
      <TabLink to={tab}>{label}</TabLink>
    </p>
  );
}
