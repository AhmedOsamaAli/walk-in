import { useRef } from "react";
import type { Concept } from "../api/types";
import { cssVars } from "../lib/css";
import { letter, list, priceLabel } from "../lib/format";
import { CountUp } from "./CountUp";

interface PosterProps {
  concept: Concept;
  index: number;
  onOpen: (index: number, opener: HTMLElement | null) => void;
}

/** A concept as a poster; the whole card opens its design sheet, and its button makes that keyboard-operable. */
export function Poster({ concept, index, onOpen }: PosterProps) {
  const button = useRef<HTMLButtonElement>(null);
  const why = list(concept.why_here).slice(0, 3);
  const signature = list(concept.signature).slice(0, 4);
  const inspired = list(concept.inspired_by).slice(0, 3).join(" · ");
  const priced = priceLabel(concept.price_level);
  return (
    <article
      className={`poster p${index}`}
      style={cssVars({ "--i": index })}
      aria-labelledby={`poster-${index}-name`}
      onClick={() => {
        onOpen(index, button.current);
      }}
    >
      <div className="poster-top mono">
        <span>
          Concept {letter(index)} · {concept.genre}
        </span>
        {priced ? <span title={concept.price_basis}>{priced}</span> : null}
      </div>
      <div className="poster-head">
        <div className="poster-score">
          <CountUp value={concept.gap_score} />
          <small>gap</small>
        </div>
        <h3 className="poster-name" id={`poster-${index}-name`}>
          {concept.name}
        </h3>
      </div>
      {concept.one_liner ? <p className="poster-line">{concept.one_liner}</p> : null}
      {why.length ? (
        <ol className="poster-why">
          {why.map((line, k) => (
            <li key={k}>{line}</li>
          ))}
        </ol>
      ) : null}
      {signature.length ? (
        <div className="poster-sig">
          {signature.map((item, k) => (
            <span key={k}>{item}</span>
          ))}
        </div>
      ) : null}
      {concept.beat_competitors ? (
        <p className="poster-note">
          <b className="mono">Competition</b>
          {concept.beat_competitors}
        </p>
      ) : null}
      {concept.price_basis ? (
        <p className="poster-note">
          <b className="mono">Price{priced ? ` ${priced.split(" · ")[0]}` : ""}</b>
          {concept.price_basis}
        </p>
      ) : null}
      {concept.risk ? (
        <p className="poster-note">
          <b className="mono">Risk</b>
          {concept.risk}
        </p>
      ) : null}
      {inspired ? <p className="poster-insp mono">Inspired by {inspired}</p> : null}
      <button ref={button} className="poster-open mono" type="button" aria-label={`Open design sheet: ${concept.name}`}>
        <span>Open design sheet</span>
        <span aria-hidden="true">→</span>
      </button>
    </article>
  );
}
