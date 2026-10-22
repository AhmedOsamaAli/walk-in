interface SectionHeadProps {
  no: string;
  title: string;
  note?: string;
  /** The heading's id, for a section labelled by it. */
  id?: string;
}

export function SectionHead({ no, title, note, id }: SectionHeadProps) {
  return (
    <header className="sec-head">
      <span className="sec-no mono">{no}</span>
      <h2 className="sec-title" id={id}>
        {title}
      </h2>
      {note ? <p className="sec-note serif">{note}</p> : null}
    </header>
  );
}
