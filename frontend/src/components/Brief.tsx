import { useRef } from "react";
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
const HEADLINE = ["What should", "this empty", "storefront", "become?"];

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

  // A site picked from the index or the search scrolls the survey button into view, once the chosen site has rendered.
  function reveal(next: Site) {
    onSite(next);
    requestAnimationFrame(() => {
      go.current?.scrollIntoView({ behavior: scrollBehavior(), block: "center" });
    });
  }

  const pickPreset = (preset: Preset) => {
    reveal({ id: preset.id, label: preset.label, lat: preset.lat, lon: preset.lon });
  };

  return (
    <section id="s-brief" className="sec brief" hidden={hidden}>
      <p className="eyebrow mono">
        <b>00</b> Site survey system
      </p>
      <h1 className="display headline" aria-label="What should this empty storefront become?">
        {HEADLINE.map((line, index) => (
          <span key={line} className="line" style={cssVars({ "--i": index })} aria-hidden="true">
            <span className={index === HEADLINE.length - 1 ? "ink-blue" : undefined}>{line}</span>
          </span>
        ))}
      </h1>
      <p className="lede serif">
        Drop a pin on a vacant unit. Blank Space reads what the people within a ten-minute walk love, what they leave the
        block for, and designs the business that keeps them here.
      </p>

      <SearchBox onPick={reveal} />
      <p className="hint mono">or click anywhere on the map</p>

      <PresetIndex selectedId={site?.id ?? null} onSelect={pickPreset} />

      <div className="brief-controls">
        {site ? (
          <div className="chosen">
            <span className="mono label">Site</span>
            <strong>{site.label}</strong>
            <span className="mono muted">{coords(site.lat, site.lon)}</span>
            <span className="mono walk-note">{walkNote(walk, minutes)}</span>
          </div>
        ) : null}

        <fieldset className="focus">
          <legend className="mono label">Walking catchment</legend>
          <div className="seg">
            {WALKS.map((value) => (
              <label key={value}>
                <input
                  type="radio"
                  name="minutes"
                  value={value}
                  checked={minutes === value}
                  onChange={() => {
                    onMinutes(value);
                  }}
                />
                <span>{value} min</span>
              </label>
            ))}
          </div>
          <p className="seg-note serif">
            Traced over real streets, so rivers, parks and highways cut it. Cafés live on 5–10 minutes; destinations draw
            from 15.
          </p>
        </fieldset>

        <fieldset className="focus">
          <legend className="mono label">Business type</legend>
          <div className="seg">
            {FOCUSES.map(({ value, label }) => (
              <label key={value}>
                <input
                  type="radio"
                  name="focus"
                  value={value}
                  checked={focus === value}
                  onChange={() => {
                    onFocus(value);
                  }}
                />
                <span>{label}</span>
              </label>
            ))}
          </div>
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

        <button ref={go} className="go" type="button" disabled={!site} onClick={onSurvey}>
          <span>Survey this site</span>
          <i aria-hidden="true">
            <svg viewBox="0 0 24 24">
              <path d="M4 12h15M13 6l6 6-6 6" />
            </svg>
          </i>
        </button>
      </div>
    </section>
  );
}
