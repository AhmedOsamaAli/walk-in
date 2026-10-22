import { Fragment, useEffect, useRef } from "react";
import type { Focus, Intent, Kitchen, PlaceHit, Preset, Walk, WalkMinutes } from "../api/types";
import { cssVars } from "../lib/css";
import { coords, floorArea, INTENTS, KITCHEN_LABELS } from "../lib/format";
import { scrollBehavior } from "../lib/motion";
import { BUSINESS_MAX, missing, type AreaUnit, type BriefForm, type Choice } from "../state/brief";
import { walkNote, type Site } from "../state/site";
import { PlaceSearch } from "./PlaceSearch";
import { PresetIndex } from "./PresetIndex";
import { SearchBox } from "./SearchBox";

const WALKS: readonly WalkMinutes[] = [5, 10, 15];
const FOCUSES: readonly { value: Focus; label: string }[] = [
  { value: "any", label: "Anything" },
  { value: "food_drink", label: "Food & drink" },
  { value: "retail", label: "Retail" },
  { value: "leisure", label: "Leisure & wellness" },
];
const INTENT_ORDER: readonly Intent[] = ["explore", "open", "improve"];
const KITCHENS: readonly { value: Kitchen | "unsure"; label: string }[] = [
  { value: "full", label: KITCHEN_LABELS.full },
  { value: "light", label: KITCHEN_LABELS.light },
  { value: "none", label: KITCHEN_LABELS.none },
  { value: "unsure", label: "Not sure" },
];
const OUTDOOR: readonly { value: Choice; label: string }[] = [
  { value: "yes", label: "Yes" },
  { value: "no", label: "No" },
  { value: "unsure", label: "Not sure" },
];
const AREA_UNITS: readonly { value: AreaUnit; label: string }[] = [
  { value: "m2", label: "m²" },
  { value: "ft2", label: "ft²" },
];

/** Each intent's question; the last word is set in the blue pen. */
const QUESTIONS: Record<Intent, string> = {
  explore: "What should this empty storefront become?",
  open: "Will your idea work on this block?",
  improve: "What would make locals choose you?",
};
const LEDES: Record<Intent, string> = {
  explore:
    "Drop a pin on a vacant unit. Walk-in reads what the people within a ten-minute walk love, what they leave the block for, and designs the business they would walk in for.",
  open: "Drop a pin where you want to open. Walk-in judges your idea against everything the block is missing, then designs it to win here.",
  improve:
    "Drop a pin near the place you run. Walk-in compares it with the places locals love in its category and lists what to change, each move with its evidence.",
};
/** Two columns: the map stays pinned beside the sheet, so scrolling the sheet never hides it. */
const SIDE_BY_SIDE = "(min-width: 981px)";

interface ChipsProps<T extends string | number> {
  name: string;
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}

