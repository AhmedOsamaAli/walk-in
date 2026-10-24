import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { KitPoster } from "../../api/kit";
import { cssVars } from "../../lib/css";
import {
  homography,
  moveCorner,
  pixelBox,
  rectQuad,
  startQuad,
  toMatrix3d,
  warpInto,
  type Corner,
  type Point,
  type Quad,
} from "../../lib/perspective";
import { POSTER_H, POSTER_W } from "../../lib/poster";
import { PosterArt } from "./PosterArt";

const POSTER_RECT = rectQuad(POSTER_W, POSTER_H);
/** The most pixels a phone's browser draws on one canvas (Safari on iOS: 4096 × 4096). */
const MAX_PIXELS = 16_777_216;
/** A photo opens at most this many pixels across and down: a larger one is scaled down to it as it opens, still sharp
 * on any screen and in the picture to download, and light on a phone's memory. */
const MAX_SIDE = 3200;
/** A file larger than this is not opened at all. */
const MAX_MB = 50;
const UNREADABLE = "That file could not be opened as a picture. Try a JPEG or PNG photo.";
/** Where the Glass slider starts: the share of the window's own reflection laid over the poster. */
const GLASS_START = 30;
/** An arrow key's step, and Shift's, as shares of the photo's longer side. */
const STEP = 0.004;
const LEAP = 0.04;
const CORNERS: readonly { corner: Corner; label: string }[] = [
  { corner: 0, label: "Top-left corner" },
  { corner: 1, label: "Top-right corner" },
  { corner: 2, label: "Bottom-right corner" },
  { corner: 3, label: "Bottom-left corner" },
];
const ARROWS: Partial<Record<string, Point>> = {
  ArrowLeft: { x: -1, y: 0 },
  ArrowRight: { x: 1, y: 0 },
  ArrowUp: { x: 0, y: -1 },
  ArrowDown: { x: 0, y: 1 },
};
/** The typefaces the poster sets its words in. */
const POSTER_FACES = new Set(["Newsreader Variable", "Geist Variable", "Geist Mono Variable"]);
const SVG_NS = "http://www.w3.org/2000/svg";

/**
 * The owner's photo, read in the browser as a data: URL, which the site's content policy lets an image show (it has no
 * blob: in img-src). It is never uploaded or stored, and goes when it is removed or the page closes.
 */
interface Photo {
  url: string;
  /** The decoded photo, for the picture to download. */
  image: HTMLImageElement;
  /** Its size upright, as the camera turned it, and at most MAX_SIDE either way. */
  width: number;
  height: number;
}

/** A file that cannot be opened as a photo, with the words that tell the owner why. */
class PhotoError extends Error {}

interface Drag {
  corner: Corner;
  pointer: number;
  /** Where the pointer took hold, from the corner's centre, in CSS pixels: the corner keeps that distance. */
  dx: number;
  dy: number;
}

function readAsDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") resolve(reader.result);
      else reject(new Error("The file could not be read."));
    };
    reader.onerror = () => {
      reject(reader.error ?? new Error("The file could not be read."));
    };
    reader.readAsDataURL(blob);
  });
}

async function decodeImage(src: string): Promise<HTMLImageElement> {
  const image = new Image();
  image.src = src;
  await image.decode();
  return image;
}

/**
 * Reads the chosen file and decodes it, upright as the camera recorded it. A photo larger than MAX_SIDE either way is
 * scaled down to it on a canvas and kept as a JPEG.
 */
async function openPhoto(file: File): Promise<Photo> {
  if (file.type && !file.type.startsWith("image/")) throw new PhotoError("That file is not a picture. Choose a photo: a JPEG or PNG.");
  if (file.size > MAX_MB * 1024 * 1024) {
    throw new PhotoError(`That file is over ${MAX_MB} MB, too large to open here. Choose a smaller copy of the photo.`);
  }
  const original = await decodeImage(await readAsDataUrl(file));
  const { naturalWidth: width, naturalHeight: height } = original;
  if (!width || !height) throw new PhotoError(UNREADABLE);
  const scale = MAX_SIDE / Math.max(width, height);
  if (scale >= 1) return { url: original.src, image: original, width, height };
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  try {
    const context = canvas.getContext("2d");
    if (!context) throw new PhotoError(UNREADABLE);
    // On white: a JPEG keeps no transparency.
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.imageSmoothingQuality = "high";
    context.drawImage(original, 0, 0, canvas.width, canvas.height);
    const url = canvas.toDataURL("image/jpeg", 0.9);
    const image = await decodeImage(url);
    return { url, image, width: image.naturalWidth, height: image.naturalHeight };
  } finally {
    // Safari keeps a canvas's memory until it is shrunk.
    canvas.width = 0;
    canvas.height = 0;
  }
}

