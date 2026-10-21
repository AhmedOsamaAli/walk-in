import type { PlaceCard } from "../api/types";
import { price } from "../lib/format";

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
  ]
    .filter(Boolean)
    .join(" · ");
  if (meta) root.append(span("m", meta));
  const complaint = place.complaints?.[0];
  const praise = (place.praise ?? []).slice(0, 2).join(", ");
  if (complaint) {
    const said = span("s");
    said.append(span("bad", complaint));
    root.append(said);
  } else if (praise) {
    root.append(span("s", praise));
  }
  return root;
}
