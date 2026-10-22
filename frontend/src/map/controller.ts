import * as L from "leaflet";
import { api } from "../api/client";
import type { FavoritePlace, GapRow, HeatCell, LatLon, PlaceCard, Walk } from "../api/types";
import { coords } from "../lib/format";
import { prefersReducedMotion } from "../lib/motion";
import type { Theme } from "../state/theme";
import { arc, cellSpan, metersToLat, WALK_M_PER_MIN } from "./geometry";
import { placeTip } from "./tooltip";

export interface MapPoint {
  lat: number;
  lon: number;
}

/**
 * Esri's light and dark gray canvases, each split into a base and a labels layer so the labels sit above the taste
 * grid. Esri serves them over HTTP/1.1 only, so tiles alternate between its two hosts to double the connections.
 */
const ESRI = "https://{s}.arcgisonline.com/ArcGIS/rest/services/Canvas";
const TILES: Record<Theme, { base: string; labels: string }> = {
  light: {
    base: `${ESRI}/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
    labels: `${ESRI}/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
  },
  dark: {
    base: `${ESRI}/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
    labels: `${ESRI}/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
  },
};
const TILE_OPTIONS: L.TileLayerOptions = { subdomains: ["server", "services"], maxNativeZoom: 16, maxZoom: 19, className: "basemap" };
/** The data credits Esri's and OpenStreetMap's terms require. */
const CREDITS =
  'Powered by <a href="https://www.esri.com">Esri</a> &middot; Esri, HERE, Garmin &middot; &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
/** OpenStreetMap's attribution guideline lets the credits collapse after the first pan, zoom or click, or this long. */
const CREDITS_OPEN_MS = 5000;
/** Matches the basemap fade in map.css. */
const BASEMAP_FADE_MS = 600;
/** How long a theme switch waits for the new tiles before showing them anyway, say on a hidden map. */
const BASEMAP_SWAP_TIMEOUT_MS = 30_000;
const TIP: L.TooltipOptions = { className: "tip", direction: "top", offset: [0, -6], opacity: 1 };
const PIN_HTML = '<div class="site-pin"><span class="sq"></span><span class="tagl">Site</span></div>';

type Located<T extends PlaceCard> = T & { lat: number; lon: number };
const located = <T extends PlaceCard>(place: T): place is Located<T> => place.lat != null && place.lon != null;

/** One theme's tile layers. */
interface Basemap {
  theme: Theme;
  layers: L.TileLayer[];
}

function dropBasemap(basemap: Basemap | null): void {
  for (const layer of basemap?.layers ?? []) layer.remove();
}

/**
 * The survey map: Leaflet driven imperatively, outside React's render. Overlays carry class names and take their
 * colors from the theme's CSS variables, so a theme switch only swaps the tiles.
 */
export class BlueprintMap {
  private readonly map: L.Map;
  private readonly readout: HTMLElement;
  /** The current theme's tiles, shown or still loading. */
  private basemap: Basemap | null = null;
  /** The previous theme's tiles, kept on screen until the current ones have loaded. */
  private fading: Basemap | null = null;
  private readonly gridRenderer: L.Canvas;
  private readonly layers: Record<"grid" | "ring" | "block" | "gap" | "site", L.LayerGroup>;
  /** On narrow screens the frame grows for the survey and shrinks back for the brief; Leaflet must re-measure it. */
  private readonly resizer: ResizeObserver;
  private readonly idleQueue: (() => void)[] = [];
  private readonly grids = new Map<string, HeatCell[]>();
  private readonly timers = new Set<number>();
  private moving = false;
  private pointerOnMap = false;
  private destroyed = false;
  private site: MapPoint | null = null;
  private walk: Walk | null = null;
  private fallbackRadius = 10 * WALK_M_PER_MIN;
  private running = false;
  private radar: L.Marker | null = null;
  private gap: GapRow | null = null;
  private runToken = 0;
  private moveToken = 0;

