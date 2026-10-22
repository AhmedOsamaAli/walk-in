import { useEffect, useRef, useState, type RefObject } from "react";
import type { LaunchChannel, LaunchPlan } from "../api/types";
import { naturalList } from "../lib/format";
import { CLAIM_KINDS, audienceRows, shareText } from "../lib/launch";
import { HoursText } from "./Hours";
import { PlaceLink } from "./Price";

type CopyState = "idle" | "copied" | "selected";

/** Copies a setting; where the browser blocks the clipboard, selects the setting so the owner can copy it by hand. */
function CopyButton({ text, what, target }: { text: string; what: string; target: RefObject<HTMLElement | null> }) {
  const [state, setState] = useState<CopyState>("idle");
  useEffect(() => {
    if (state === "idle") return;
    const timer = window.setTimeout(
      () => {
        setState("idle");
      },
      state === "copied" ? 1800 : 6000,
    );
    return () => {
      window.clearTimeout(timer);
    };
  }, [state]);
  const keys = navigator.userAgent.includes("Mac") ? "⌘C" : "Ctrl+C";
  const select = () => {
    const selection = window.getSelection();
    if (!target.current || !selection) return;
    selection.selectAllChildren(target.current);
    setState("selected");
  };
  const status =
    state === "copied"
      ? `Copied the ${what} setting`
      : state === "selected"
        ? `Selected the ${what} setting: press ${keys} to copy it`
        : "";
  return (
    <>
      <button
        type="button"
        className="copy mono"
        data-state={state}
        aria-label={`Copy the ${what} setting`}
        onClick={() => {
          if (!("clipboard" in navigator)) {
            select();
            return;
          }
          navigator.clipboard.writeText(text).then(() => {
            setState("copied");
          }, select);
        }}
      >
        {state === "copied" ? "Copied" : state === "selected" ? `Press ${keys}` : "Copy"}
      </button>
      <span className="sr-only" role="status">
        {status}
      </span>
    </>
  );
}

function Channel({ channel, sites }: { channel: LaunchChannel; sites: LaunchPlan["where"]["sites_like"] }) {
  const setting = useRef<HTMLParagraphElement>(null);
  return (
    <li className="channel">
      <div className="channel-head">
        <b>{channel.channel}</b>
        <CopyButton text={channel.setting} what={channel.channel} target={setting} />
      </div>
      <p className="channel-setting" ref={setting}>
        {channel.setting}
      </p>
      <p className="channel-why">{channel.why}</p>
      {sites.length ? (
        <p className="channel-why">
          Their sites:{" "}
          {sites.map((site, index) => (
            <span key={site.url}>
              {index ? ", " : null}
              <PlaceLink name={site.name} url={site.url} />
            </span>
          ))}
          .
        </p>
      ) : null}
    </li>
  );
}

/** Who to reach, where and when, and only what the evidence lets an ad say: settings to paste, not a picture. */
export function LaunchPlanView({ plan }: { plan: LaunchPlan }) {
  const { audience, where, when, claims, channels, cautions } = plan;
  const shared = new Set(audience.shared);
  const rows = audienceRows(audience);
  const reach = where.reach_m ? `reaches ${where.reach_m} m at its farthest point` : null;
  const hoods = where.neighborhoods.length ? `takes in parts of ${naturalList(where.neighborhoods)}` : null;

  return (
    <div className="launch">
      {claims.length ? (
        <div className="launch-block">
          <h4 className="xp-title">
            What you can say
            <span className="mono">Each line with the numbers that make it true today</span>
          </h4>
          <ol className="claims">
            {claims.map((claim) => (
              <li className="claim" key={claim.line} data-kind={claim.kind}>
                <span className="claim-kind mono">{CLAIM_KINDS[claim.kind]}</span>
                <p className="claim-line">
                  <span className="hl">{claim.line}</span>
                </p>
                <p className="claim-proof">
                  <span className="mono">Proof</span> {claim.proof}
                </p>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {audience.crowd.length || rows.length ? (
        <div className="launch-block">
          <h4 className="xp-title">
            Who to reach
            <span className="mono">What people within 1.5 km over-index on</span>
          </h4>
          <dl className="spec launch-spec">
            {audience.crowd.length ? (
              <div>
                <dt>The places draw</dt>
                <dd className="tags">
                  {audience.crowd.map((share) => (
                    <span className="tag" key={share.label}>
                      {share.label} <small>{shareText(share)}</small>
                    </span>
                  ))}
                </dd>
              </div>
            ) : null}
            {rows.map((row) => (
              <div key={row.title}>
                <dt>{row.title}</dt>
                <dd>
                  {row.names.map((name, index) => (
                    <span key={name}>
                      {index ? " · " : null}
                      {shared.has(name) ? <b className="launch-shared">{name}</b> : name}
                    </span>
                  ))}
                </dd>
              </div>
            ))}
          </dl>
          {shared.size ? <p className="launch-note">Names in bold are loved by this category&apos;s fans too.</p> : null}
        </div>
      ) : null}

      {when.times.length || when.intents.length || when.hours ? (
        <div className="launch-block">
          <h4 className="xp-title">
            When
            <span className="mono">Qloo&apos;s tags on the places locals love of this kind</span>
          </h4>
          <dl className="spec launch-spec">
            {when.times.length ? (
              <div>
                <dt>Times of day</dt>
                <dd className="tags">
                  {when.times.map((share) => (
                    <span className="tag" key={share.label}>
                      {share.label} <small>{shareText(share)}</small>
                    </span>
                  ))}
                </dd>
              </div>
            ) : null}
            {when.intents.length ? (
              <div>
                <dt>Why people go</dt>
                <dd>
                  {when.intents.map((share) => (
                    <p className="launch-intent" key={share.label}>
                      <b>{share.label}</b> <small>{shareText(share)}</small>
                      {share.angle ? <span>{share.angle}</span> : null}
                    </p>
                  ))}
                </dd>
              </div>
            ) : null}
            {when.hours ? (
              <div>
                <dt>Hours</dt>
                <dd>
                  <HoursText hours={when.hours} />
                </dd>
              </div>
            ) : null}
          </dl>
        </div>
      ) : null}

      {channels.length ? (
        <div className="launch-block">
          <h4 className="xp-title">
            Where to set it up
            <span className="mono">Settings to paste</span>
          </h4>
          {reach || hoods ? (
            <p className="launch-note">
              The {where.minutes}-minute walk {[reach, hoods].filter(Boolean).join(" and ")}.
            </p>
          ) : null}
          <ol className="channels">
            {channels.map((channel) => (
              <Channel
                key={channel.channel}
                channel={channel}
                sites={channel.channel.startsWith("Google") ? where.sites_like : []}
              />
            ))}
          </ol>
        </div>
      ) : null}

      {cautions.length ? (
        <div className="launch-cautions">
          <h4 className="xp-title">Before it runs</h4>
          <ul>
            {cautions.map((caution) => (
              <li key={caution}>{caution}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {plan.basis ? <p className="xp-basis mono">{plan.basis}</p> : null}
    </div>
  );
}
