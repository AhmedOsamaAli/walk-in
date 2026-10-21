interface SectionHeadProps {
  no: string;
  title: string;
  note?: string;
}

export function SectionHead({ no, title, note }: SectionHeadProps) {
  return (
    <header className="sec-head">
      <span className="sec-no mono">{no}</span>
      <h2 className="sec-title">{title}</h2>
      {note ? <p className="sec-note serif">{note}</p> : null}
    </header>
  );
}
