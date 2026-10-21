export interface TitleField {
  label: string;
  /** One entry per line, so a value breaks where it should, never mid-coordinate. */
  lines: readonly string[];
  /** Coordinates and other measured values read best in the drafting face. */
  mono?: boolean;
}

interface SiteHeaderProps {
  /** "Site under survey": the first word is set bold. */
  eyebrow: string;
  label: string;
  fields: readonly TitleField[];
  onNewSurvey: () => void;
}

/** The site under survey, with the survey's parameters set out like a drawing's title block. */
export function SiteHeader({ eyebrow, label, fields, onNewSurvey }: SiteHeaderProps) {
  const [first = "", ...rest] = eyebrow.split(" ");
  return (
    <section className="sec site-head" aria-label={eyebrow}>
      <div className="site-row">
        <p className="eyebrow mono">
          <b>{first}</b> {rest.join(" ")}
        </p>
        <button className="ghost mono" type="button" onClick={onNewSurvey}>
          New survey
        </button>
      </div>
      <h2 className="site-title">{label}</h2>
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
    </section>
  );
}
