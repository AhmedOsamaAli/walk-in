import { useState } from "react";
import { EXAMPLES_URL } from "../lib/routes";
import "../styles/examples.css";

/**
 * One quiet line under the survey's status while it runs: a finished example opens in a new tab, so this survey runs
 * on here. Once the survey ends the line folds away; a survey shown after it ended never has it.
 */
export function ExampleWait({ running }: { running: boolean }) {
  const [seen, setSeen] = useState(running);
  if (running && !seen) setSeen(true);
  if (!seen) return null;
  return (
    <div className="ex-wait" data-done={running ? undefined : ""} inert={!running}>
      <div>
        <p>
          While you wait,{" "}
          <a href={EXAMPLES_URL} target="_blank" rel="noopener">
            see a finished example
            <span aria-hidden="true"> ↗</span>
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
        </p>
      </div>
    </div>
  );
}
