import { Fragment, useEffect, useId, useRef, useState, type ReactNode } from "react";
import type { Ages, Focus, Intent, Kitchen, PlaceHit, Preset, Travel } from "../api/types";
import { areaLabel, KM_PICKS, MINUTE_PICKS, TRAVEL_LABELS } from "../lib/area";
import { cssVars } from "../lib/css";
import { coords, floorArea, INTENTS } from "../lib/format";
import { spotTitle } from "../lib/fullmap";
import { scrollBehavior } from "../lib/motion";
import { EXAMPLES_URL } from "../lib/routes";
import { walkLine, type WalkPreview } from "../lib/walk";
import { isBigArea } from "../map/geometry";
import {
  AGES_LABELS,
  areaProblem,
  briefArea,
  BUSINESS_MAX,
  foodPrepAsked,
  formArea,
  missing,
  type AreaUnit,
  type BriefForm,
  type Choice,
} from "../state/brief";
import { useSession } from "../state/session";
import type { Site } from "../state/site";
import { ExampleStrip } from "./ExampleStrip";
import { Link } from "./Link";
import { MapsLink } from "./MapsLink";
import { PlaceSearch } from "./PlaceSearch";
import { PresetIndex } from "./PresetIndex";
import { SearchBox } from "./SearchBox";

const TRAVELS: readonly { value: Travel; label: string }[] = (["walk", "drive", "distance"] as const).map((value) => ({
  value,
  label: TRAVEL_LABELS[value],
}));
/** How each way of measuring the area is traced. The walk's note also says how far people walk for what. */
const AREA_NOTES: Record<Travel, string> = {
  walk: "Traced over real streets, so rivers, parks and highways cut it. A café draws people from 5–10 minutes away; a destination from 15.",
  drive: "Traced over real roads at driving speeds, so bridges, highways and one-way streets shape it.",
  distance: "Measured along real roads from the site, not as the crow flies.",
};
const BIG_AREA =
  "Big areas suit towns, suburbs and destination businesses. In a dense city a big area holds almost everything, so few gaps show.";
const AGE_GROUPS: readonly { value: Ages; label: string }[] = (["all", "under_25", "25_34", "35_54", "55_plus"] as const).map(
  (value) => ({ value, label: AGES_LABELS[value] }),
);
const FOCUSES: readonly { value: Focus; label: string }[] = [
  { value: "any", label: "Anything" },
  { value: "food_drink", label: "Food & drink" },
  { value: "retail", label: "Retail" },
  { value: "leisure", label: "Leisure & wellness" },
];
const INTENT_ORDER: readonly Intent[] = ["explore", "open", "improve"];
/** What the unit can cook: it keeps a full restaurant off a unit that cannot, and matters only when food can be involved. */
const FOOD_PREP: readonly { value: Kitchen | "unsure"; label: string }[] = [
  { value: "full", label: "Full kitchen (with extraction)" },
  { value: "light", label: "Light prep only" },
  { value: "none", label: "None" },
  { value: "unsure", label: "Not sure" },
];
/** The answer in the folded "+ Your unit" line, where "None" alone would not say of what. */
const FOOD_PREP_SUMMARY: Record<Kitchen, string> = { full: "Full kitchen", light: "Light prep only", none: "No food prep" };
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
  improve: "What would make people here choose you?",
};
/** Each intent's lede; finding what is missing names the area it reads, "a 10-minute walk" until the owner picks another. */
const LEDES: Record<Intent, (area: string) => string> = {
  explore: (area) =>
    `Drop a pin on an empty shop. Walk-in reads what the people within a ${area} love, what they leave the block for, and designs the business they would walk in for.`,
  open: () =>
    "Drop a pin where you want to open. Walk-in tests your idea against everything the block is missing, then designs it to win here.",
  improve: () =>
    "Drop a pin near the place you run. Walk-in compares it with the places people here love in its category and lists what to change, each move with its evidence.",
};
/** Line icons for the three intents: find what is missing, an idea to test, a place to improve. */
const INTENT_ICONS: Record<Intent, ReactNode> = {
  explore: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m15.4 15.4 5.1 5.1M10.5 7.9v5.2M7.9 10.5h5.2" />
    </>
  ),
  open: (
    <path d="M9.6 18.2h4.8M10.4 21h3.2M12 3.2a5.6 5.6 0 0 0-3.4 10.1c.6.5 1 1.2 1 2v.6h4.8v-.6c0-.8.4-1.5 1-2A5.6 5.6 0 0 0 12 3.2Z" />
  ),
  improve: <path d="m3.5 16.8 5.6-5.6 4 4 7.4-7.4M15.2 7.8h5.3v5.3" />,
};
/** Two columns: the map stays pinned beside the sheet, so scrolling the sheet never hides it. */
const SIDE_BY_SIDE = "(min-width: 981px)";

