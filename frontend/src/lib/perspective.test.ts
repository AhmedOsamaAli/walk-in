import { describe, expect, it } from "vitest";
import {
  centroid,
  homography,
  isConvex,
  mapPoint,
  moveCorner,
  pixelBox,
  quadArea,
  rectQuad,
  startQuad,
  toMatrix3d,
  warpInto,
  type Homography,
  type Pixels,
  type Point,
  type Quad,
} from "./perspective";

const POSTER = rectQuad(600, 848);
// A shop window seen from the left: its far edge shorter, its top and bottom running toward a point on the right.
const WINDOW: Quad = [
  { x: 912, y: 610 },
  { x: 2050, y: 702 },
  { x: 2032, y: 1488 },
  { x: 930, y: 1602 },
];

function close(point: Point, expected: Point, digits = 6): void {
  expect(point.x).toBeCloseTo(expected.x, digits);
  expect(point.y).toBeCloseTo(expected.y, digits);
}

/** Where two lines, each through two points, cross. */
function crossing(a: Point, b: Point, c: Point, d: Point): Point {
  const den = (a.x - b.x) * (c.y - d.y) - (a.y - b.y) * (c.x - d.x);
  const s = a.x * b.y - a.y * b.x;
  const t = c.x * d.y - c.y * d.x;
  return { x: (s * (c.x - d.x) - (a.x - b.x) * t) / den, y: (s * (c.y - d.y) - (a.y - b.y) * t) / den };
}

function solid(width: number, height: number, rgba: readonly [number, number, number, number]): Pixels {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let k = 0; k < data.length; k += 4) data.set(rgba, k);
  return { width, height, data };
}

function pixel(image: Pixels, x: number, y: number): number[] {
  const k = (y * image.width + x) * 4;
  return Array.from(image.data.subarray(k, k + 4));
}

describe("the four-point homography", () => {
  it("takes each corner of the poster to the same corner of the window", () => {
    const map = homography(POSTER, WINDOW);
    expect(map).not.toBeNull();
    if (!map) return;
    POSTER.forEach((corner, index) => {
      close(mapPoint(map, corner), WINDOW[index] ?? corner);
    });
  });

  it("is a true perspective: the poster's middle lands where the window's diagonals cross, and edges stay straight", () => {
    const map = homography(POSTER, WINDOW);
    if (!map) throw new Error("no map");
    const [tl, tr, br, bl] = WINDOW;
    close(mapPoint(map, { x: 300, y: 424 }), crossing(tl, br, tr, bl));
    // Not the corners' average, which an affine stretch would give.
    expect(Math.abs(mapPoint(map, { x: 300, y: 424 }).x - centroid(WINDOW).x)).toBeGreaterThan(5);
    // A third of the way along the poster's top edge: on the window's top edge, and past a third of it, the near end
    // of the window (its longer edge) taking more of the poster than the far end.
    const third = mapPoint(map, { x: 200, y: 0 });
    const offLine = Math.abs((third.x - tl.x) * (tr.y - tl.y) - (third.y - tl.y) * (tr.x - tl.x)) / Math.hypot(tr.x - tl.x, tr.y - tl.y);
    expect(offLine).toBeLessThan(1e-6);
    expect((third.x - tl.x) / (tr.x - tl.x)).toBeGreaterThan(1 / 3);
    // Equal steps down the poster shrink toward the window's far, shorter edge.
    const near = mapPoint(map, { x: 0, y: 424 });
    const far = mapPoint(map, { x: 600, y: 424 });
    expect(far.y - tr.y).toBeLessThan(near.y - tl.y);
  });

  it("is the identity onto the same quad, and a stretch and shift between rectangles", () => {
    const same = homography(WINDOW, WINDOW);
    if (!same) throw new Error("no map");
    const identity = [1, 0, 0, 0, 1, 0, 0, 0, 1];
    same.forEach((value, index) => {
      expect(value).toBeCloseTo(identity[index] ?? NaN, 9);
    });
    const stretch = homography(rectQuad(100, 50), rectQuad(300, 200, 40, 10));
    if (!stretch) throw new Error("no map");
    close(mapPoint(stretch, { x: 50, y: 25 }), { x: 190, y: 110 });
    close(mapPoint(stretch, { x: 10, y: 40 }), { x: 70, y: 170 });
    expect(stretch[6]).toBeCloseTo(0, 12);
    expect(stretch[7]).toBeCloseTo(0, 12);
  });

  it("goes back the way it came", () => {
    const there = homography(POSTER, WINDOW);
    const back = homography(WINDOW, POSTER);
    if (!there || !back) throw new Error("no map");
    for (const point of [{ x: 0, y: 0 }, { x: 123.4, y: 567.8 }, { x: 599, y: 1 }, { x: 300, y: 848 }]) {
      close(mapPoint(back, mapPoint(there, point)), point);
    }
  });

  it("keeps w at 1 in the middle of the quad it maps from, and positive across it", () => {
    const map = homography(POSTER, WINDOW);
    if (!map) throw new Error("no map");
    const w = (point: Point) => map[6] * point.x + map[7] * point.y + map[8];
    expect(w({ x: 300, y: 424 })).toBeCloseTo(1, 12);
    for (const point of [...POSTER, { x: 600, y: 0 }, { x: 13, y: 801 }]) expect(w(point)).toBeGreaterThan(0);
  });

  it("finds no map onto or from a quad with three corners on a line", () => {
    const flat: Quad = [
      { x: 0, y: 0 },
      { x: 50, y: 50 },
      { x: 100, y: 100 },
      { x: 0, y: 100 },
    ];
    expect(homography(POSTER, flat)).toBeNull();
    expect(homography(flat, POSTER)).toBeNull();
    const point: Quad = [
      { x: 5, y: 5 },
      { x: 5, y: 5 },
      { x: 5, y: 5 },
      { x: 5, y: 5 },
    ];
    expect(homography(POSTER, point)).toBeNull();
  });
});

