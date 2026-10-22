import { useCallback, useEffect, useRef, type ReactNode, type Ref } from "react";
import { PRIVACY_URL } from "../lib/routes";
import { Link } from "./Link";
import type { TitleField } from "./SiteHeader";

/** Focuses a page's title once, when the page appears, so screen readers start there; the page does not scroll. */
export function useFocusOnMount(): (node: HTMLElement | null) => void {
  const done = useRef(false);
  return useCallback((node: HTMLElement | null) => {
    if (!node || done.current) return;
    done.current = true;
    node.focus({ preventScroll: true });
  }, []);
}

/** "My places · Walk-in" in the tab while the page shows; back to "Walk-in" after. */
export function useDocumentTitle(title: string | null): void {
  useEffect(() => {
    if (!title) return;
    document.title = `${title} · Walk-in`;
    return () => {
      document.title = "Walk-in";
    };
  }, [title]);
}

interface PageHeadProps {
  /** "Account · My places": the first word is set bold, like the survey's eyebrow. */
  eyebrow: string;
  title: string;
  titleRef?: Ref<HTMLHeadingElement>;
  standfirst?: ReactNode;
  fields?: readonly TitleField[];
  /** Controls set beside the eyebrow. */
  actions?: ReactNode;
}

/** A page's title block: the eyebrow, a broadsheet headline, a serif standfirst and the facts set out like a drawing's. */
export function PageHead({ eyebrow, title, titleRef, standfirst, fields, actions }: PageHeadProps) {
  const [first = "", ...rest] = eyebrow.split(" ");
  return (
    <header className="page-head">
      <div className="page-row">
        <p className="eyebrow mono">
          <b>{first}</b> {rest.join(" ")}
        </p>
        {actions ? <div className="page-actions">{actions}</div> : null}
      </div>
      <h1 ref={titleRef} className="page-title" tabIndex={-1}>
        {title}
      </h1>
      {standfirst ? <p className="page-standfirst serif">{standfirst}</p> : null}
      {fields?.length ? (
        <dl className="title-block">
          {fields.map((field) => (
            <div key={field.label}>
              <dt className="mono">{field.label}</dt>
              <dd className={field.mono ? "mono" : undefined}>
                {field.lines.map((line) => (
                  <span key={line}>{line}</span>
                ))}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </header>
  );
}

/** The sheet every page sits on: the drafting grid, the content column and the credits. */
export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <main className="page" id="main">
      <div className={className ? `page-sheet ${className}` : "page-sheet"}>
        {children}
        <footer className="page-foot mono">
          <p>
            Walk-in · Taste data by{" "}
            <a href="https://www.qloo.com" target="_blank" rel="noopener">
              Qloo
            </a>{" "}
            · <Link href={PRIVACY_URL}>Privacy</Link>
          </p>
        </footer>
      </div>
    </main>
  );
}