/**
 * The brief's next step in view: its card whole when it fits under the bar, else from its site line, its primary action
 * held at the foot of the screen while the card is on it (layout.css). Smooth unless motion is reduced.
 */
function showCard(card: HTMLElement | null): void {
  card?.scrollIntoView({ behavior: scrollBehavior(), block: "nearest" });
}

interface ChipsProps<T extends string | number> {
  name: string;
  options: readonly { value: T; label: string }[];
  /** The chosen option's value; one none of the options has leaves them all unchosen. */
  value: T;
  onChange: (value: T) => void;
  className?: string;
  /** Names the group for screen readers when it shares its legend with another group. */
  label?: string;
  /** More in the same row, after the options: "Other". */
  children?: ReactNode;
}

function Chips<T extends string | number>({ name, options, value, onChange, className = "chips", label, children }: ChipsProps<T>) {
  return (
    <div className={className} role={label ? "radiogroup" : undefined} aria-label={label}>
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
      {children}
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

interface IntentsProps {
  intent: Intent;
  onChange: (intent: Intent) => void;
}

/**
 * What the owner wants, as three option cards: native radios, so the group is one tab stop and the arrow keys move
 * between the cards. Each card is named by its title and described by its sentence; on phones only the chosen card
 * shows its sentence, so the question and the search stay on the first screen (screen readers still hear them all).
 */
function Intents({ intent, onChange }: IntentsProps) {
  const id = useId();
  const [howOpen, setHowOpen] = useState(false);
  return (
    <div className="intents">
      <div className="intents-head">
        <p className="intents-q mono" id={`${id}-q`}>
          What do you want to do?
        </p>
        <button
          type="button"
          className="how-toggle mono"
          aria-expanded={howOpen}
          aria-controls={`${id}-how`}
          onClick={() => {
            setHowOpen((open) => !open);
          }}
        >
          How it works
          <span className="how-sign" aria-hidden="true" />
        </button>
      </div>
      <HowItWorks id={`${id}-how`} hidden={!howOpen} />
      <div className="intent-cards" role="radiogroup" aria-labelledby={`${id}-q`}>
        {INTENT_ORDER.map((value) => (
          <label key={value} className="intent-card" data-on={intent === value ? "" : undefined}>
            <input
              type="radio"
              name="intent"
              value={value}
              checked={intent === value}
              aria-labelledby={`${id}-${value}-title`}
              aria-describedby={`${id}-${value}-does`}
              onChange={() => {
                onChange(value);
              }}
            />
            <svg className="intent-icon" viewBox="0 0 24 24" aria-hidden="true">
              {INTENT_ICONS[value]}
            </svg>
            <span className="intent-title" id={`${id}-${value}-title`}>
              {INTENTS[value].label}
            </span>
            <span className="intent-does" id={`${id}-${value}-does`}>
              {INTENTS[value].does}
            </span>
            <span className="intent-check" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="m6.8 12.4 3.4 3.4 7-7.6" />
              </svg>
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}

/** The three steps and what a survey gives back: optional, folded away until asked for. */
function HowItWorks({ id, hidden }: { id: string; hidden: boolean }) {
  return (
    <div className="how" id={id} hidden={hidden}>
      <ol className="how-steps">
        <li>
          <b>Choose what you want.</b> Find what is missing, test an idea, or improve a place you run.
        </li>
        <li>
          <b>Pick the storefront.</b> Search an address, <span className="say-click">click</span>
          <span className="say-tap">tap</span> the map, or open the full-screen map.
        </li>
        <li>
          <b>Run the survey.</b> In about a minute, it reads Qloo&apos;s taste data for the people in the area.
        </li>
      </ol>
      <div className="how-get">
        <p className="how-label mono">What you get</p>
        <ul>
          <li>Ranked gaps, each with its evidence</li>
          <li>Concepts, each with its design sheet</li>
          <li>A free launch kit</li>
        </ul>
      </div>
    </div>
  );
}

interface FieldProps {
  form: BriefForm;
  onForm: (patch: Partial<BriefForm>) => void;
}

/**
 * How far customers come from: a walk, a drive or a road distance, each with five quick picks and "Other" for any number
 * within the routing server's limits, which wins over the picks while it holds text. A big area says what it suits.
 */
function AreaField({ form, onForm }: FieldProps) {
  const id = useId();
  const distance = form.travel === "distance";
  const unit = distance ? "km" : "min";
  const other = distance ? form.otherKm : form.otherMinutes;
  const typing = other.trim() !== "";
  const problem = areaProblem(form);
  const area = briefArea(form);
  const noun = distance ? "road distance" : form.travel;
  return (
    <fieldset className="field area-field">
      <legend className="mono label">How far do customers come from?</legend>
      <Chips
        name="travel"
        className="chips seg"
        label="Measured by"
        options={TRAVELS}
        value={form.travel}
        onChange={(travel) => {
          onForm({ travel });
        }}
      />
      <Chips
        name="reach"
        className="chips reach"
        label={distance ? "Road distance" : form.travel === "drive" ? "Drive time" : "Walking time"}
        options={(distance ? KM_PICKS : MINUTE_PICKS).map((value) => ({ value, label: `${value} ${unit}` }))}
        value={typing ? -1 : distance ? form.km : form.minutes}
        onChange={(value) => {
          onForm(distance ? { km: value, otherKm: "" } : { minutes: value, otherMinutes: "" });
        }}
      >
        <label className="chip-other" data-on={typing && !problem ? "" : undefined} data-bad={problem ? "" : undefined}>
          <input
            type="text"
            inputMode={distance ? "decimal" : "numeric"}
            maxLength={5}
            placeholder="Other"
            aria-label={distance ? "Other road distance in km, 1 to 100" : `Other ${noun} in minutes, 5 to 60`}
            aria-invalid={problem ? true : undefined}
            aria-describedby={problem ? `${id}-problem` : undefined}
            value={other}
            onChange={(event) => {
              const text = event.target.value;
              onForm(distance ? { otherKm: text } : { otherMinutes: text });
            }}
          />
          <span aria-hidden="true">{unit}</span>
        </label>
      </Chips>
      {problem ? (
        <p id={`${id}-problem`} className="area-problem mono">
          {problem}
        </p>
      ) : null}
      <p className="field-note serif">{AREA_NOTES[form.travel]}</p>
      {area && isBigArea(area) ? <p className="area-hint">{BIG_AREA}</p> : null}
    </fieldset>
  );
}

/** Who the owner wants to serve: everyone, or an age group, which changes what counts as missing. */
function AgesField({ form, onForm }: FieldProps) {
  return (
    <fieldset className="field">
      <legend className="mono label">Who do you want to serve?</legend>
      <Chips
        name="ages"
        options={AGE_GROUPS}
        value={form.ages}
        onChange={(ages) => {
          onForm({ ages });
        }}
      />
      <p className="field-note serif">An age group changes what counts as missing, and whose favorite places count.</p>
    </fieldset>
  );
}

function unitSummary(form: BriefForm): string {
  const size = floorArea(form.area, form.areaUnit);
  const parts = [
    size === null ? null : `${size.toLocaleString("en-US")} m²`,
    form.kitchen === "unsure" || !foodPrepAsked(form) ? null : FOOD_PREP_SUMMARY[form.kitchen],
    form.outdoor === "unsure" ? null : form.outdoor === "yes" ? "Outdoor space" : "No outdoor space",
  ].filter(Boolean);
  return parts.length ? ` · ${parts.join(" · ")}` : " (optional)";
}

const RULES_SHOWN = 36;

/** The owner's rules as the summary shows them while folded: what they typed, cut short, or that they are optional. */
function rulesSummary(notes: string): string {
  const text = notes.trim().replace(/\s+/g, " ");
  if (!text) return " (optional)";
  return ` · ${text.length > RULES_SHOWN ? `${text.slice(0, RULES_SHOWN - 1).trimEnd()}…` : text}`;
}

export interface BriefProps {
  hidden: boolean;
  /** Why the link the page was opened with shows the brief instead, say a survey that is no longer available. */
  notice: string | null;
  site: Site | null;
  /** The site's walk as it is traced. */
  trace: WalkPreview;
  /** Counts "Use this spot" on the full-screen map: each one brings the brief's next step into view and focus. */
  reveal: number;
  form: BriefForm;
  onForm: (patch: Partial<BriefForm>) => void;
  onSite: (site: Site) => void;
  onPlace: (place: PlaceHit | null) => void;
  onSurvey: () => void;
}

export function Brief({ hidden, notice, site, trace, reveal, form, onForm, onSite, onPlace, onSurvey }: BriefProps) {
  const sheet = useRef<HTMLElement>(null);
  const go = useRef<HTMLButtonElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const chosen = useRef<HTMLDivElement>(null);
  const fromBrief = useRef(false);
  const { intent } = form;
  /** New surveys are off for now (the judging weeks): the survey button gives way to the surveyed storefronts. */
  const paused = useSession().config?.surveys_paused === true;
  const blocker = missing(site, form);
  /** The area to trace; none while "Other" holds a number out of the limits. */
  const area = briefArea(form);
  /** The site's name: its address, or its coordinates for a pin placed by hand until its address comes. */
  const named = site ? spotTitle(site.label, site.lat, site.lon) : null;
  /** Where the site stands: a pin's address coming renames the site without moving it. */
  const spot = site ? `${site.lat},${site.lon}` : null;

  // A chosen site reveals the survey brief under the search, and the brief comes into view with its button. Picked in
  // the brief (the search, a sample site), focus moves on to its site line, which also closes a phone's keyboard; a pin
  // dropped on the map beside the sheet leaves focus on the map, where the owner may still be moving it. A pin dropped
  // on the map of a phone or tablet moves nothing, since the map sits above the sheet there: "Use this spot" waits at
  // the foot of the screen instead (NextStep.tsx). Nor does the page move under the full-screen map, whose own "Use this
  // spot" brings the brief's next step into view once it shrinks.
  useEffect(() => {
    if (spot === null) return;
    const picked = fromBrief.current;
    fromBrief.current = false;
    if (document.documentElement.classList.contains("map-full")) return;
    if (!picked && !window.matchMedia(SIDE_BY_SIDE).matches) return;
    const frame = requestAnimationFrame(() => {
      if (picked) chosen.current?.focus({ preventScroll: true });
      showCard(card.current);
    });
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [spot]);

  // "Use this spot" (the full-screen map's, or the one at the foot of a phone's screen): the brief takes over at its
  // next step, the survey's button, or the field that still stands in its way ("What do you want to open?", "Your
  // place").
  useEffect(() => {
    if (!reveal) return;
    // The survey's button, or the surveyed storefronts' link while surveys are paused; else the field in the way.
    const next =
      card.current?.querySelector<HTMLElement>(".go-row .go:not(:disabled)") ??
      card.current?.querySelector<HTMLElement>("input:not([type=radio])");
    next?.focus({ preventScroll: true });
    showCard(card.current);
  }, [reveal]);

  function choose(next: Site) {
    // Only a new spot runs the effect that reads and clears this; the same one again must not leave it set for the
    // next pin dropped on the map.
    fromBrief.current = spot !== `${next.lat},${next.lon}`;
    onSite(next);
  }

  const pickPreset = (preset: Preset) => {
    choose({ id: preset.id, label: preset.label, lat: preset.lat, lon: preset.lon });
  };

  /**
   * "Pick a sample site": the index of sites at the foot of the brief comes into view, focus on the chosen one or the
   * first. Not the finished examples, which open a survey already run: those are the strip under the hint.
   */
  function toSamples() {
    const examples = sheet.current?.querySelector<HTMLElement>(".index");
    const chosen = examples?.querySelector<HTMLElement>('.site-btn[aria-pressed="true"]');
    (chosen ?? examples?.querySelector<HTMLElement>(".site-btn"))?.focus({ preventScroll: true });
    examples?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
  }

  return (
    <section ref={sheet} id="s-brief" className="sec brief" hidden={hidden}>
      {notice ? <p className="brief-notice">{notice}</p> : null}
      <Intents
        intent={intent}
        onChange={(value) => {
          onForm({ intent: value });
        }}
      />
      <Headline intent={intent} />
      <p className="lede" key={intent}>
        {LEDES[intent](areaLabel(formArea(form)))}
      </p>

      <div className="find">
        <SearchBox
          site={site}
          siteLabel={site?.label ?? null}
          onPick={choose}
          placeholder={intent === "improve" ? "Street or neighborhood of your place" : undefined}
        />
        <p className="hint mono">
          or <span className="say-click">click</span>
          <span className="say-tap">tap</span> <span className="when-side">anywhere on the map</span>
          <span className="when-stacked">the map above</span>, or{" "}
          <button type="button" className="hint-link" onClick={toSamples}>
            pick a sample site
          </button>
        </p>
      </div>

      {site ? (
        <div ref={card} className="brief-card">
          <div ref={chosen} className="chosen" tabIndex={-1}>
            <span className="mono label">{intent === "improve" ? (form.place ? "Place" : "Near") : "Site"}</span>
            <strong className={named?.isCoords ? "coords" : undefined}>{named?.text}</strong>
            <MapsLink lat={site.lat} lon={site.lon} />
            {named?.isCoords ? null : <span className="mono muted">{coords(site.lat, site.lon)}</span>}
            <span className="mono walk-note">{area ? walkLine(trace, area) : ""}</span>
          </div>

          {intent === "improve" ? (
            <div className="field">
              <p className="mono label">Your place</p>
              <PlaceSearch near={site} place={form.place} onPick={onPlace} />
              <p className="field-note serif">
                Its Qloo record (reviews, hours and what it is known for) is set against the places people here love in its
                category.
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

          <AreaField form={form} onForm={onForm} />

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

          <AgesField form={form} onForm={onForm} />

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
                  {foodPrepAsked(form) ? (
                    <fieldset>
                      <legend className="mono label">
                        Food prep
                        {intent === "open" ? <span className="muted">only matters if it serves food</span> : null}
                      </legend>
                      <Chips
                        name="kitchen"
                        options={FOOD_PREP}
                        value={form.kitchen}
                        onChange={(kitchen) => {
                          onForm({ kitchen });
                        }}
                      />
                    </fieldset>
                  ) : null}
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
                  Floor area sizes seating where people sit or stand. Food prep marks food ideas this space can&apos;t serve.
                  Shops and services need neither.
                </p>
              </details>

              <details className="notes">
                <summary className="mono">+ Your rules{rulesSummary(form.notes)}</summary>
                <textarea
                  rows={2}
                  maxLength={300}
                  aria-label="Your rules for the business"
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
            {paused ? (
              <>
                <p className="go-paused" id="go-paused">
                  New surveys are paused while judges try Walk-in:
                </p>
                <Link className="go" href={EXAMPLES_URL} aria-describedby="go-paused">
                  <span>Open a surveyed storefront</span>
                  <i aria-hidden="true">
                    <svg viewBox="0 0 24 24">
                      <path d="M4 12h15M13 6l6 6-6 6" />
                    </svg>
                  </i>
                </Link>
              </>
            ) : (
              <>
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
              </>
            )}
          </div>
        </div>
      ) : null}

      <ExampleStrip after={site !== null} />

      <PresetIndex selectedId={site?.id ?? null} onSelect={pickPreset} />
    </section>
  );
}
