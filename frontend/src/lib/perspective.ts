/**
 * Perspective for "See it in your window": the projective map (a homography) that takes the poster's rectangle onto
 * four corners an owner sets on a photo of their storefront, the CSS transform that draws it so on screen, and the
 * pixel warp that paints it into the downloaded picture. Pure functions: no DOM.
 */

export interface Point {
  x: number;
  y: number;
}

/** Four corners, in order: top-left, top-right, bottom-right, bottom-left. */
export type Quad = readonly [Point, Point, Point, Point];

/** A corner of a quad, by its place in that order. */
export type Corner = 0 | 1 | 2 | 3;

/**
 * A projective map as a 3 × 3 matrix, row by row: [a, b, c, d, e, f, g, h, i] takes (x, y) to
 * ((ax + by + c) / w, (dx + ey + f) / w), where w = gx + hy + i.
 */
export type Homography = readonly [number, number, number, number, number, number, number, number, number];

/** Pixels as a canvas holds them (an ImageData fits): RGBA, row by row, four bytes a pixel, colors not premultiplied. */
export interface Pixels {
  readonly width: number;
  readonly height: number;
  readonly data: Uint8ClampedArray;
}

/** The corners of a width × height rectangle whose top-left corner is at (left, top). */
export function rectQuad(width: number, height: number, left = 0, top = 0): Quad {
  return [
    { x: left, y: top },
    { x: left + width, y: top },
    { x: left + width, y: top + height },
    { x: left, y: top + height },
  ];
}

/** Twice the area of the triangle o, a, b: positive when it turns clockwise on screen, where y runs down. */
function cross(o: Point, a: Point, b: Point): number {
  return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
}

/** The quad's area: positive when its corners run clockwise on screen, as top-left, top-right, … do. */
export function quadArea(quad: Quad): number {
  const [a, b, c, d] = quad;
  return (cross(a, b, c) + cross(a, c, d)) / 2;
}

/** The average of the quad's corners: inside it whenever it is convex. */
export function centroid(quad: Quad): Point {
  const [a, b, c, d] = quad;
  return { x: (a.x + b.x + c.x + d.x) / 4, y: (a.y + b.y + c.y + d.y) / 4 };
}

/** Three corners on one line, or two on one spot: no projective map takes a rectangle there. */
function degenerate(quad: Quad): boolean {
  const [a, b, c, d] = quad;
  const xs = [a.x, b.x, c.x, d.x];
  const ys = [a.y, b.y, c.y, d.y];
  const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
  if (!Number.isFinite(span) || span <= 0) return true;
  const floor = span * span * 1e-9;
  return [cross(a, b, c), cross(b, c, d), cross(c, d, a), cross(d, a, b)].some((area) => Math.abs(area) <= floor);
}

/** The map from the unit square onto a quad: (0, 0) to its first corner, (1, 0) to the second, (1, 1), (0, 1). After
 * Heckbert, "Fundamentals of Texture Mapping and Image Warping" (1989), §2.2.3. */
function fromSquare(quad: Quad): Homography {
  const [p0, p1, p2, p3] = quad;
  const sx = p0.x - p1.x + p2.x - p3.x;
  const sy = p0.y - p1.y + p2.y - p3.y;
  const dx1 = p1.x - p2.x;
  const dx2 = p3.x - p2.x;
  const dy1 = p1.y - p2.y;
  const dy2 = p3.y - p2.y;
  const den = dx1 * dy2 - dx2 * dy1;
  const g = (sx * dy2 - dx2 * sy) / den;
  const h = (dx1 * sy - sx * dy1) / den;
  return [p1.x - p0.x + g * p1.x, p3.x - p0.x + h * p3.x, p0.x, p1.y - p0.y + g * p1.y, p3.y - p0.y + h * p3.y, p0.y, g, h, 1];
}

function multiply(m: Homography, n: Homography): Homography {
  const [a, b, c, d, e, f, g, h, i] = m;
  const [j, k, l, o, p, q, r, s, t] = n;
  return [
    a * j + b * o + c * r,
    a * k + b * p + c * s,
    a * l + b * q + c * t,
    d * j + e * o + f * r,
    d * k + e * p + f * s,
    d * l + e * q + f * t,
    g * j + h * o + i * r,
    g * k + h * p + i * s,
    g * l + h * q + i * t,
  ];
}

