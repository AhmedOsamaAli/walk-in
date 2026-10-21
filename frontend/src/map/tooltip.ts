import type { PlaceCard } from "../api/types";
import { price, standingText } from "../lib/format";

function span(className: string, text = ""): HTMLSpanElement {
  const element = document.createElement("span");
  element.className = className;
  element.textContent = text;
  return element;
}

/** Tooltip content for a place on the map, built from text nodes so a place name is never parsed as HTML. */
export function placeTip(place: PlaceCard): HTMLElement {
  const root = document.createElement("div");
  const name = document.createElement("b");
  name.textContent = place.name ?? "Unnamed place";
  root.append(name);
  const meta = [
    place.genres?.[0],
    place.rating ? `★ ${place.rating.toFixed(1)}` : "",
    place.price_level ? price(place.price_level) : "",
    place.distance_m != null ? `${place.distance_m} m` : "",
    standingText(place.standing),
  ]
    .filter(Boolean)
    .join(" · ");
  if (meta) root.append(span("m", meta));
  const known = (place.known_for ?? []).slice(0, 3).join(", ");
  if (known) root.append(span("s", `Known for ${known}`));
  const complaint = place.complaints?.[0];
  if (complaint) {
    const said = span("s");
    said.append(span("hl", complaint));
    root.append(said);
  }
  return root;
}
