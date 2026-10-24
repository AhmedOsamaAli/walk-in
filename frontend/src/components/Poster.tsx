import { Fragment, useRef } from "react";
import type { Concept } from "../api/types";
import { loves, riskText, ruleLines } from "../lib/concepts";
import { cssVars, cx } from "../lib/css";
import { letter, list } from "../lib/format";
import { posterButtonId } from "../lib/sections";
import { CountUp } from "./CountUp";

interface PosterProps {
  concept: Concept;
  /** Its place in the payload, which its design sheet and the sheet's link use. */
  index: number;
  /** Its rank among the ranked concepts; null for the wild card, which is never ranked. */
  rank: number | null;
  /** Its place on the page, for the order the cards come in. */
  position: number;
  onOpen: (index: number, opener: HTMLElement | null) => void;
}

const capitalized = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/**
 * A concept as a poster; the whole card opens its design sheet, and its button makes that keyboard-operable. The wild
 * card has no score or rank: it is stamped untested, says what it combines and why that is a risk.
 */
export function Poster({ concept, index, rank, position, onOpen }: PosterProps) {
  const button = useRef<HTMLButtonElement>(null);
  const wild = rank === null;
  const why = wild ? [] : list(concept.why_here).slice(0, 3);
  const signature = list(concept.signature).slice(0, 4);
  const inspired = list(concept.inspired_by).slice(0, 3).join(" · ");
  const pair = wild ? loves(concept) : [];
  const rules = ruleLines(concept);
  const risk = riskText(concept);
  const caution = wild ? concept.caution?.trim() : null;
  return (
    <article
      className={cx("poster", wild ? "wild" : `p${rank}`)}
      style={cssVars({ "--i": position })}
      aria-labelledby={`poster-${index}-name`}
      onClick={() => {
        onOpen(index, button.current);
      }}
    >
      <div className="poster-top mono">
        <span>{wild ? "Wild card · not ranked" : `Concept ${letter(index)} · ${concept.genre}`}</span>
      </div>
      <div className="poster-head">
        {wild ? (
          <span className="stamp untested mono">Untested</span>
        ) : typeof concept.gap_score === "number" ? (
          <div className="poster-score">
            <CountUp value={concept.gap_score} />
            <small>gap</small>
          </div>
        ) : null}
        <h3 className="poster-name" id={`poster-${index}-name`}>
          {concept.name}
        </h3>
      </div>
      {pair.length === 2 ? (
        <div className="poster-pair">
          <p className="poster-combines">
            <span className="mono">Combines</span>{" "}
            {pair.map((love, k) => (
              <Fragment key={love.item}>
                {k ? (
                  <>
                    <span aria-hidden="true"> × </span>
                    <span className="sr-only"> and </span>
                  </>
                ) : null}
                <b>{love.item}</b>
              </Fragment>
            ))}
          </p>
          <ul className="poster-loves">
            {pair.map((love) => (
              <li key={love.item}>
                <b>{capitalized(love.item)}:</b> {love.source}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {concept.one_liner ? <p className="poster-line">{concept.one_liner}</p> : null}
      {caution ? (
        <p className="poster-note poster-caution">
          <b className="mono">Caution</b>
          {caution}
        </p>
      ) : null}
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
      {rules.length ? (
        <div className="poster-note poster-rules">
          <b className="mono">Your rules</b>
          <ul>
            {rules.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {risk ? (
        <p className="poster-note">
          <b className="mono">Risk</b>
          {risk}
        </p>
      ) : null}
      {inspired ? <p className="poster-insp mono">Inspired by {inspired}</p> : null}
      <button
        ref={button}
        id={posterButtonId(index)}
        className="poster-open mono"
        type="button"
        aria-label={`Open design sheet: ${concept.name}`}
      >
        <span>Open design sheet</span>
        <span aria-hidden="true">→</span>
      </button>
    </article>
  );
}