describe("the CSS transform", () => {
  it("lists the matrix column by column, w in the fourth row", () => {
    const shift: Homography = [1, 0, 5, 0, 1, 7, 0, 0, 1];
    expect(toMatrix3d(shift)).toBe("matrix3d(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 5, 7, 0, 1)");
    const projective: Homography = [1, 2, 3, 4, 5, 6, 0.5, 0.25, 1];
    expect(toMatrix3d(projective)).toBe("matrix3d(1, 4, 0, 0.5, 2, 5, 0, 0.25, 0, 0, 1, 0, 3, 6, 0, 1)");
  });

  it("writes small perspective terms in plain decimals CSS reads", () => {
    const map = homography(POSTER, WINDOW);
    if (!map) throw new Error("no map");
    const css = toMatrix3d(map);
    expect(css).toMatch(/^matrix3d\((-?\d+(\.\d+)?, ){15}-?\d+(\.\d+)?\)$/);
    expect(css).not.toMatch(/e/);
  });
});

describe("the poster's corners on a photo", () => {
  it("starts upright at the poster's shape in the middle of the photo", () => {
    const landscape = startQuad(3000, 2000, 600 / 848);
    expect(landscape[0].y).toBeCloseTo(500);
    expect(landscape[2].y).toBeCloseTo(1500);
    expect((landscape[1].x - landscape[0].x) / (landscape[3].y - landscape[0].y)).toBeCloseTo(600 / 848);
    close(centroid(landscape), { x: 1500, y: 1000 });
    // A narrow photo holds it to 60% of its width.
    const narrow = startQuad(400, 2000, 600 / 848);
    expect(narrow[1].x - narrow[0].x).toBeCloseTo(240);
    close(centroid(narrow), { x: 200, y: 1000 });
  });

  it("tells a placeable quad from a folded, flat or turned-over one", () => {
    expect(isConvex(POSTER)).toBe(true);
    expect(isConvex(WINDOW)).toBe(true);
    const [tl, tr, br, bl] = WINDOW;
    expect(isConvex([tr, tl, br, bl])).toBe(false);
    expect(isConvex([tl, bl, br, tr])).toBe(false);
    expect(isConvex([tl, { x: (tl.x + br.x) / 2 + 300, y: (tl.y + br.y) / 2 - 300 }, br, bl])).toBe(true);
    expect(isConvex([tl, { x: (tl.x + br.x) / 2 - 100, y: (tl.y + br.y) / 2 + 40 }, br, bl])).toBe(false);
    expect(quadArea(POSTER)).toBe(600 * 848);
    expect(quadArea([tl, bl, br, tr])).toBeLessThan(0);
  });

  it("moves a corner inside the photo, and stops it where the poster would fold", () => {
    const size = { width: 1000, height: 800 };
    const start = rectQuad(200, 300, 400, 250);
    const moved = moveCorner(start, 0, { x: 380, y: 220 }, size);
    close(moved[0], { x: 380, y: 220 });
    expect(moved[1]).toBe(start[1]);
    // Off the photo: held at its edge.
    close(moveCorner(start, 2, { x: 1400, y: 900 }, size)[2], { x: 1000, y: 800 });
    // Dragged across the poster toward the opposite corner: it stops short, the quad still convex.
    const folded = moveCorner(start, 0, { x: 700, y: 650 }, size);
    expect(isConvex(folded)).toBe(true);
    expect(folded[0].x).toBeGreaterThan(400);
    expect(folded[0].x).toBeLessThan(700);
    // Kept above a least size.
    const small = moveCorner(start, 0, { x: 590, y: 540 }, size, 200 * 300 * 0.5);
    expect(quadArea(small)).toBeGreaterThanOrEqual(200 * 300 * 0.5 - 1);
  });

  it("boxes the pixels a quad touches, inside the photo", () => {
    expect(pixelBox(WINDOW, 3000, 2000)).toEqual({ x: 911, y: 609, width: 1140, height: 994 });
    expect(pixelBox(rectQuad(50, 50, -10, 1990), 3000, 2000)).toEqual({ x: 0, y: 1989, width: 41, height: 11 });
  });
});