  constructor(element: HTMLElement, readout: HTMLElement, onPick: (lat: number, lon: number) => void) {
    this.readout = readout;
    const map = L.map(element, { zoomControl: false, worldCopyJump: true, attributionControl: false }).setView([40.735, -73.975], 12);
    this.map = map;
    L.control.zoom({ position: "topright" }).addTo(map);
    this.addCredits();
    const scale = L.control.scale({ position: "bottomright", imperial: false, maxWidth: 120 }).addTo(map);
    // The scale bar is a label, not a place: a click on it must not drop a pin under it.
    const scaleBox = scale.getContainer();
    if (scaleBox) L.DomEvent.disableClickPropagation(scaleBox);
    for (const [name, zIndex] of [["grid", 350], ["labels", 360], ["radar", 380]] as const) {
      const pane = map.createPane(name);
      pane.style.zIndex = String(zIndex);
      pane.style.pointerEvents = "none";
    }
    map.getPane("grid")?.classList.add("grid-pane");
    this.gridRenderer = L.canvas({ padding: 0.5, pane: "grid" });
    this.layers = {
      grid: L.layerGroup().addTo(map),
      ring: L.layerGroup().addTo(map),
      block: L.layerGroup().addTo(map),
      gap: L.layerGroup().addTo(map),
      site: L.layerGroup().addTo(map),
    };

    map.on("mouseover", () => {
      this.pointerOnMap = true;
    });
    map.on("mouseout", () => {
      this.pointerOnMap = false;
      this.showCenter();
    });
    map.on("move", () => {
      this.showCenter();
    });
    map.on("mousemove", (event: L.LeafletMouseEvent) => {
      this.readout.textContent = coords(event.latlng.lat, event.latlng.lng);
    });
    map.on("click", (event: L.LeafletMouseEvent) => {
      const { lat, lng } = event.latlng.wrap();
      onPick(lat, lng);
    });
    // Paths added while the map is flying are projected against a moving origin and appear offset until the
    // flight ends, so every overlay is drawn only once the map is idle.
    map.on("movestart", () => {
      this.moving = true;
    });
    map.on("moveend", () => {
      this.moving = false;
      for (const draw of this.idleQueue.splice(0)) draw();
    });
    // Keeps the center where it was, so a resized frame never pushes the site off to one side.
    this.resizer = new ResizeObserver(() => {
      map.invalidateSize();
    });
    this.resizer.observe(element);
    this.showCenter();
  }

  destroy(): void {
    this.destroyed = true;
    this.resizer.disconnect();
    for (const timer of this.timers) window.clearTimeout(timer);
    this.idleQueue.length = 0;
    this.map.off("zoomend", this.resizeRadar);
    this.map.remove();
  }

  /** Swaps the tiles; overlays restyle themselves from the theme's variables, except the canvas grid. */
  setTheme(theme: Theme): void {
    this.showBasemap(theme);
    const fillColor = this.gridColor();
    this.layers.grid.eachLayer((layer) => {
      if (layer instanceof L.Path) layer.setStyle({ fillColor });
    });
  }

  selectSite(site: MapPoint): void {
    this.site = site;
    this.walk = null;
    this.clearRun();
    this.layers.ring.clearLayers();
    this.drawPin(site);
    this.map.flyTo([site.lat, site.lon], Math.max(this.map.getZoom(), 15), this.flight(1.4));
  }

  showWalk(walk: Walk): void {
    const previous = this.walk;
    this.walk = walk;
    const same =
      previous !== null &&
      previous.minutes === walk.minutes &&
      previous.ring.length === walk.ring.length &&
      this.layers.ring.getLayers().length > 0;
    if (!same) {
      this.whenIdle(() => {
        this.drawWalk(walk);
      });
    }
  }

  /** A survey started: frame the walk and sweep it with the radar until the run ends. */
  startRun(minutes: number): void {
    this.clearRun();
    this.running = true;
    this.fallbackRadius = minutes * WALK_M_PER_MIN;
    // The frame may have just changed size for the survey view; frame the walk against its new size.
    this.map.invalidateSize();
    this.map.flyToBounds(this.walkBounds(), { padding: [70, 70], maxZoom: 16, ...this.flight(1.2) });
    this.startRadar();
  }

  finishRun(): void {
    this.running = false;
    this.stopRadar();
  }