/** The inverse up to scale, which is all a projective map needs. */
function adjugate(m: Homography): Homography {
  const [a, b, c, d, e, f, g, h, i] = m;
  return [e * i - f * h, c * h - b * i, b * f - c * e, f * g - d * i, a * i - c * g, c * d - a * f, d * h - e * g, b * g - a * h, a * e - b * d];
}

/**
 * The homography that takes each corner of `from` to the same corner of `to`, or null when either quad is degenerate.
 * It is scaled so that w is 1 in the middle of `from`, so w stays positive across a convex `from`: the side of the map's
 * horizon a CSS transform draws, and the side the warp paints.
 */
export function homography(from: Quad, to: Quad): Homography | null {
  if (degenerate(from) || degenerate(to)) return null;
  const m = multiply(fromSquare(to), adjugate(fromSquare(from)));
  const middle = centroid(from);
  const w = m[6] * middle.x + m[7] * middle.y + m[8];
  if (!Number.isFinite(w) || w === 0) return null;
  const [a, b, c, d, e, f, g, h, i] = m;
  return [a / w, b / w, c / w, d / w, e / w, f / w, g / w, h / w, i / w];
}

/** Where the map takes a point. */
export function mapPoint(m: Homography, point: Point): Point {
  const w = m[6] * point.x + m[7] * point.y + m[8];
  return { x: (m[0] * point.x + m[1] * point.y + m[2]) / w, y: (m[3] * point.x + m[4] * point.y + m[5]) / w };
}

/** A number as CSS reads it, to 12 places and without a trailing zero. */
function cssNumber(value: number): string {
  const text = value.toFixed(12).replace(/\.?0+$/, "");
  return text === "-0" ? "0" : text;
}

/**
 * The CSS transform that draws an element's box through the map, from the box's own top-left corner: set it with
 * `transform-origin: 0 0`. matrix3d lists the 4 × 4 matrix column by column, the map's w in its fourth row.
 */
export function toMatrix3d(m: Homography): string {
  const [a, b, c, d, e, f, g, h, i] = m;
  return `matrix3d(${[a, d, 0, g, b, e, 0, h, 0, 0, 1, 0, c, f, 0, i].map(cssNumber).join(", ")})`;
}

/** The sine of the turn at `at`, on the way from `before` to `after`: 1 for a right angle, near 0 for nearly straight. */
function turn(before: Point, at: Point, after: Point): number {
  const lengths = Math.hypot(at.x - before.x, at.y - before.y) * Math.hypot(after.x - at.x, after.y - at.y);
  return lengths > 0 ? ((at.x - before.x) * (after.y - at.y) - (at.y - before.y) * (after.x - at.x)) / lengths : 0;
}

/** Every corner keeps an angle between 4° and 176°. */
const MIN_TURN = Math.sin((4 * Math.PI) / 180);

/**
 * True when the quad is convex and runs clockwise on screen as the poster's corners do: no corner folded past another,
 * none nearly flat, and the poster not turned over.
 */