function Chips<T extends string | number>({ name, options, value, onChange, className = "chips" }: ChipsProps<T>) {
  return (
    <div className={className}>
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

function Headline({ intent }: { intent: Intent }) {
  const question = QUESTIONS[intent];
  const words = question.split(" ");
  return (
    <h1 className="headline" key={intent}>
      <span className="sr-only">{question}</span>
      {words.map((word, index) => (
        <Fragment key={`${word}-${index}`}>
          <span className="w" aria-hidden="true">
            <span style={cssVars({ "--i": index })}>{index === words.length - 1 ? <em>{word}</em> : word}</span>
          </span>
          {index < words.length - 1 ? " " : null}
        </Fragment>
      ))}
    </h1>
  );
}

function unitSummary(form: BriefForm): string {
  const size = floorArea(form.area, form.areaUnit);
  const parts = [
    size === null ? null : `${size.toLocaleString("en-US")} m²`,
    form.kitchen === "unsure" ? null : KITCHEN_LABELS[form.kitchen],
    form.outdoor === "unsure" ? null : form.outdoor === "yes" ? "Outdoor space" : "No outdoor space",
  ].filter(Boolean);
  return parts.length ? ` · ${parts.join(" · ")}` : " (optional)";
}

interface BriefProps {
  hidden: boolean;
  site: Site | null;
  walk: Walk | null;
  form: BriefForm;
  onForm: (patch: Partial<BriefForm>) => void;
  onSite: (site: Site) => void;
  onPlace: (place: PlaceHit | null) => void;
  onSurvey: () => void;
}

export function Brief({ hidden, site, walk, form, onForm, onSite, onPlace, onSurvey }: BriefProps) {
  const go = useRef<HTMLButtonElement>(null);
  const fromBrief = useRef(false);
  const { intent } = form;
  const blocker = missing(site, form);

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
      <fieldset className="intents">
        <legend className="mono">
          <b>00</b>
          <span className="sr-only">What do you want to do?</span>
        </legend>
        <Chips
          name="intent"
          className="intent-tabs mono"
          options={INTENT_ORDER.map((value) => ({ value, label: INTENTS[value].label }))}
          value={intent}
          onChange={(value) => {
            onForm({ intent: value });
          }}
        />
      </fieldset>
      <Headline intent={intent} />
      <p className="lede" key={intent}>
        {LEDES[intent]}
      </p>

      <SearchBox onPick={choose} placeholder={intent === "improve" ? "Street or neighborhood of your place" : undefined} />
      <p className="hint mono">or click anywhere on the map</p>

      {site ? (
        <div className="brief-card">
          <div className="chosen">
            <span className="mono label">{intent === "improve" ? (form.place ? "Place" : "Near") : "Site"}</span>
            <strong>{site.label}</strong>
            <span className="mono muted">{coords(site.lat, site.lon)}</span>
            <span className="mono walk-note">{walkNote(walk, form.minutes)}</span>
          </div>

          {intent === "improve" ? (
            <div className="field">
              <p className="mono label">Your place</p>
              <PlaceSearch near={site} place={form.place} onPick={onPlace} />
              <p className="field-note serif">
                Its Qloo record (reviews, price, hours and what it is known for) is set against the places locals love in
                its category.
              </p>
            </div>
          ) : null}

          {intent === "open" ? (
            <label className="field">
              <span className="mono label">What do you want to open?</span>
              <input
                className="field-input"
                type="text"
                maxLength={BUSINESS_MAX}
                placeholder="bakery, sports bar, bookstore…"
                value={form.business}
                onChange={(event) => {
                  onForm({ business: event.target.value });
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !blocker) onSurvey();
                }}
              />
              <span className="field-note serif">
                Matched to Qloo&apos;s place categories and measured live when the gap table does not have it.
              </span>
            </label>
          ) : null}

          <fieldset className="field">
            <legend className="mono label">Walking catchment</legend>
            <Chips
              name="minutes"
              options={WALKS.map((value) => ({ value, label: `${value} min` }))}
              value={form.minutes}
              onChange={(minutes) => {
                onForm({ minutes });
              }}
            />
            <p className="field-note serif">
              Traced over real streets, so rivers, parks and highways cut it. Cafés live on 5–10 minutes; destinations
              draw from 15.
            </p>
          </fieldset>

          {intent === "explore" ? (
            <fieldset className="field">
              <legend className="mono label">Business type</legend>
              <Chips
                name="focus"
                options={FOCUSES}
                value={form.focus}
                onChange={(focus) => {
                  onForm({ focus });
                }}
              />
            </fieldset>
          ) : null}

          {intent !== "improve" ? (
            <>
              <details className="notes unit">
                <summary className="mono">+ Your unit{unitSummary(form)}</summary>
                <div className="unit-grid">
                  <div className="unit-area">
                    <label className="mono label" htmlFor="unit-area">
                      Floor area
                    </label>
                    <div className="area-input">
                      <input
                        id="unit-area"
                        className="field-input"
                        type="text"
                        inputMode="decimal"
                        placeholder={form.areaUnit === "m2" ? "60" : "650"}
                        value={form.area}
                        onChange={(event) => {
                          onForm({ area: event.target.value });
                        }}
                      />
                      <Chips
                        name="area-unit"
                        options={AREA_UNITS}
                        value={form.areaUnit}
                        onChange={(areaUnit) => {
                          onForm({ areaUnit });
                        }}
                      />
                    </div>
                  </div>
                  <fieldset>
                    <legend className="mono label">Kitchen</legend>
                    <Chips
                      name="kitchen"
                      options={KITCHENS}
                      value={form.kitchen}
                      onChange={(kitchen) => {
                        onForm({ kitchen });
                      }}
                    />
                  </fieldset>
                  <fieldset>
                    <legend className="mono label">Outdoor space</legend>
                    <Chips
                      name="outdoor"
                      options={OUTDOOR}
                      value={form.outdoor}
                      onChange={(outdoor) => {
                        onForm({ outdoor });
                      }}
                    />
                  </fieldset>
                </div>
                <p className="field-note serif">
                  Categories the kitchen cannot serve are marked, and seating is sized with building-code occupant loads.
                </p>
              </details>

              <details className="notes">
                <summary className="mono">+ Owner constraints</summary>
                <textarea
                  rows={2}
                  maxLength={300}
                  aria-label="Owner constraints"
                  placeholder="e.g. no alcohol, halal, family friendly, mid-range prices"
                  value={form.notes}
                  onChange={(event) => {
                    onForm({ notes: event.target.value });
                  }}
                />
              </details>
            </>
          ) : null}

          <div className="go-row">
            <button
              ref={go}
              className="go"
              type="button"
              onClick={onSurvey}
              disabled={blocker !== null}
              aria-describedby={blocker ? "go-hint" : undefined}
            >
              <span>{INTENTS[intent].action}</span>
              <i aria-hidden="true">
                <svg viewBox="0 0 24 24">
                  <path d="M4 12h15M13 6l6 6-6 6" />
                </svg>
              </i>
            </button>
            {blocker ? (
              <p id="go-hint" className="go-hint mono">
                {blocker}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}

      <PresetIndex selectedId={site?.id ?? null} onSelect={pickPreset} />
    </section>
  );
}
