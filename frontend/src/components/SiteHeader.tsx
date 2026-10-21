interface SiteHeaderProps {
  label: string;
  detail: string;
  onNewSurvey: () => void;
}

export function SiteHeader({ label, detail, onNewSurvey }: SiteHeaderProps) {
  return (
    <section className="sec site-head" aria-label="Site under survey">
      <div className="site-row">
        <div>
          <p className="eyebrow mono">
            <b>Site</b> under survey
          </p>
          <h2 className="site-title">{label}</h2>
          <p className="mono muted">{detail}</p>
        </div>
        <button className="ghost mono" type="button" onClick={onNewSurvey}>
          New survey
        </button>
      </div>
    </section>
  );
}
