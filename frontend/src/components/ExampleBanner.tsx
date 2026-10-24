import type { MouseEvent } from "react";
import type { Example } from "../api/types";
import { isPlainClick } from "../lib/navigation";
import { BRIEF_URL } from "../lib/routes";
import "../styles/examples.css";

interface ExampleBannerProps {
  example: Example;
  /** "Survey your own storefront": a fresh brief at "/". */
  onFresh: () => void;
  /** Over a page of its own (a kit, its report) rather than the survey's sheet. */
  page?: boolean;
}

/** A plain click starts the fresh brief in place; a modified or middle click opens "/" as browsers do. */
export function freshClick(onFresh: () => void) {
  return (event: MouseEvent<HTMLAnchorElement>) => {
    if (!isPlainClick(event)) return;
    event.preventDefault();
    onFresh();
  };
}

/** Says an example's survey, kit or report is a finished example, free to open, and how to survey one's own. */
export function ExampleBanner({ example, onFresh, page = false }: ExampleBannerProps) {
  return (
    <aside className="ex-banner" aria-label="Example" data-page={page ? "" : undefined}>
      <p>
        <b className="ex-banner-tag mono">Example</b> · a finished survey of {example.label}. Opening it spends nothing.
      </p>
      <a className="ex-banner-go" href={BRIEF_URL} onClick={freshClick(onFresh)}>
        Survey your own storefront <span aria-hidden="true">→</span>
      </a>
    </aside>
  );
}