  /** Removes everything a survey drew, keeping the site and its walk. */
  clearRun(): void {
    this.runToken += 1;
    this.running = false;
    this.gap = null;
    this.layers.block.clearLayers();
    this.clearGap();
    this.stopRadar();
  }

  plotBlock(places: PlaceCard[]): void {
    const token = this.runToken;
    this.whenIdle(() => {
      if (token !== this.runToken) return;
      this.layers.block.clearLayers();
      const reach = this.walk?.radius_m ?? 10 * WALK_M_PER_MIN;
      const reduced = prefersReducedMotion();
      for (const place of places.filter(located)) {
        const dot = L.circleMarker([place.lat, place.lon], { radius: 3.4, stroke: false, className: "pdot place" })
          .bindTooltip(placeTip(place), TIP)
          .addTo(this.layers.block);
        const element = dot.getElement();
        if (element instanceof SVGElement) {
          // Places ripple outward from the site.
          const share = Math.min(1.3, (place.distance_m ?? reach / 2) / reach);
          element.style.animationDelay = reduced ? "0ms" : `${Math.round(share * 1100)}ms`;
        }
      }
    });
  }

  /** Shows one gap's competitors, favorites, trips and taste grid, or clears them for null. */
  showGap(gap: GapRow | null): void {
    this.gap = gap;
    if (!gap) {
      this.clearGap();
      return;
    }
    const token = this.runToken;
    this.whenIdle(() => {
      if (this.gap === gap && token === this.runToken) this.drawGap(gap);
    });
  }

  private readonly resizeRadar = (): void => {
    if (this.radar && this.site) this.radar.setIcon(this.radarIcon(this.site));
  };

  private whenIdle(draw: () => void): void {
    if (this.moving) this.idleQueue.push(draw);
    else draw();
  }

  private later(callback: () => void, ms: number): void {
    const timer = window.setTimeout(() => {
      this.timers.delete(timer);
      if (!this.destroyed) callback();
    }, ms);
    this.timers.add(timer);
  }

  private flight(duration: number): L.ZoomPanOptions {
    return { animate: !prefersReducedMotion(), duration };
  }

  /** The canvas grid cannot be styled with CSS, so it reads its color from the theme. */
  private gridColor(): string {
    return getComputedStyle(this.map.getContainer()).getPropertyValue("--map-grid-fill").trim() || "#0000ff";
  }

  /**
   * Loads the theme's tiles hidden under the ones on screen, fades them in once every visible tile has arrived and only
   * then drops the old, so a theme switch never shows an empty or half-swapped map while tiles download. Switching
   * back before then keeps what is on screen.
   */
  private showBasemap(theme: Theme): void {
    if (this.basemap?.theme === theme) return;
    if (this.fading?.theme === theme) {
      dropBasemap(this.basemap);
      this.basemap = this.fading;
      this.fading = null;
      return;
    }
    dropBasemap(this.fading);
    const previous = this.basemap;
    const opacity = previous ? 0 : 1;
    const tiles = TILES[theme];
    const next: Basemap = {
      theme,
      layers: [
        L.tileLayer(tiles.base, { ...TILE_OPTIONS, opacity }),
        L.tileLayer(tiles.labels, { ...TILE_OPTIONS, opacity, pane: "labels" }),
      ],
    };
    this.fading = previous;
    this.basemap = next;
    for (const layer of next.layers) layer.addTo(this.map);
    if (!previous) return;

    let shown = false;
    const show = () => {
      if (shown || this.basemap !== next) return;
      shown = true;
      for (const layer of next.layers) layer.setOpacity(1);
      this.later(() => {
        if (this.fading !== previous) return;
        dropBasemap(previous);
        this.fading = null;
      }, BASEMAP_FADE_MS);
    };
    let loading = next.layers.length;
    for (const layer of next.layers) {
      layer.once("load", () => {
        loading -= 1;
        if (loading === 0) show();
      });
    }
    this.later(show, BASEMAP_SWAP_TIMEOUT_MS);
  }

  private showCenter(): void {
    if (this.pointerOnMap) return;
    const center = this.map.getCenter();
    this.readout.textContent = coords(center.lat, center.lng);
  }