function scaled(quad: Quad, by: number): Quad {
  const [a, b, c, d] = quad;
  return [
    { x: a.x * by, y: a.y * by },
    { x: b.x * by, y: b.y * by },
    { x: c.x * by, y: c.y * by },
    { x: d.x * by, y: d.y * by },
  ];
}

/** The least the poster may shrink to: a square 4% of the photo's shorter side across. */
function leastArea(photo: Photo): number {
  const side = Math.min(photo.width, photo.height) * 0.04;
  return side * side;
}

function percent(share: number): string {
  return `${Math.round(share * 100)}%`;
}

// ---------- The picture to download ----------

/** The code points a unicode-range covers, as [first, last] pairs; a face without one covers them all. */
function unicodeRanges(value: string | undefined): [number, number][] {
  const ranges: [number, number][] = [];
  for (const part of (value ?? "").split(",")) {
    const match = /U\+([0-9a-f?]+)(?:-([0-9a-f]+))?/i.exec(part);
    const start = match?.[1];
    if (!start) continue;
    const end = match[2];
    ranges.push([parseInt(start.replace(/\?/g, "0"), 16), parseInt(end ?? start.replace(/\?/g, "f"), 16)]);
  }
  return ranges.length ? ranges : [[0, 0x10ffff]];
}

/** Every @font-face rule the page's style sheets hold, with the address its file is relative to. */
function* fontFaces(sheets: Iterable<CSSStyleSheet>): Generator<{ css: string; base: string }> {
  for (const sheet of sheets) {
    let rules: CSSRuleList;
    try {
      rules = sheet.cssRules;
    } catch {
      continue; // Another site's sheet, which a page may not read.
    }
    for (const rule of Array.from(rules)) {
      if (rule instanceof CSSFontFaceRule) yield { css: rule.cssText, base: sheet.href ?? document.baseURI };
      else if (rule instanceof CSSImportRule && rule.styleSheet) yield* fontFaces([rule.styleSheet]);
    }
  }
}

const fontFiles = new Map<string, Promise<string>>();

/** A font file as a data: URL, fetched once a page. */
function fontFile(url: string): Promise<string> {
  let file = fontFiles.get(url);
  if (!file) {
    file = fetch(url).then(async (response) => {
      if (!response.ok) throw new Error(`The font answered ${response.status}.`);
      return readAsDataUrl(await response.blob());
    });
    fontFiles.set(url, file);
    file.catch(() => {
      fontFiles.delete(url);
    });
  }
  return file;
}

/**
 * The page's own @font-face rules for the poster's typefaces, each with its file written in: an SVG drawn as an image
 * may load nothing from outside itself, and would set its words in a system face instead. Only the subsets that hold
 * the poster's characters. A face whose file cannot be fetched is left out, and its words fall back.
 */