describe("the warp", () => {
  const RED = [200, 30, 40, 255] as const;
  const BLUE = [10, 20, 160, 255] as const;

  it("paints the source inside the quad, fades its edge over a pixel and leaves the rest alone", () => {
    const target = solid(12, 12, BLUE);
    const source = solid(4, 4, RED);
    // The 4 × 4 source onto the 8 × 8 square at (2, 2) of the picture.
    const toSource = homography(rectQuad(8, 8, 2, 2), rectQuad(4, 4));
    if (!toSource) throw new Error("no map");
    warpInto(target, source, toSource);
    expect(pixel(target, 6, 6)).toEqual([...RED]);
    expect(pixel(target, 3, 8)).toEqual([...RED]);
    expect(pixel(target, 0, 0)).toEqual([...BLUE]);
    expect(pixel(target, 11, 5)).toEqual([...BLUE]);
    // The first pixel inside the edge: its centre is a quarter of a source pixel in, so three quarters red.
    const [r, g, b, a] = pixel(target, 2, 6);
    expect(r).toBeCloseTo(0.75 * RED[0] + 0.25 * BLUE[0], -1);
    expect(g).toBeCloseTo(0.75 * RED[1] + 0.25 * BLUE[1], -1);
    expect(b).toBeCloseTo(0.75 * RED[2] + 0.25 * BLUE[2], -1);
    expect(a).toBe(255);
  });

  it("reads the picture from where the target sits in it", () => {
    const whole = solid(12, 12, BLUE);
    const part = solid(6, 6, BLUE);
    const source = solid(4, 4, RED);
    const toSource = homography(rectQuad(8, 8, 2, 2), rectQuad(4, 4));
    if (!toSource) throw new Error("no map");
    warpInto(whole, source, toSource);
    warpInto(part, source, toSource, 5, 1);
    for (let y = 0; y < 6; y += 1) {
      for (let x = 0; x < 6; x += 1) {
        const there = pixel(whole, x + 5, y + 1);
        // Equal but for rounding: the two walk to the same place in different steps.
        pixel(part, x, y).forEach((value, channel) => {
          expect(Math.abs(value - (there[channel] ?? NaN))).toBeLessThanOrEqual(1);
        });
      }
    }
    // Its last column is the picture's at x = 10, a quarter of a source pixel past the edge: a quarter red.
    const [r, g, b] = pixel(part, 5, 3);
    expect(Math.abs((r ?? 0) - (0.25 * RED[0] + 0.75 * BLUE[0]))).toBeLessThanOrEqual(1);
    expect(Math.abs((g ?? 0) - (0.25 * RED[1] + 0.75 * BLUE[1]))).toBeLessThanOrEqual(1);
    expect(Math.abs((b ?? 0) - (0.25 * RED[2] + 0.75 * BLUE[2]))).toBeLessThanOrEqual(1);
  });

  it("follows the perspective: a pixel takes the color of the source pixel it maps to", () => {
    // A source in two halves, left red and right blue, onto the window in a 3000 × 2000 picture, read near its middle.
    const source = solid(60, 85, RED);
    for (let y = 0; y < 85; y += 1) for (let x = 30; x < 60; x += 1) source.data.set(BLUE, (y * 60 + x) * 4);
    const toSource = homography(WINDOW, rectQuad(60, 85));
    const toPicture = homography(rectQuad(60, 85), WINDOW);
    if (!toSource || !toPicture) throw new Error("no map");
    const box = pixelBox(WINDOW, 3000, 2000);
    const target = solid(box.width, box.height, [0, 0, 0, 255]);
    warpInto(target, source, toSource, box.x, box.y);
    const left = mapPoint(toPicture, { x: 20, y: 40 });
    const right = mapPoint(toPicture, { x: 40, y: 40 });
    expect(pixel(target, Math.floor(left.x) - box.x, Math.floor(left.y) - box.y)).toEqual([...RED]);
    expect(pixel(target, Math.floor(right.x) - box.x, Math.floor(right.y) - box.y)).toEqual([...BLUE]);
    // Outside the window, the picture is untouched.
    expect(pixel(target, 0, box.height - 1)).toEqual([0, 0, 0, 255]);
  });

  it("paints nothing past the window's horizon, where a plain division would draw a sliver of ghost", () => {
    // Its left edge 10 tall and its right 400: its top and bottom meet just left of it, on the horizon x ≈ 202.6.
    const steep: Quad = [
      { x: 210, y: 100 },
      { x: 500, y: 0 },
      { x: 500, y: 400 },
      { x: 210, y: 110 },
    ];
    const toSource = homography(steep, rectQuad(4, 4));
    const toPicture = homography(rectQuad(4, 4), steep);
    if (!toSource || !toPicture) throw new Error("no map");
    const w = (point: Point) => toSource[6] * point.x + toSource[7] * point.y + toSource[8];
    // A pixel past the horizon that maps to within half a pixel of the source's far edge: a warp that only divided
    // would tint it.
    let ghost: Point | null = null;
    for (let y = 0; y < 420 && !ghost; y += 1) {
      for (let x = 0; x < 200 && !ghost; x += 1) {
        const at = mapPoint(toSource, { x: x + 0.5, y: y + 0.5 });
        if (at.x > -0.5 && at.y > -0.5 && at.x < 4.5 && at.y < 4.5) ghost = { x, y };
      }
    }
    expect(ghost).not.toBeNull();
    if (!ghost) return;
    expect(w({ x: ghost.x + 0.5, y: ghost.y + 0.5 })).toBeLessThan(0);
    const target = solid(520, 420, BLUE);
    warpInto(target, solid(4, 4, RED), toSource);
    expect(pixel(target, ghost.x, ghost.y)).toEqual([...BLUE]);
    for (let y = 0; y < 420; y += 1) {
      for (let x = 0; x < 200; x += 3) expect(pixel(target, x, y)).toEqual([...BLUE]);
    }
    const middle = mapPoint(toPicture, { x: 2, y: 2 });
    expect(pixel(target, Math.floor(middle.x), Math.floor(middle.y))).toEqual([...RED]);
  });
});
