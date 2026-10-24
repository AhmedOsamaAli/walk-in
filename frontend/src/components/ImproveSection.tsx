import type { Comparison, ImprovePayload, OfferDiff } from "../api/types";
import { toSection } from "../lib/journey";
import { ExperiencePlanView } from "./ExperiencePlan";
import { PlaceLink } from "./PlaceLink";
import { SectionHead } from "./SectionHead";

const FAMILIES: readonly { key: string; label: string }[] = [
  { key: "menu", label: "Menu" },
  { key: "offerings", label: "Offerings" },
  { key: "amenities", label: "Amenities" },
  { key: "activities", label: "Activities" },
];

const rating = (value: number | null) => (value == null ? "Not listed" : value.toFixed(1));

/** Day groups in the order the server wrote them, from the place's hours and then the peers'. */
function dayGroups(hours: Comparison["hours"]): string[] {
  return [...new Set([...Object.keys(hours.place ?? {}), ...Object.keys(hours.peers ?? {})])];
}

function OfferRow({ label, diff, peers }: { label: string; diff: OfferDiff; peers: number }) {
  if (!diff.missing.length && !diff.own.length) return null;
  return (
    <div className="offer-diff">
      <h4 className="mono label">{label}</h4>
      {diff.missing.length ? (
        <p>
          <b>Theirs, not yours: </b>
          {diff.missing.map((item) => `${item.name} (${item.places} of ${peers})`).join(", ")}
        </p>
      ) : null}
      {diff.own.length ? (
        <p>
          <b>Only yours: </b>
          {diff.own.join(", ")}
        </p>
      ) : null}
    </div>
  );
}

export function ImproveSection({ no, data }: { no: string; data: ImprovePayload }) {
  if ("note" in data) {
    return (
      <section id="s-improve" className="sec reveal">
        <SectionHead no={no} title="What to change" />
        <p className="concepts-empty serif">{data.note}</p>
        <p className="sec-next" data-next-to="s-gaps">
          <b className="sec-next-label mono">Next</b>
          <a className="sec-next-link" href="#s-gaps" onClick={toSection("s-gaps")}>
            See what's missing <span aria-hidden="true">↑</span>
          </a>
        </p>
      </section>
    );
  }
  const { place, genre, comparison: c, moves, experience } = data;
  const name = place.name ?? "Your place";
  const names = c.peer_names.join(", ");
  const groups = dayGroups(c.hours);
  return (
    // data-moves: the wider taste's way back here shows only when there are moves to make (styles/journey.css).
    <section id="s-improve" className="sec reveal improve" data-moves={moves.length ? "" : undefined}>
      <SectionHead
        no={no}
        title="What to change"
        note={`${name} set against the ${c.peers} ${c.peers_label} in its category, ${genre}${names ? `: ${names}` : ""}.`}
      />
      {!c.comparable ? (
        <p className="concepts-caution">
          Few of them are priced like {name}, so read their offer and hours as context, not as a benchmark.
        </p>
      ) : null}
      {moves.length ? (
        <ol className="moves">
          {moves.map((move, index) => (
            <li key={move.title}>
              <span className="move-no" aria-hidden="true">
                {index + 1}
              </span>
              <div>
                <h3>{move.title}</h3>
                <p className="serif">{move.why}</p>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="concepts-empty serif">
          Nothing the places people here love do differs enough from {name} to suggest a change.
        </p>
      )}

      <h3 className="label mono improve-h">Side by side</h3>
      <div className="versus-wrap">
        <table className="versus">
          <thead>
            <tr>
              <th scope="col">
                <span className="sr-only">Measure</span>
              </th>
              <th scope="col">{name}</th>
              <th scope="col">The {c.peers} places people here love</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">Rating</th>
              <td>{rating(c.rating.place)}</td>
              <td>{rating(c.rating.peers)} median</td>
            </tr>
            {c.peer_links?.some((peer) => peer.url) ? (
              <tr>
                <th scope="row">Their menus</th>
                <td className="versus-note">Set their offer beside yours</td>
                <td>
                  {c.peer_links.map((peer, index) => (
                    <span key={peer.name}>
                      {index ? ", " : null}
                      <PlaceLink name={peer.name} url={peer.url} kind={peer.link} />
                    </span>
                  ))}
                </td>
              </tr>
            ) : null}
            {groups.map((group) => (
              <tr key={group}>
                <th scope="row">{group}</th>
                <td>{c.hours.place?.[group] ?? "Closed or not listed"}</td>
                <td>{c.hours.peers?.[group] ?? "Not listed"}</td>
              </tr>
            ))}
            <tr>
              <th scope="row">Known for</th>
              <td>{c.known_for.join(", ") || "Nothing recurring in its reviews"}</td>
              <td>{c.peers_known_for.join(", ") || "Nothing they share"}</td>
            </tr>
            <tr>
              <th scope="row">Reviews flag</th>
              <td>
                {c.complaints.map((theme) => `${theme.label} (${theme.mentions} ${theme.mentions === 1 ? "mention" : "mentions"})`).join(", ") ||
                  "Nothing recurring"}
              </td>
              <td aria-label="Not compared" />
            </tr>
          </tbody>
        </table>
      </div>
      <div className="offer-diffs">
        {FAMILIES.map(({ key, label }) => {
          const diff = c.offer[key];
          return diff ? <OfferRow key={key} label={label} diff={diff} peers={c.peers} /> : null;
        })}
      </div>

      {experience ? (
        <>
          <h3 className="label mono improve-h">Program for the neighborhood</h3>
          <ExperiencePlanView plan={experience} />
        </>
      ) : null}
      {/* Shown once the wider taste is on the page (styles/journey.css). */}
      <p className="sec-next" data-next-to="s-taste">
        <b className="sec-next-label mono">Next</b>
        <span>
          {moves.length ? "Start with move 1, then see what else people here love." : "See what else people here love."}
        </span>
        <a className="sec-next-link" href="#s-taste" onClick={toSection("s-taste")}>
          The wider taste <span aria-hidden="true">↓</span>
        </a>
      </p>
    </section>
  );
}
