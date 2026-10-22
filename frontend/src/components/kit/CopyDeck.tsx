import { useRef } from "react";
import type { ChannelKey, Kit, KitClaim, KitCopy } from "../../api/kit";
import { cx } from "../../lib/css";
import { CLAIM_KINDS } from "../../lib/launch";
import { CopyButton } from "../CopyButton";

/** One field of a channel's copy: a line, a paragraph or a list of lines, with the limit the platform sets. */
interface Field {
  label: string;
  /** A single text, or the lines of a list field such as search headlines. */
  value: string | string[];
  limit: number;
  unit: "characters" | "words";
}

const ORDER: readonly ChannelKey[] = ["spotify", "nextdoor", "google_search", "meta", "poster"];

const WHERE: Record<ChannelKey, string> = {
  spotify: "Read aloud in a Spotify audio ad, with its companion banner",
  nextdoor: "A post for the neighborhoods of the walk",
  google_search: "A responsive search ad: Google mixes the headlines and descriptions",
  meta: "A radius ad on Facebook and Instagram",
  poster: "The lines on the window poster",
};

/** The fields of each channel's copy, as kit.py writes them, with the limits it checked them against. */
function fieldsOf(key: ChannelKey, copy: KitCopy): Field[] {
  switch (key) {
    case "spotify":
      return copy.spotify
        ? [
            { label: "Script", value: copy.spotify.script, limit: 75, unit: "words" },
            { label: "Companion banner", value: copy.spotify.companion, limit: 40, unit: "characters" },
          ]
        : [];
    case "nextdoor":
      return copy.nextdoor
        ? [
            { label: "Headline", value: copy.nextdoor.headline, limit: 60, unit: "characters" },
            { label: "Post", value: copy.nextdoor.body, limit: 600, unit: "characters" },
          ]
        : [];
    case "google_search":
      return copy.google_search
        ? [
            { label: "Headlines", value: copy.google_search.headlines, limit: 30, unit: "characters" },
            { label: "Descriptions", value: copy.google_search.descriptions, limit: 90, unit: "characters" },
          ]
        : [];
    case "meta":
      return copy.meta
        ? [
            { label: "Primary text", value: copy.meta.primary_text, limit: 125, unit: "characters" },
            { label: "Headline", value: copy.meta.headline, limit: 40, unit: "characters" },
            { label: "Description", value: copy.meta.description, limit: 30, unit: "characters" },
          ]
        : [];
    case "poster":
      return copy.poster
        ? [
            { label: "Headline", value: copy.poster.headline, limit: 40, unit: "characters" },
            { label: "Subline", value: copy.poster.subline, limit: 90, unit: "characters" },
          ]
        : [];
  }
}

const count = (text: string, unit: Field["unit"]) => (unit === "words" ? text.split(/\s+/).filter(Boolean).length : text.length);

const SOURCES = { agent: "Written by the agent", rules: "Written by the evidence rules", mixed: "The agent's lines, topped up by the rules" };

function FieldView({ field, channel }: { field: Field; channel: string }) {
  const box = useRef<HTMLDivElement>(null);
  const lines = Array.isArray(field.value) ? field.value : [field.value];
  const text = lines.join("\n");
  const what = `the ${channel} ${field.label.toLowerCase()}`;
  return (
    <div className="ad-field">
      <div className="ad-field-head">
        <span className="mono">{field.label}</span>
        <span className="ad-limit mono">
          {Array.isArray(field.value)
            ? `${lines.length} lines · ${field.limit} ${field.unit} each at most`
            : `${count(field.value, field.unit)} of ${field.limit} ${field.unit}`}
        </span>
        {text ? <CopyButton text={text} what={what} target={box} label={Array.isArray(field.value) ? "Copy all" : "Copy"} /> : null}
      </div>
      <div ref={box} className={cx("ad-text", Array.isArray(field.value) && "ad-lines", field.label === "Script" && "ad-script")}>
        {Array.isArray(field.value) ? (
          <ol>
            {lines.map((line) => (
              <li key={line}>
                <span>{line}</span>
                <small className="mono" aria-label={`${line.length} characters`}>
                  {line.length}
                </small>
              </li>
            ))}
          </ol>
        ) : (
          <p>{field.value || "—"}</p>
        )}
      </div>
    </div>
  );
}

function Claims({ ids, claims }: { ids: string[]; claims: KitClaim[] }) {
  const used = claims.filter((claim) => ids.includes(claim.id));
  if (!used.length) return <p className="ad-claims mono">States no claim: only what the business is, where and when</p>;
  return (
    <p className="ad-claims">
      <span className="mono">Claims</span>
      {used.map((claim) => (
        <span className="ad-claim mono" key={claim.id} title={claim.proof}>
          {CLAIM_KINDS[claim.kind]}
        </span>
      ))}
    </p>
  );
}

/** The ad copy, one card per channel, every field with its limit and a copy button. */
export function CopyDeck({ kit }: { kit: Kit }) {
  const channels = ORDER.filter((key) => kit.copy[key]);
  return (
    <div className="ad-deck">
      {channels.map((key) => {
        const piece = kit.copy[key];
        if (!piece) return null;
        const extra = key === "spotify" && kit.copy.spotify ? ` · about ${kit.copy.spotify.seconds} seconds read aloud` : "";
        return (
          <article className={cx("ad-card", `ad-${key}`)} key={key} aria-labelledby={`ad-${key}`}>
            <header className="ad-head">
              <h3 className="ad-channel" id={`ad-${key}`}>
                {piece.channel}
              </h3>
              <span className="ad-source mono" data-source={piece.source}>
                {SOURCES[piece.source]}
              </span>
            </header>
            <p className="ad-where">
              {WHERE[key]}
              {extra}.
            </p>
            {fieldsOf(key, kit.copy).map((field) => (
              <FieldView key={field.label} field={field} channel={piece.channel} />
            ))}
            <Claims ids={piece.claims} claims={kit.claims} />
          </article>
        );
      })}
    </div>
  );
}

/** Lines the checks refused, and claims left out: proof the copy says only what the evidence gives. */
export function CopyChecks({ kit }: { kit: Kit }) {
  if (!kit.rejected.length && !kit.notes.length) return null;
  return (
    <details className="ad-checks">
      <summary className="mono">
        What the checks refused · {kit.rejected.length} {kit.rejected.length === 1 ? "line" : "lines"}
        {kit.notes.length ? `, ${kit.notes.length} ${kit.notes.length === 1 ? "claim" : "claims"} left out` : ""}
      </summary>
      <ul>
        {kit.notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
        {kit.rejected.map((line, index) => (
          <li key={`${line.channel}-${line.field}-${String(index)}`}>
            <s>{line.text}</s>
            <span className="mono">
              {line.channel} · {line.field}
            </span>
            <span>{line.reasons.join("; ")}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}
