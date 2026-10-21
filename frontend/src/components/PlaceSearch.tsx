import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { api, messageOf } from "../api/client";
import type { PlaceHit } from "../api/types";
import { distanceText } from "../lib/format";

interface Found {
  query: string;
  items: PlaceHit[];
  error: string | null;
}

interface PlaceSearchProps {
  near: { lat: number; lon: number };
  place: PlaceHit | null;
  onPick: (place: PlaceHit | null) => void;
}

function details(place: PlaceHit, withDistance = true): string {
  return [place.genres?.slice(0, 2).join(", "), place.address, withDistance ? distanceText(place.distance_m) : null]
    .filter(Boolean)
    .join(" · ");
}

/** Finds the owner's place on Qloo by name, nearest the pin first. */
export function PlaceSearch({ near, place, onPick }: PlaceSearchProps) {
  const listId = useId();
  const box = useRef<HTMLDivElement>(null);
  const timer = useRef(0);
  const pending = useRef<AbortController | null>(null);
  const [text, setText] = useState("");
  const [found, setFound] = useState<Found | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);

  useEffect(() => {
    const closeOutside = (event: MouseEvent) => {
      if (!(event.target instanceof Node) || !box.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("click", closeOutside);
    return () => {
      document.removeEventListener("click", closeOutside);
      window.clearTimeout(timer.current);
      pending.current?.abort();
    };
  }, []);

  function search(query: string) {
    pending.current?.abort();
    const abort = new AbortController();
    pending.current = abort;
    api.places(query, near.lat, near.lon, abort.signal).then(
      (items) => {
        if (abort.signal.aborted) return;
        setFound({ query, items, error: null });
        setActive(-1);
        setOpen(true);
      },
      (error: unknown) => {
        if (abort.signal.aborted) return;
        setFound({ query, items: [], error: messageOf(error) });
        setOpen(true);
      },
    );
  }

  function change(value: string) {
    setText(value);
    window.clearTimeout(timer.current);
    const query = value.trim();
    if (query.length < 2) {
      pending.current?.abort();
      setOpen(false);
      return;
    }
    timer.current = window.setTimeout(() => {
      search(query);
    }, 350);
  }

  function pick(item: PlaceHit | undefined) {
    if (!item) return;
    setOpen(false);
    setActive(-1);
    setText("");
    onPick(item);
  }

  function keyDown(event: KeyboardEvent<HTMLInputElement>) {
    const count = found?.items.length ?? 0;
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (open && count) pick(found?.items[Math.max(0, active)]);
      return;
    }
    if (!open || !count || (event.key !== "ArrowDown" && event.key !== "ArrowUp")) return;
    event.preventDefault();
    const step = event.key === "ArrowDown" ? 1 : -1;
    setActive((index) => (index + step + count) % count);
  }

  if (place) {
    return (
      <div className="place-picked">
        <div>
          <strong>{place.name}</strong>
          <span className="mono muted">{details(place, false)}</span>
        </div>
        <button
          className="ghost mono"
          type="button"
          onClick={() => {
            onPick(null);
          }}
        >
          Change
        </button>
      </div>
    );
  }

  const optionId = (index: number) => `${listId}-${index}`;
  const showList = open && found !== null;
  return (
    <div ref={box} className="place-search">
      <input
        className="field-input"
        type="search"
        placeholder="Your place's name, e.g. Suerte"
        aria-label="Your place's name"
        value={text}
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showList && active >= 0 ? optionId(active) : undefined}
        onChange={(event) => {
          change(event.target.value);
        }}
        onKeyDown={keyDown}
      />
      <ul id={listId} className="results" role="listbox" aria-label="Places on Qloo near the pin" hidden={!showList}>
        {found?.error ? (
          <li className="empty" role="option" aria-selected="false" aria-disabled="true">
            {found.error}
          </li>
        ) : found?.items.length ? (
          found.items.map((item, index) => (
            <li
              key={item.id}
              id={optionId(index)}
              role="option"
              aria-selected={index === active}
              onMouseDown={(event) => {
                event.preventDefault();
              }}
              onClick={() => {
                pick(item);
              }}
            >
              <b>{item.name}</b>
              <span className="mono">{details(item)}</span>
            </li>
          ))
        ) : (
          <li className="empty" role="option" aria-selected="false" aria-disabled="true">
            No place by that name near the pin on Qloo. Move the pin closer to it, or try its name as signs spell it.
          </li>
        )}
      </ul>
    </div>
  );
}
