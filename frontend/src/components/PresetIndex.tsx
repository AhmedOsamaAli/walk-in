import { useEffect, useState } from "react";
import { api, messageOf } from "../api/client";
import type { Preset } from "../api/types";
import { fmtLat, fmtLon, letter } from "../lib/format";

interface PresetIndexProps {
  selectedId: string | null;
  onSelect: (preset: Preset) => void;
}

export function PresetIndex({ selectedId, onSelect }: PresetIndexProps) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.presets().then(
      (loaded) => {
        if (live) setPresets(loaded);
      },
      (failure: unknown) => {
        if (live) setError(messageOf(failure));
      },
    );
    return () => {
      live = false;
    };
  }, []);

  return (
    <div className="index">
      <div className="index-head mono">
        <span>Index of sites</span>
        <span>Lat / Lon</span>
      </div>
      <ol className="index-list">
        {error ? (
          <li className="muted">{error}</li>
        ) : (
          presets.map((preset, index) => (
            <li key={preset.id}>
              <button
                className="site-btn"
                type="button"
                aria-pressed={preset.id === selectedId}
                onClick={() => {
                  onSelect(preset);
                }}
              >
                <span className="letter">{letter(index)}</span>
                <span>
                  <span className="name">{preset.label}</span>
                  <span className="blurb">{preset.blurb}</span>
                </span>
                <span className="coords mono">
                  {fmtLat(preset.lat)}
                  <br />
                  {fmtLon(preset.lon)}
                </span>
                <span className="arrow" aria-hidden="true">
                  →
                </span>
              </button>
            </li>
          ))
        )}
      </ol>
    </div>
  );
}