  /**
   * The credits in the map's corner: in full when the map appears, then collapsed into an (i) button after the first
   * pan, zoom or click, or after five seconds, as OpenStreetMap's guideline allows. The button opens them again.
   * Leaflet's own control rewrites its contents whenever the tiles change, so this one is separate.
   */
  private addCredits(): void {
    const control = new L.Control({ position: "bottomright" });
    control.onAdd = () => {
      const box = L.DomUtil.create("div", "credits open");
      const button = L.DomUtil.create("button", "credits-toggle", box);
      button.type = "button";
      button.textContent = "i";
      button.setAttribute("aria-label", "Map credits");
      button.setAttribute("aria-controls", "map-credits");
      button.setAttribute("aria-expanded", "true");
      const text = L.DomUtil.create("span", "credits-text", box);
      text.id = "map-credits";
      text.innerHTML = CREDITS;
      L.DomEvent.disableClickPropagation(box);
      L.DomEvent.disableScrollPropagation(box);

      let settled = false;
      const show = (open: boolean) => {
        box.classList.toggle("open", open);
        button.setAttribute("aria-expanded", String(open));
      };
      const collapse = () => {
        if (settled) return;
        settled = true;
        show(false);
      };
      button.addEventListener("click", () => {
        settled = true;
        show(!box.classList.contains("open"));
      });
      this.map.once("movestart", collapse);
      this.map.once("zoomstart", collapse);
      this.map.once("click", collapse);
      this.later(collapse, CREDITS_OPEN_MS);
      return box;
    };
    control.addTo(this.map);
  }

  private drawPin(site: MapPoint): void {
    this.layers.site.clearLayers();
    const icon = L.divIcon({ className: "site-icon", iconSize: [0, 0], html: PIN_HTML });
    L.marker([site.lat, site.lon], { icon, interactive: false, keyboard: false }).addTo(this.layers.site);
  }

  private drawWalk(walk: Walk): void {
    if (walk !== this.walk) return;
    this.layers.ring.clearLayers();
    L.polygon(walk.ring, { weight: 1.4, dashArray: "4 6", lineJoin: "round", interactive: false, className: "walk" }).addTo(
      this.layers.ring,
    );
  }

  private walkBounds(): L.LatLngBounds {
    if (this.walk) return L.latLngBounds(this.walk.ring);
    return this.site ? L.latLng(this.site.lat, this.site.lon).toBounds(1600) : this.map.getBounds();
  }

  private radarIcon(site: MapPoint): L.DivIcon {
    const center = L.latLng(site.lat, site.lon);
    const radius = this.walk?.radius_m ?? this.fallbackRadius;
    const a = this.map.latLngToLayerPoint(center);
    const b = this.map.latLngToLayerPoint(L.latLng(center.lat + metersToLat(radius), center.lng));
    const r = Math.max(12, Math.round(Math.abs(a.y - b.y)));
    return L.divIcon({ className: "radar-icon", iconSize: [r * 2, r * 2], iconAnchor: [r, r], html: '<div class="radar"></div>' });
  }

  private startRadar(): void {
    this.stopRadar();
    if (!this.site || prefersReducedMotion()) return;
    const token = this.runToken;
    this.whenIdle(() => {
      if (!this.running || this.radar || !this.site || token !== this.runToken) return;
      this.radar = L.marker([this.site.lat, this.site.lon], {
        icon: this.radarIcon(this.site),
        pane: "radar",
        interactive: false,
        keyboard: false,
      }).addTo(this.map);
      this.map.on("zoomend", this.resizeRadar);
    });
  }

  private stopRadar(): void {
    this.radar?.remove();
    this.radar = null;
    this.map.off("zoomend", this.resizeRadar);
  }

  private clearGap(): void {
    this.moveToken += 1;
    this.layers.gap.clearLayers();
    this.layers.grid.clearLayers();
    this.map.getPane("grid")?.classList.remove("in");
  }

