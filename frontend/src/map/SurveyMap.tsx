import { useEffect, useEffectEvent, useRef } from "react";
import type { GapRow, PlaceCard, Walk } from "../api/types";
import type { Theme } from "../state/theme";
import { BlueprintMap, type MapPoint } from "./controller";
import { Legend } from "./Legend";

interface SurveyMapProps {
  theme: Theme;
  site: MapPoint | null;
  walk: Walk | null;
  minutes: number;
  /** The survey view is showing: the legend is up and clicks no longer drop pins. */
  surveying: boolean;
  /** Counts survey runs; a new value frames the walk and starts the radar. */
  run: number;
  streaming: boolean;
  places: PlaceCard[] | null;
  gap: GapRow | null;
  onPick: (point: MapPoint) => void;
}

export function SurveyMap({ theme, site, walk, minutes, surveying, run, streaming, places, gap, onPick }: SurveyMapProps) {
  const canvas = useRef<HTMLDivElement>(null);
  const readout = useRef<HTMLDivElement>(null);
  const controller = useRef<BlueprintMap | null>(null);

  const pick = useEffectEvent((lat: number, lon: number) => {
    if (!surveying) onPick({ lat, lon });
  });
  const beginRun = useEffectEvent(() => {
    controller.current?.startRun(minutes);
  });

  useEffect(() => {
    if (!canvas.current || !readout.current) return;
    const map = new BlueprintMap(canvas.current, readout.current, (lat, lon) => {
      pick(lat, lon);
    });
    controller.current = map;
    return () => {
      map.destroy();
      controller.current = null;
    };
  }, []);

  useEffect(() => {
    controller.current?.setTheme(theme);
  }, [theme]);

  useEffect(() => {
    if (site) controller.current?.selectSite(site);
  }, [site]);

  // Selecting a site clears the drawn walk, so the walk is shown again even when it is the same object.
  useEffect(() => {
    if (walk) controller.current?.showWalk(walk);
  }, [site, walk]);

  useEffect(() => {
    if (run > 0) beginRun();
  }, [run]);

  useEffect(() => {
    if (!streaming) controller.current?.finishRun();
  }, [streaming]);

  useEffect(() => {
    if (!surveying) controller.current?.clearRun();
  }, [surveying]);

  useEffect(() => {
    if (places) controller.current?.plotBlock(places);
  }, [places]);

  useEffect(() => {
    controller.current?.showGap(gap);
  }, [gap]);

  return (
    <aside className="map-frame" aria-label="Map of the site and its surroundings">
      <div ref={canvas} className="map-canvas" />
      <span className="crop tl" aria-hidden="true" />
      <span className="crop tr" aria-hidden="true" />
      <span className="crop bl" aria-hidden="true" />
      <span className="crop br" aria-hidden="true" />
      <div ref={readout} className="readout mono" aria-hidden="true" />
      {site ? null : <div className="map-hint mono">Click the map to place a site</div>}
      {surveying ? <Legend walkMinutes={walk?.minutes ?? minutes} gapGenre={gap?.genre ?? null} /> : null}
    </aside>
  );
}
