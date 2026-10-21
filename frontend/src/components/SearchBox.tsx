import { useEffect, useId, useRef, useState, type KeyboardEvent, type SyntheticEvent } from "react";
import { api, messageOf } from "../api/client";
import type { GeocodeResult } from "../api/types";
import { shortLabel } from "../lib/format";
import type { Site } from "../state/site";

interface Results {
  query: string;
  items: GeocodeResult[];
  error: string | null;
}

interface SearchBoxProps {
  onPick: (site: Site) => void;
}

/** Address search: results appear as you type; Enter picks the highlighted result, or the first one. */
export function SearchBox({ onPick }: SearchBoxProps) {
  const listId = useId();
  const form = useRef<HTMLFormElement>(null);
  const timer = useRef(0);
  const sequence = useRef(0);
  const [text, setText] = useState("");
  const [results, setResults] = useState<Results | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);

  useEffect(() => {
    const closeOutside = (event: MouseEvent) => {
      if (!(event.target instanceof Node) || !form.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("click", closeOutside);
    return () => {
      document.removeEventListener("click", closeOutside);
      window.clearTimeout(timer.current);
    };
  }, []);

  async function search(query: string): Promise<GeocodeResult[]> {
    const seq = ++sequence.current;
    try {
      const items = await api.geocode(query);
      if (seq !== sequence.current) return [];
      setResults({ query, items, error: null });
      setActive(-1);
      setOpen(true);
      return items;
    } catch (error) {
      if (seq === sequence.current) {
        setResults({ query: "", items: [], error: messageOf(error) });
        setActive(-1);
        setOpen(true);
      }
      return [];
    }
  }

  function pick(item: GeocodeResult | undefined) {
    if (!item) return;
    const label = shortLabel(item.label);
    setOpen(false);
    setActive(-1);
    setText(label);
    onPick({ id: null, label, lat: item.lat, lon: item.lon });
  }

  function change(value: string) {
    setText(value);
    window.clearTimeout(timer.current);
    const query = value.trim();
    if (query.length < 3) {
      setOpen(false);
      setActive(-1);
      return;
    }
    timer.current = window.setTimeout(() => {
      void search(query);
    }, 450);
  }

  async function submit(event: SyntheticEvent) {
    event.preventDefault();
    const query = text.trim();
    if (query.length < 3) return;
    window.clearTimeout(timer.current);
    if (results?.query === query) {
      pick(results.items[active >= 0 ? active : 0]);
      return;
    }
    pick((await search(query))[0]);
  }

  function keyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setOpen(false);
      setActive(-1);
      return;
    }
    const count = results?.items.length ?? 0;
    if (!open || !count || (event.key !== "ArrowDown" && event.key !== "ArrowUp")) return;
    event.preventDefault();
    const step = event.key === "ArrowDown" ? 1 : -1;
    setActive((index) => (index + step + count) % count);
  }

  const optionId = (index: number) => `${listId}-${index}`;
  const showList = open && results !== null;

  return (
    <form
      ref={form}
      className="capsule"
      role="search"
      autoComplete="off"
      onSubmit={(event) => {
        void submit(event);
      }}
    >
      <label className="sr-only" htmlFor={`${listId}-input`}>
        Search an address, street or neighborhood
      </label>
      <input
        id={`${listId}-input`}
        type="search"
        placeholder="Address or neighborhood"
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
      <button className="capsule-go" type="submit" aria-label="Search">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4 12h15M13 6l6 6-6 6" />
        </svg>
      </button>
      <ul id={listId} className="results" role="listbox" aria-label="Places found" hidden={!showList}>
        {results?.error ? (
          <li className="empty" role="option" aria-selected="false" aria-disabled="true">
            {results.error}
          </li>
        ) : results?.items.length ? (
          results.items.map((item, index) => (
            <li
              key={`${item.lat},${item.lon},${index}`}
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
              {item.label}
            </li>
          ))
        ) : (
          <li className="empty" role="option" aria-selected="false" aria-disabled="true">
            No matches. Try a street or neighborhood name.
          </li>
        )}
      </ul>
    </form>
  );
}