  private drawGap(gap: GapRow): void {
    const site = this.site;
    if (!site) return;
    this.clearGap();
    const origin: LatLon = [site.lat, site.lon];
    for (const place of (gap.competitors ?? []).filter(located)) {
      L.circleMarker([place.lat, place.lon], { radius: 5, weight: 1.5, className: "pdot comp" })
        .bindTooltip(placeTip(place), TIP)
        .addTo(this.layers.gap);
    }
    const local = gap.favorites_kind === "local";
    const favorites = (gap.favorites ?? []).filter(located);
    for (const place of favorites) {
      const style = local ? { radius: 5.5, className: "pdot fav" } : { radius: 5, className: "pdot famous" };
      L.circleMarker([place.lat, place.lon], { ...style, weight: 1.5 }).bindTooltip(placeTip(place), TIP).addTo(this.layers.gap);
    }
    if (favorites.length) {
      // Only places locals love more than the city say anything about travel; the city's famous spots do not.
      const trips = local ? favorites.filter((place) => !place.within_walk) : [];
      this.afterMove(() => {
        this.drawTrips(origin, trips);
      });
      const bounds = L.latLngBounds([origin, ...favorites.map((place): LatLon => [place.lat, place.lon])]);
      if (this.walk) bounds.extend(this.walkBounds());
      this.map.flyToBounds(bounds, { padding: [80, 80], maxZoom: 15, ...this.flight(1.2) });
    }
    void this.drawGrid(gap);
  }

  private drawTrips(origin: LatLon, trips: Located<FavoritePlace>[]): void {
    trips.forEach((place, k) => {
      const line = L.polyline(arc(origin, [place.lat, place.lon]), { weight: 1.3, interactive: false, className: "leak" }).addTo(
        this.layers.gap,
      );
      this.drawLine(line, k * 80);
    });
  }

  /** Runs once the next flight ends, or after a timeout if the map does not move; a newer gap cancels it. */
  private afterMove(callback: () => void): void {
    const token = ++this.moveToken;
    let ran = false;
    const run = () => {
      if (ran || token !== this.moveToken || this.destroyed) return;
      ran = true;
      callback();
    };
    this.map.once("moveend", run);
    this.later(run, prefersReducedMotion() ? 50 : 1500);
  }

  private drawLine(line: L.Polyline, delay: number): void {
    const path = line.getElement();
    if (!(path instanceof SVGPathElement) || prefersReducedMotion()) return;
    const length = path.getTotalLength();
    path.style.transition = "none";
    path.style.strokeDasharray = `${length}`;
    path.style.strokeDashoffset = `${length}`;
    // Reading layout commits the hidden dash before the transition is restored, so the line draws itself.
    path.getBoundingClientRect();
    path.style.transition = "";
    path.addEventListener(
      "transitionend",
      () => {
        path.style.strokeDasharray = "";
        path.style.strokeDashoffset = "";
      },
      { once: true },
    );
    this.later(() => {
      path.style.strokeDashoffset = "0";
    }, 40 + delay);
  }

  private async drawGrid(gap: GapRow): Promise<void> {
    const site = this.site;
    if (!site) return;
    const key = `${site.lat.toFixed(5)},${site.lon.toFixed(5)}|${gap.genre_id}`;
    let cells = this.grids.get(key);
    if (!cells) {
      try {
        cells = (await api.heatmap(site.lat, site.lon, gap.genre_id)).cells ?? [];
        this.grids.set(key, cells);
      } catch {
        cells = [];
      }
    }
    if (this.gap !== gap || this.destroyed) return;
    const shown = cells;
    this.whenIdle(() => {
      if (this.gap !== gap) return;
      this.layers.grid.clearLayers();
      const fillColor = this.gridColor();
      for (const cell of shown) {
        if (cell.affinity < 0.45) continue;
        const [dLat, dLon] = cellSpan(cell.geohash);
        const strength = (cell.affinity - 0.45) / 0.55;
        L.rectangle(
          [
            [cell.lat - dLat / 2, cell.lon - dLon / 2],
            [cell.lat + dLat / 2, cell.lon + dLon / 2],
          ],
          {
            renderer: this.gridRenderer,
            stroke: false,
            fillColor,
            fillOpacity: 0.04 + 0.32 * strength ** 1.8,
            interactive: false,
          },
        ).addTo(this.layers.grid);
      }
      const pane = this.map.getPane("grid");
      pane?.classList.remove("in");
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          pane?.classList.add("in");
        }),
      );
    });
  }
}
