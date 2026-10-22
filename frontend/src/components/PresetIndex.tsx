import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Preset } from "../api/types";
import { fmtLat, fmtLon, letter } from "../lib/format";
import { PRESETS } from "../lib/presets";

interface PresetIndexProps {
  selectedId: string | null;
  onSelect: (preset: Preset) => void;
}

export function PresetIndex({ selectedId, onSelect }: PresetIndexProps) {
  // The bundled list shows at once; the server's, when it answers, replaces it.
  const [presets, setPresets] = useState<readonly Preset[]>(PRESETS);

  useEffect(() => {
    let live = true;
    api.presets().then(
      (loaded) => {
        if (live && loaded.length) setPresets(loaded);
      },
      () => {
        // The bundled list stands.
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
        {presets.map((preset, index) => (
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
        ))}
      </ol>
    </div>
  );
}