async function posterFontCss(text: string): Promise<string> {
  const used = Array.from(new Set(Array.from(text, (character) => character.codePointAt(0) ?? 0)));
  const faces: { css: string; url: string }[] = [];
  for (const { css, base } of fontFaces(document.styleSheets)) {
    const family = /font-family:\s*([^;]+);/i.exec(css)?.[1]?.replace(/["']/g, "").trim();
    if (!family || !POSTER_FACES.has(family)) continue;
    const ranges = unicodeRanges(/unicode-range:\s*([^;]+);/i.exec(css)?.[1]);
    if (!used.some((point) => ranges.some(([first, last]) => point >= first && point <= last))) continue;
    const href = /url\(\s*(["']?)([^"')]+)\1\s*\)/.exec(css)?.[2];
    if (href) faces.push({ css, url: new URL(href, base).href });
  }
  const rules = await Promise.all(
    faces.map(async ({ css, url }) => {
      try {
        return css.replace(/url\([^)]*\)/, `url("${await fontFile(url)}")`);
      } catch {
        return "";
      }
    }),
  );
  return rules.join("\n");
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      resolve(image);
    };
    image.onerror = () => {
      reject(new Error("The poster could not be drawn."));
    };
    image.src = src;
  });
}

/**
 * The poster as pixels, drawn from the SVG on the page with its typefaces written in, at about the size it takes in
 * the photo: the warp then neither blurs it nor makes its fine lines shimmer.
 */
async function posterPixels(svg: SVGSVGElement, quad: Quad): Promise<ImageData> {
  const [tl, tr, br, bl] = quad;
  const across = Math.max(Math.hypot(tr.x - tl.x, tr.y - tl.y), Math.hypot(br.x - bl.x, br.y - bl.y)) / POSTER_W;
  const down = Math.max(Math.hypot(bl.x - tl.x, bl.y - tl.y), Math.hypot(br.x - tr.x, br.y - tr.y)) / POSTER_H;
  const scale = Math.min(Math.max(across, down, 0.25), Math.sqrt(MAX_PIXELS / 2 / (POSTER_W * POSTER_H)));
  const width = Math.round(POSTER_W * scale);
  const height = Math.round(POSTER_H * scale);
  const copy = svg.cloneNode(true);
  if (!(copy instanceof SVGSVGElement)) throw new Error("The poster could not be copied.");
  copy.setAttribute("width", String(width));
  copy.setAttribute("height", String(height));
  const style = document.createElementNS(SVG_NS, "style");
  style.textContent = await posterFontCss(svg.textContent);
  copy.prepend(style);
  const markup = new XMLSerializer().serializeToString(copy);
  const image = await loadImage(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  try {
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) throw new Error("This browser cannot draw the picture.");
    context.drawImage(image, 0, 0, width, height);
    return context.getImageData(0, 0, width, height);
  } finally {
    canvas.width = 0;
    canvas.height = 0;
  }
}

function trace(context: CanvasRenderingContext2D, quad: Quad): void {
  const [first, ...rest] = quad;
  context.beginPath();
  context.moveTo(first.x, first.y);
  for (const point of rest) context.lineTo(point.x, point.y);
  context.closePath();
}

/** The photo with the poster in place and the window's reflection over it, as a JPEG at the photo's size as opened. */
async function makePicture(photo: Photo, quad: Quad, glass: number, svg: SVGSVGElement): Promise<Blob> {
  const { width, height } = photo;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  try {
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) throw new Error("This browser cannot draw the picture.");
    context.drawImage(photo.image, 0, 0, width, height);
    const source = await posterPixels(svg, quad);
    const toSource = homography(quad, rectQuad(source.width, source.height));
    if (!toSource) throw new Error("The poster's corners are out of shape.");
    const box = pixelBox(quad, width, height);
    if (box.width > 0 && box.height > 0) {
      const target = context.getImageData(box.x, box.y, box.width, box.height);
      warpInto(target, source, toSource, box.x, box.y);
      context.putImageData(target, box.x, box.y);
    }
    if (glass > 0) {
      // The window's own light laid back over the poster, as the screen does it: "screen" brightens, never darkens.
      context.save();
      trace(context, quad);
      context.clip();
      context.globalCompositeOperation = "screen";
      context.globalAlpha = glass;
      context.drawImage(photo.image, 0, 0, width, height);
      context.restore();
    }
    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, "image/jpeg", 0.92);
    });
    if (!blob) throw new Error("The picture could not be saved.");
    return blob;
  } finally {
    // Safari keeps a canvas's memory until it is shrunk.
    canvas.width = 0;
    canvas.height = 0;
  }
}

function save(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 2000);
}

// ---------- On the page ----------

interface WindowPreviewProps {
  poster: KitPoster;
  /** The poster's QR code link, as the poster beside it has it. */
  link: string | null;
  /** The downloaded picture's file name. */
  fileName: string;
}

/**
 * "See it in your window": the owner adds a photo of their storefront and drags the poster's four corners onto the
 * window; the poster follows in perspective. The photo never leaves the browser: it is read on the device, is not
 * uploaded or stored, and goes when it is removed or the page closes. The picture to download is drawn at its size.
 */