export function isConvex(quad: Quad): boolean {
  const [a, b, c, d] = quad;
  return [turn(d, a, b), turn(a, b, c), turn(b, c, d), turn(c, d, a)].every((sine) => sine > MIN_TURN);
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

function withCorner(quad: Quad, corner: Corner, point: Point): Quad {
  const [a, b, c, d] = quad;
  return [corner === 0 ? point : a, corner === 1 ? point : b, corner === 2 ? point : c, corner === 3 ? point : d];
}

/**
 * The quad with one corner moved toward `to`, kept inside a width × height photo. The corner goes only as far as the
 * quad stays convex and at least `minArea` in size: pushed past that, it stops at the last place it fitted.
 */
export function moveCorner(quad: Quad, corner: Corner, to: Point, size: { width: number; height: number }, minArea = 0): Quad {
  const target = { x: clamp(to.x, 0, size.width), y: clamp(to.y, 0, size.height) };
  const fits = (point: Point) => {
    const next = withCorner(quad, corner, point);
    return isConvex(next) && quadArea(next) >= minArea;
  };
  if (fits(target)) return withCorner(quad, corner, target);
  const from = quad[corner];
  const along = (t: number): Point => ({ x: from.x + (target.x - from.x) * t, y: from.y + (target.y - from.y) * t });
  let low = 0;
  let high = 1;
  for (let step = 0; step < 14; step += 1) {
    const middle = (low + high) / 2;
    if (fits(along(middle))) low = middle;
    else high = middle;
  }
  return low > 0 ? withCorner(quad, corner, along(low)) : quad;
}

/** Where the poster starts on a photo: upright, at its own shape (width / height = aspect), half the photo's height or
 * at most 60% of its width, in the middle. */
export function startQuad(width: number, height: number, aspect: number): Quad {
  let tall = height * 0.5;
  let wide = tall * aspect;
  if (wide > width * 0.6) {
    wide = width * 0.6;
    tall = wide / aspect;
  }
  return rectQuad(wide, tall, (width - wide) / 2, (height - tall) / 2);
}

/** The whole pixels a quad touches, with one to spare all round for its soft edge, inside a width × height picture. */
export function pixelBox(quad: Quad, width: number, height: number): { x: number; y: number; width: number; height: number } {
  const xs = quad.map((point) => point.x);
  const ys = quad.map((point) => point.y);
  const left = clamp(Math.floor(Math.min(...xs)) - 1, 0, width);
  const top = clamp(Math.floor(Math.min(...ys)) - 1, 0, height);
  const right = clamp(Math.ceil(Math.max(...xs)) + 1, 0, width);
  const bottom = clamp(Math.ceil(Math.max(...ys)) + 1, 0, height);
  return { x: left, y: top, width: right - left, height: bottom - top };
}

/**
 * Paints `source` over `target` through `toSource`, the map from a point of the picture to the matching point of the
 * source; `left` and `top` say where the target sits in the picture, so only the part a quad covers need be read.
 * Each pixel blends the four source pixels around its mapped centre, and the source's edge fades out across one pixel
 * instead of stepping. Pixels past the map's horizon (w ≤ 0) are left as they are.
 */
export function warpInto(target: Pixels, source: Pixels, toSource: Homography, left = 0, top = 0): void {
  const [a, b, c, d, e, f, g, h, i] = toSource;
  // The source inside a clear border one pixel wide: the four pixels a sample reads are then always there to read.
  const wide = source.width + 2;
  const tall = source.height + 2;
  const padded = new Uint8ClampedArray(wide * tall * 4);
  for (let row = 0; row < source.height; row += 1) {
    padded.set(source.data.subarray(row * source.width * 4, (row + 1) * source.width * 4), ((row + 1) * wide + 1) * 4);
  }
  const out = target.data;
  const across = wide * 4;
  for (let row = 0; row < target.height; row += 1) {
    const y = top + row + 0.5;
    const x = left + 0.5;
    let nu = a * x + b * y + c;
    let nv = d * x + e * y + f;
    let w = g * x + h * y + i;
    for (let col = 0; col < target.width; col += 1) {
      if (w > 0) {
        // The sample's place among the padded source's pixel centres.
        const u = nu / w + 0.5;
        const v = nv / w + 0.5;
        if (u > 0 && v > 0 && u < wide - 1 && v < tall - 1) {
          const u0 = Math.floor(u);
          const v0 = Math.floor(v);
          const fu = u - u0;
          const fv = v - v0;
          const k00 = (v0 * wide + u0) * 4;
          const k10 = k00 + 4;
          const k01 = k00 + across;
          const k11 = k01 + 4;
          // Each pixel's weight times its alpha, so colors blend premultiplied and the clear border adds no dark fringe.
          const w00 = (1 - fu) * (1 - fv) * (padded[k00 + 3] ?? 0);
          const w10 = fu * (1 - fv) * (padded[k10 + 3] ?? 0);
          const w01 = (1 - fu) * fv * (padded[k01 + 3] ?? 0);
          const w11 = fu * fv * (padded[k11 + 3] ?? 0);
          const alpha = w00 + w10 + w01 + w11;
          if (alpha > 0) {
            const keep = 1 - alpha / 255;
            const o = (row * target.width + col) * 4;
            for (let channel = 0; channel < 3; channel += 1) {
              const color =
                (padded[k00 + channel] ?? 0) * w00 +
                (padded[k10 + channel] ?? 0) * w10 +
                (padded[k01 + channel] ?? 0) * w01 +
                (padded[k11 + channel] ?? 0) * w11;
              out[o + channel] = color / 255 + (out[o + channel] ?? 0) * keep;
            }
            out[o + 3] = alpha + (out[o + 3] ?? 0) * keep;
          }
        }
      }
      nu += a;
      nv += d;
      w += g;
    }
  }
}
