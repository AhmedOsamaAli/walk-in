import { Fragment, useEffect, useRef } from "react";
import type { Focus, Preset, Walk, WalkMinutes } from "../api/types";
import { cssVars } from "../lib/css";
import { coords } from "../lib/format";
import { scrollBehavior } from "../lib/motion";
import { walkNote, type Site } from "../state/site";
import { PresetIndex } from "./PresetIndex";
import { SearchBox } from "./SearchBox";

const WALKS: readonly WalkMinutes[] = [5, 10, 15];
const FOCUSES: readonly { value: Focus; label: string }[] = [
  { value: "any", label: "Anything" },
  { value: "food_drink", label: "Food & drink" },
  { value: "retail", label: "Retail" },
  { value: "leisure", label: "Leisure & wellness" },
];
const QUESTION = "What should this empty storefront become?";
const WORDS = QUESTION.split(" ");
/** Two columns: the map stays pinned beside the sheet, so scrolling the sheet never hides it. */
const SIDE_BY_SIDE = "(min-width: 981px)";

interface ChipsProps<T extends string | number> {
  name: string;
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}

function Chips<T extends string | number>({ name, options, value, onChange }: ChipsProps<T>) {
  return (
    <div className="chips">
      {options.map((option) => (
        <label key={option.value} className="chip">
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            onChange={() => {
              onChange(option.value);
            }}
          />
          <span>{option.label}</span>
        </label>
      ))}
    </div>
  );
}

interface BriefProps {
  hidden: boolean;
  site: Site | null;
  walk: Walk | null;
  minutes: WalkMinutes;
  focus: Focus;
  notes: string;
  onSite: (site: Site) => void;
  onMinutes: (minutes: WalkMinutes) => void;
  onFocus: (focus: Focus) => void;
  onNotes: (notes: string) => void;
  onSurvey: () => void;
}

export function Brief({ hidden, site, walk, minutes, focus, notes, onSite, onMinutes, onFocus, onNotes, onSurvey }: BriefProps) {
  const go = useRef<HTMLButtonElement>(null);
  const fromBrief = useRef(false);

  // A chosen site reveals the survey brief under the search; bring its button into view. A pin dropped on the map of a
  // phone stays put, since the map sits above the sheet there and the user may still be moving the pin.
  useEffect(() => {
    if (!site) return;
    const picked = fromBrief.current;
    fromBrief.current = false;
    if (!picked && !window.matchMedia(SIDE_BY_SIDE).matches) return;
    const frame = requestAnimationFrame(() => {
      go.current?.scrollIntoView({ behavior: scrollBehavior(), block: "nearest" });
    });
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [site]);

  function choose(next: Site) {
    fromBrief.current = true;
    onSite(next);
  }

  const pickPreset = (preset: Preset) => {
    choose({ id: preset.id, label: preset.label, lat: preset.lat, lon: preset.lon });
  };

  return (
    <section id="s-brief" className="sec brief" hidden={hidden}>
      <p className="eyebrow mono">
        <b>00</b> Site survey
      </p>
      <h1 className="headline">
        <span className="sr-only">{QUESTION}</span>
        {WORDS.map((word, index) => (
          <Fragment key={word}>
            <span className="w" aria-hidden="true">
              <span style={cssVars({ "--i": index })}>{index === WORDS.length - 1 ? <em>{word}</em> : word}</span>
            </span>
            {index < WORDS.length - 1 ? " " : null}
          </Fragment>
        ))}
      </h1>
      <p className="lede">
        Drop a pin on a vacant unit. Blank Space reads what the people within a ten-minute walk love, what they leave the
        block for, and designs the business that keeps them here.
      </p>

      <SearchBox onPick={choose} />
      <p className="hint mono">or click anywhere on the map</p>

      {site ? (
        <div className="brief-card">
          <div className="chosen">
            <span className="mono label">Site</span>
            <strong>{site.label}</strong>
            <span className="mono muted">{coords(site.lat, site.lon)}</span>
            <span className="mono walk-note">{walkNote(walk, minutes)}</span>
          </div>

          <fieldset className="field">
            <legend className="mono label">Walking catchment</legend>
            <Chips
              name="minutes"
              options={WALKS.map((value) => ({ value, label: `${value} min` }))}
              value={minutes}
              onChange={onMinutes}
            />
            <p className="field-note serif">
              Traced over real streets, so rivers, parks and highways cut it. Cafés live on 5–10 minutes; destinations
              draw from 15.
            </p>
          </fieldset>

          <fieldset className="field">
            <legend className="mono label">Business type</legend>
            <Chips name="focus" options={FOCUSES} value={focus} onChange={onFocus} />
          </fieldset>

          <details className="notes">
            <summary className="mono">+ Owner constraints</summary>
            <textarea
              rows={2}
              maxLength={300}
              aria-label="Owner constraints"
              placeholder="e.g. no alcohol, 60 m² unit, mid-range prices"
              value={notes}
              onChange={(event) => {
                onNotes(event.target.value);
              }}
            />
          </details>

          <button ref={go} className="go" type="button" onClick={onSurvey}>
            <span>Survey this site</span>
            <i aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M4 12h15M13 6l6 6-6 6" />
              </svg>
            </i>
          </button>
        </div>
      ) : null}

      <PresetIndex selectedId={site?.id ?? null} onSelect={pickPreset} />
    </section>
  );
}