export function WindowPreview({ poster, link, fileName }: WindowPreviewProps) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const ask = useRef<HTMLButtonElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const hint = useRef<HTMLParagraphElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<Drag | null>(null);
  const opened = useRef(0);
  /** Where the focus goes once a photo comes or goes: to the instructions, or back to the button that chooses one. */
  const focusNext = useRef<"hint" | "ask" | null>(null);
  const [photo, setPhoto] = useState<Photo | null>(null);
  const [quad, setQuad] = useState<Quad | null>(null);
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  const [glass, setGlass] = useState(GLASS_START);
  const [active, setActive] = useState<Corner | null>(null);
  const [opening, setOpening] = useState(false);
  const [making, setMaking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [news, setNews] = useState("");
  const art = useMemo(() => <PosterArt poster={poster} link={link} svgRef={svg} />, [poster, link]);

  useEffect(() => {
    const node = stage.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const { width, height } = entry.contentRect;
      setSize((old) => (old?.width === width && old.height === height ? old : { width, height }));
    });
    observer.observe(node);
    return () => {
      observer.disconnect();
    };
  }, [photo]);

  // The first photo replaces the button that chose it, and removing it brings the button back: the focus follows.
  useEffect(() => {
    const next = focusNext.current;
    focusNext.current = null;
    if (next === "hint" && photo) hint.current?.focus();
    else if (next === "ask" && !photo) ask.current?.focus();
  }, [photo]);

  async function choose(file: File) {
    const ticket = ++opened.current;
    setOpening(true);
    setError(null);
    try {
      const next = await openPhoto(file);
      if (ticket !== opened.current) return;
      focusNext.current = photo === null ? "hint" : null;
      setSize(null);
      setPhoto(next);
      setQuad(startQuad(next.width, next.height, POSTER_W / POSTER_H));
      setNews("Photo added. Drag the poster's corners onto the corners of the window.");
    } catch (problem) {
      if (ticket === opened.current) setError(problem instanceof PhotoError ? problem.message : UNREADABLE);
    } finally {
      if (ticket === opened.current) setOpening(false);
    }
  }

  function pick() {
    if (!opening) input.current?.click();
  }

  /** Lets the photo go: nothing of it is kept. A photo still opening is dropped too. */
  function remove() {
    opened.current += 1;
    drag.current = null;
    focusNext.current = "ask";
    setOpening(false);
    setPhoto(null);
    setQuad(null);
    setSize(null);
    setActive(null);
    setGlass(GLASS_START);
    setError(null);
    setNews("Photo removed.");
  }

  const picker = (
    <input
      ref={input}
      type="file"
      accept="image/*"
      hidden
      onChange={(event) => {
        const file = event.currentTarget.files?.[0];
        // Cleared, so choosing the same file again still counts.
        event.currentTarget.value = "";
        if (file) void choose(file);
      }}
    />
  );
  // Keyed, so it stays the same element whether a photo is in or not: a screen reader hears each change.
  const status = (
    <p key="status" className="sr-only" role="status" aria-live="polite">
      {news}
    </p>
  );

  if (!photo || !quad) {
    return (
      <div className="win no-print">
        <div className="win-ask">
          <div className="win-ask-text">
            <h3 className="win-title">See it in your window</h3>
            <p className="win-lead">Add a photo of your storefront. It stays on this device.</p>
          </div>
          <button ref={ask} type="button" className="ink-button" aria-disabled={opening} aria-busy={opening} onClick={pick}>
            {opening ? "Opening the photo…" : "Choose a photo"}
          </button>
          {picker}
        </div>
        <p className="win-error" role="alert">
          {error ?? ""}
        </p>
        {status}
      </div>
    );
  }

  const shown = photo;
  const placed = quad;
  const onStage = size ? scaled(placed, size.width / shown.width) : null;
  const toStage = onStage ? homography(POSTER_RECT, onStage) : null;
  const clip = onStage ? `polygon(${onStage.map((point) => `${point.x}px ${point.y}px`).join(", ")})` : undefined;

  function grab(corner: Corner, event: PointerEvent<HTMLButtonElement>) {
    const node = stage.current;
    if (event.button !== 0 || !node) return;
    // Captured, the corner keeps the pointer when it runs off the handle. The press itself is left to the browser,
    // which focuses the handle (so the arrow keys can finish the job) without the keyboard's ring.
    event.currentTarget.setPointerCapture(event.pointerId);
    const box = node.getBoundingClientRect();
    const scale = box.width / shown.width;
    const at = placed[corner];
    drag.current = {
      corner,
      pointer: event.pointerId,
      dx: event.clientX - (box.left + at.x * scale),
      dy: event.clientY - (box.top + at.y * scale),
    };
    setActive(corner);
  }

  function follow(event: PointerEvent<HTMLButtonElement>) {
    const held = drag.current;
    const node = stage.current;
    if (held?.pointer !== event.pointerId || !node) return;
    const box = node.getBoundingClientRect();
    const scale = shown.width / box.width;
    const to = { x: (event.clientX - held.dx - box.left) * scale, y: (event.clientY - held.dy - box.top) * scale };
    setQuad((old) => (old ? moveCorner(old, held.corner, to, shown, leastArea(shown)) : old));
  }

  function release(event: PointerEvent<HTMLButtonElement>) {
    if (drag.current?.pointer !== event.pointerId) return;
    drag.current = null;
    setActive(null);
  }

  function nudge(corner: Corner, label: string, event: KeyboardEvent<HTMLButtonElement>) {
    const arrow = ARROWS[event.key];
    if (!arrow || event.altKey || event.ctrlKey || event.metaKey) return;
    event.preventDefault();
    const step = Math.max(shown.width, shown.height) * (event.shiftKey ? LEAP : STEP);
    const at = placed[corner];
    const next = moveCorner(placed, corner, { x: at.x + arrow.x * step, y: at.y + arrow.y * step }, shown, leastArea(shown));
    const there = next[corner];
    setQuad(next);
    setNews(
      there.x === at.x && there.y === at.y
        ? `The ${label.toLowerCase()} can go no further that way.`
        : `${label}: ${percent(there.x / shown.width)} from the left, ${percent(there.y / shown.height)} from the top.`,
    );
  }

  async function download() {
    const node = svg.current;
    if (making || !node) return;
    setMaking(true);
    setError(null);
    try {
      save(await makePicture(shown, placed, glass / 100, node), fileName);
      setNews(`Downloading ${fileName}.`);
    } catch {
      setError("The picture could not be made. Try again, or choose a smaller photo.");
    } finally {
      setMaking(false);
    }
  }

  return (
    <div className="win no-print" data-state="placing">
      <div className="win-head">
        <h3 className="win-title">See it in your window</h3>
        <p className="win-lead win-hint" id={`${id}-hint`} ref={hint} tabIndex={-1}>
          Drag the four corners onto the corners of the window. On a keyboard, the arrow keys move a corner; Shift moves
          it further.
        </p>
      </div>
      <div className="win-frame">
        <div className="win-stage" ref={stage} style={cssVars({ "--ratio": shown.width / shown.height })}>
          <img className="win-photo" src={shown.url} alt="Your storefront photo, with the poster on it" draggable={false} />
          <div
            className="win-poster"
            aria-hidden="true"
            style={{ width: POSTER_W, height: POSTER_H, transform: toStage ? toMatrix3d(toStage) : undefined, visibility: toStage ? undefined : "hidden" }}
          >
            {art}
          </div>
          <img className="win-glass" src={shown.url} alt="" draggable={false} style={{ clipPath: clip, opacity: glass / 100 }} />
          {CORNERS.map(({ corner, label }) => (
            <button
              key={corner}
              type="button"
              className="win-handle"
              aria-label={label}
              aria-describedby={`${id}-hint`}
              data-active={active === corner ? "" : undefined}
              style={{ left: `${(placed[corner].x / shown.width) * 100}%`, top: `${(placed[corner].y / shown.height) * 100}%` }}
              onPointerDown={(event) => {
                grab(corner, event);
              }}
              onPointerMove={follow}
              onPointerUp={release}
              onPointerCancel={release}
              onLostPointerCapture={release}
              onKeyDown={(event) => {
                nudge(corner, label, event);
              }}
            />
          ))}
        </div>
      </div>
      <div className="win-tools">
        <div className="win-glass-field">
          <div className="win-glass-head">
            <label htmlFor={`${id}-glass`}>Glass</label>
            <output htmlFor={`${id}-glass`} className="mono">
              {glass}%
            </output>
          </div>
          <input
            id={`${id}-glass`}
            className="win-range"
            type="range"
            min={0}
            max={100}
            step={5}
            value={glass}
            aria-valuetext={`${glass}%`}
            aria-describedby={`${id}-glass-note`}
            onChange={(event) => {
              setGlass(Number(event.currentTarget.value));
            }}
          />
          <p className="win-note" id={`${id}-glass-note`}>
            How much of the window&apos;s reflection shows over the poster.
          </p>
        </div>
        <div className="win-actions">
          <button
            type="button"
            className="ink-button"
            aria-disabled={making}
            aria-busy={making}
            onClick={() => {
              // Not disabled while it works: a disabled button drops the keyboard's focus.
              void download();
            }}
          >
            {making ? "Making the picture…" : "Download picture"}
          </button>
          <button
            type="button"
            className="ghost mono"
            onClick={() => {
              setQuad(startQuad(shown.width, shown.height, POSTER_W / POSTER_H));
              setGlass(GLASS_START);
              setNews("The poster is back in the middle of the photo.");
            }}
          >
            Reset
          </button>
          <button type="button" className="ghost mono" aria-busy={opening} onClick={pick}>
            {opening ? "Opening…" : "Choose another photo"}
          </button>
          <button type="button" className="ghost mono" onClick={remove}>
            Remove photo
          </button>
          {picker}
        </div>
        <p className="win-note">The photo stays on this device: it is not uploaded or saved.</p>
        <p className="win-error" role="alert">
          {error ?? ""}
        </p>
      </div>
      {status}
    </div>
  );
}
