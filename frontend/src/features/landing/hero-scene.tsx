"use client";

import type { CSSProperties } from "react";
import { motion, useReducedMotion } from "framer-motion";

/**
 * The hero image: a forested valley at golden hour, full-bleed behind the whole
 * top of the page — nav included — with the headline set over it in light type.
 *
 * **Drawn, not photographed.** A stock hero would be someone else's licence,
 * several hundred kilobytes, soft on a retina display, and impossible to tune
 * once the palette moved. This is vector: sharp at any width, and it costs no
 * request at all because it is already in the HTML.
 *
 * **The detail is generated, not drawn.** Around nine hundred elements make up
 * the treelines, the ground cover, the water and the air — well past what anyone
 * would place by hand, and placing two hundred trees by hand is exactly how a
 * drawn landscape ends up with the even spacing that gives it away. A seeded
 * PRNG scatters them over curves that describe where the ground is, with size,
 * hue and opacity all keyed to depth. `mulberry32` rather than `Math.random`,
 * and every array is built once at module scope: the sequence has to be
 * identical on the server and on the client, or every tree moves on hydration
 * and React tears the whole tree down.
 *
 * **Green, and lit from one side.** The sun sits right of centre and low, so the
 * left bank is in full light and reads yellow-green, while the right bank is
 * backlit and falls to a cold blue-green. Both banks in the same green is the
 * single most common reason a drawn forest looks like a pattern rather than a
 * place. Distance is drawn with *contrast*, not with size — each ridge sits
 * closer to the sky's own value than the one in front of it, and mist banks lie
 * in the gaps between them, which is the other half of what makes a treeline two
 * miles away look two miles away.
 *
 * **It is painted with noise.** A landscape built from clean bézier curves reads
 * as a chart no matter how carefully the curves are placed — the giveaway is the
 * edge, which is mathematically smooth where a real one is broken.
 * `feTurbulence` driving an `feDisplacementMap` pushes every edge by a few units
 * of fractal noise, so ridgelines come out ragged and clustered ellipses fuse
 * into undergrowth. One filter over a whole group of several hundred shapes,
 * never one filter each: the group form is a single rasterisation and the
 * per-shape form is several hundred.
 *
 * **The wind is composed.** See `globals.css` — every band of foliage is a slow
 * `gust` group wrapping a faster `sway` group, so the transforms multiply into
 * something that arrives in waves instead of ticking like a metronome, and each
 * element carries its own duration and a negative delay so nothing starts in
 * phase. The animations are CSS rather than Framer Motion because ninety
 * simultaneous motion values would be ninety main-thread subscriptions; these
 * are compositor transforms with no per-frame JavaScript at all. Framer Motion
 * is kept for the handful of things that genuinely need it.
 *
 * **The viewBox is the hero's own aspect, not a round number.** With `slice` the
 * difference between the two is thrown away: drawn 16:10 into a section nearer
 * 8:7, this lost 320px off each side and took both valley walls with it.
 * Everything load-bearing also sits above `y≈900` or outside the middle 900
 * units, because the product panel is centred over the rest.
 *
 * **The palette is the artwork's own and does not follow the theme.** Every
 * other colour in the product resolves to a token so it can flip; this is the
 * one deliberate exception, because a picture whose colours invert is a
 * different picture and the type over it would have to work against both. The
 * scene is a fixed golden hour in either theme, the type on it uses the `on-art`
 * pair, and only the final resolve at the bottom is a token — so the picture
 * always lands exactly on the page colour beneath it.
 *
 * All of the motion stops for `prefers-reduced-motion`: the ambient layers are
 * not rendered at all rather than animated to a standstill.
 */

/* ------------------------------------------------------------------ *
 * Deterministic scatter
 * ------------------------------------------------------------------ */

/** mulberry32. Small, fast, and — the only property that matters here — the
 *  same sequence from the same seed in every runtime, so the server's HTML and
 *  the client's first render agree. */
function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** The height of a ridge at a given x, by interpolating its sample points.
 *  Linear is enough: everything sits *below* the line by a random depth, so a
 *  few units of error at the joins is invisible under the foliage. */
function ridge(points: readonly (readonly [number, number])[]) {
  return (x: number) => {
    if (x <= points[0][0]) return points[0][1];
    for (let i = 1; i < points.length; i++) {
      const [x0, y0] = points[i - 1];
      const [x1, y1] = points[i];
      if (x <= x1) return y0 + ((y1 - y0) * (x - x0)) / (x1 - x0);
    }
    return points[points.length - 1][1];
  };
}

/** Custom properties are not in `CSSProperties`, and the alternative to this
 *  cast is a `--hs-*` entry in a global type augmentation for six values used
 *  in one file. */
const css = (v: Record<string, string | number>) => v as CSSProperties;

/* ------------------------------------------------------------------ *
 * The terrain
 * ------------------------------------------------------------------ */

const RANGE_FAR = ridge([
  [-40, 590], [200, 540], [420, 566], [640, 528], [900, 558], [1140, 522], [1480, 552],
]);
const RANGE_NEAR = ridge([
  [-40, 654], [180, 616], [400, 646], [620, 626], [880, 650], [1160, 620], [1480, 646],
]);
const MID_L = ridge([
  [-60, 706], [120, 658], [300, 676], [440, 690], [560, 726], [660, 764],
]);
const MID_R = ridge([
  [780, 768], [900, 710], [1040, 680], [1200, 684], [1360, 666], [1500, 694],
]);
const FORE_L = ridge([
  [-80, 930], [100, 878], [280, 890], [400, 930], [520, 1004],
]);
const FORE_R = ridge([
  [860, 1024], [1000, 930], [1160, 888], [1340, 874], [1520, 910],
]);

/** The river's banks as functions of *depth*, so anything drawn on the water can
 *  be placed between them without re-deriving the path. */
const BANK_L = ridge([[648, 712], [760, 690], [860, 632], [1000, 530], [1240, 424]]);
const BANK_R = ridge([[648, 728], [760, 800], [860, 812], [1000, 780], [1240, 742]]);

const RIVER =
  "M712 648 C 700 720, 684 786, 632 858 C 578 932, 470 1020, 424 1240 L 742 1240 C 760 1060, 800 940, 812 856 C 826 764, 754 700, 728 648 Z";

/* ------------------------------------------------------------------ *
 * Palettes — one sunlit, one in shade, at two depths
 * ------------------------------------------------------------------ */

const LIT_MID = [
  "oklch(0.688 0.116 124)", "oklch(0.632 0.108 132)", "oklch(0.742 0.118 116)",
  "oklch(0.582 0.098 140)", "oklch(0.706 0.104 106)",
] as const;

const SHADE_MID = [
  "oklch(0.522 0.070 168)", "oklch(0.468 0.064 176)", "oklch(0.578 0.076 158)",
  "oklch(0.432 0.056 184)", "oklch(0.548 0.082 150)",
] as const;

const LIT_FORE = [
  "oklch(0.462 0.086 132)", "oklch(0.398 0.076 142)", "oklch(0.524 0.094 122)",
  "oklch(0.346 0.062 150)", "oklch(0.436 0.090 112)",
] as const;

const SHADE_FORE = [
  "oklch(0.372 0.058 170)", "oklch(0.316 0.050 178)", "oklch(0.424 0.066 160)",
  "oklch(0.272 0.040 184)", "oklch(0.352 0.062 152)",
] as const;

/* ------------------------------------------------------------------ *
 * Undergrowth
 * ------------------------------------------------------------------ */

type Blob = { x: number; y: number; rx: number; ry: number; fill: string; o: number };

/**
 * A field of undergrowth on one bank.
 *
 * `depth` is what makes it read as a slope rather than a hedge: size and opacity
 * are driven by how far down the band a clump landed, so one call produces small
 * pale scrub at the ridgeline and large saturated bushes at the viewer's feet.
 * The depth is squared, so clumps bunch toward the ridge and thin out downhill —
 * uniform depth gives an evenly grey field with no horizon to it.
 */
function scatter(opts: {
  seed: number; from: number; to: number; top: (x: number) => number;
  depth: number; count: number; minScale: number; maxScale: number;
  palette: readonly string[];
  /** Where nothing may grow — the pond. Rejection sampling rather than a
   *  post-filter, so clearing a hole does not also thin out the field. */
  avoid?: (x: number, y: number) => boolean;
}): Blob[] {
  const r = rng(opts.seed);
  const out: Blob[] = [];
  let guard = 0;
  while (out.length < opts.count && guard < opts.count * 12) {
    guard++;
    const x = opts.from + r() * (opts.to - opts.from);
    const t = r() ** 2;
    const y = opts.top(x) + 12 + t * opts.depth;
    if (opts.avoid?.(x, y)) continue;
    const s = opts.minScale + t * (opts.maxScale - opts.minScale) * (0.6 + r() * 0.7);
    out.push({
      x,
      y,
      rx: 16 * s * (0.7 + r() * 0.65),
      ry: 11 * s * (0.65 + r() * 0.7),
      fill: opts.palette[Math.floor(r() * opts.palette.length)],
      o: 0.55 + t * 0.38 + r() * 0.1,
    });
  }
  return out.sort((a, b) => a.y - b.y);
}

/* ------------------------------------------------------------------ *
 * The pond
 * ------------------------------------------------------------------ */

/**
 * A tarn on the valley floor, left of the stream and above the fold.
 *
 * Flattened hard — `ry` is a quarter of `rx` — because a pond seen from a
 * standing height is an ellipse, and the circle everyone draws instead is the
 * single thing that makes a landscape read as a map. Everything on it inherits
 * that same ratio: the ripple rings are ellipses of the same flattening, which
 * is what puts them *on* the surface rather than hovering over it.
 */
const POND = { cx: 286, cy: 806, rx: 188, ry: 48 };

/** The margin is generous: undergrowth whose centre clears the water but whose
 *  body does not still ends up as a bush growing out of the pond. */
const inPond = (x: number, y: number) =>
  ((x - POND.cx) / (POND.rx + 30)) ** 2 + ((y - POND.cy) / (POND.ry + 22)) ** 2 <= 1;

/** Ripple origins. Each emits a train of rings on staggered delays, so the
 *  water is never briefly still the way one ring per origin would leave it. */
const POND_RINGS = (() => {
  const r = rng(4001);
  const flat = POND.ry / POND.rx;
  const out: {
    ox: number; oy: number; rx: number; ry: number;
    dur: number; delay: number; o: number;
  }[] = [];
  for (let i = 0; i < 5; i++) {
    const ox = POND.cx + (r() - 0.5) * POND.rx * 1.25;
    const oy = POND.cy + (r() - 0.5) * POND.ry * 1.1;
    const max = 26 + r() * 44;
    const dur = 4.4 + r() * 3.6;
    for (let k = 0; k < 3; k++) {
      out.push({
        ox, oy, rx: max, ry: max * flat, dur,
        delay: -((k * dur) / 3) - r() * 1.5,
        o: 0.52 - k * 0.09,
      });
    }
  }
  return out;
})();

const LILIES = (() => {
  const r = rng(4409);
  return Array.from({ length: 9 }, () => {
    // Kept inside the ellipse by construction rather than by rejection: an
    // angle and a radius under one, mapped through the pond's own radii.
    const a = r() * Math.PI * 2;
    const d = 0.35 + r() * 0.55;
    return {
      cx: POND.cx + Math.cos(a) * POND.rx * d,
      cy: POND.cy + Math.sin(a) * POND.ry * d,
      rx: 7 + r() * 7,
      o: 0.5 + r() * 0.35,
    };
  });
})();

const COVER_MID_L = scatter({
  seed: 1301, from: -60, to: 640, top: MID_L, depth: 210,
  count: 104, minScale: 0.32, maxScale: 1.0, palette: LIT_MID,
  avoid: inPond,
});
const COVER_MID_R = scatter({
  seed: 2207, from: 800, to: 1500, top: MID_R, depth: 210,
  count: 104, minScale: 0.32, maxScale: 1.0, palette: SHADE_MID,
});
const COVER_FORE_L = scatter({
  seed: 5501, from: -70, to: 520, top: FORE_L, depth: 330,
  count: 112, minScale: 0.8, maxScale: 2.0, palette: LIT_FORE,
});
const COVER_FORE_R = scatter({
  seed: 6607, from: 860, to: 1510, top: FORE_R, depth: 330,
  count: 112, minScale: 0.8, maxScale: 2.0, palette: SHADE_FORE,
});

/* ------------------------------------------------------------------ *
 * Treelines
 * ------------------------------------------------------------------ */

type Conifer = { d: string; fill: string; o: number; y: number };

/**
 * A stand of conifers along a ridge.
 *
 * Two stacked triangles rather than one: a wider skirt with a narrower crown
 * above it is the silhouette that separates a spruce from a road sign, and it
 * survives being shrunk to twelve units on the far ridge. The whole stand takes
 * one displacement filter, which frays every outline at once.
 */
function treeline(opts: {
  seed: number; from: number; to: number; top: (x: number) => number;
  count: number; hMin: number; hMax: number; palette: readonly string[];
  sink?: number;
}): Conifer[] {
  const r = rng(opts.seed);
  const out: Conifer[] = [];
  for (let i = 0; i < opts.count; i++) {
    const x = opts.from + r() * (opts.to - opts.from);
    const h = opts.hMin + r() * (opts.hMax - opts.hMin);
    const w = h * (0.24 + r() * 0.14);
    // Rooted a little below the ridgeline, so the stand reads as growing out of
    // the slope rather than balanced on top of it.
    const y = opts.top(x) + (opts.sink ?? 8) + r() * 22;
    out.push({
      y,
      d:
        `M${(x - w).toFixed(1)} ${y.toFixed(1)} L${x.toFixed(1)} ${(y - h * 0.72).toFixed(1)} L${(x + w).toFixed(1)} ${y.toFixed(1)} Z` +
        `M${(x - w * 0.7).toFixed(1)} ${(y - h * 0.4).toFixed(1)} L${x.toFixed(1)} ${(y - h * 1.04).toFixed(1)} L${(x + w * 0.7).toFixed(1)} ${(y - h * 0.4).toFixed(1)} Z`,
      fill: opts.palette[Math.floor(r() * opts.palette.length)],
      o: 0.62 + r() * 0.34,
    });
  }
  return out.sort((a, b) => a.y - b.y);
}

const STAND_FAR = treeline({
  seed: 401, from: -40, to: 1480, top: RANGE_FAR, count: 150,
  hMin: 8, hMax: 22, sink: 2,
  palette: ["oklch(0.688 0.026 226)", "oklch(0.652 0.030 218)", "oklch(0.716 0.024 232)"],
});

const STAND_NEAR = treeline({
  seed: 907, from: -40, to: 1480, top: RANGE_NEAR, count: 150,
  hMin: 14, hMax: 40, sink: 4,
  palette: ["oklch(0.552 0.044 196)", "oklch(0.502 0.048 186)", "oklch(0.596 0.042 204)"],
});

const STAND_MID_L = treeline({
  seed: 1601, from: -50, to: 660, top: MID_L, count: 78, hMin: 26, hMax: 84,
  palette: [
    "oklch(0.482 0.086 142)", "oklch(0.422 0.076 150)",
    "oklch(0.566 0.098 128)", "oklch(0.618 0.104 118)",
  ],
});

const STAND_MID_R = treeline({
  seed: 1709, from: 780, to: 1500, top: MID_R, count: 78, hMin: 26, hMax: 84,
  palette: [
    "oklch(0.392 0.058 174)", "oklch(0.342 0.050 182)",
    "oklch(0.446 0.066 164)", "oklch(0.302 0.042 188)",
  ],
});

/* ------------------------------------------------------------------ *
 * The near trees
 * ------------------------------------------------------------------ */

type Broadleaf = { x: number; y: number; s: number; trunk: string; canopy: Blob[]; dur: number; delay: number };

/**
 * A broadleaf is a trunk and a cloud of canopy blobs — never one ellipse, which
 * is the shape everyone recognises as a clip-art tree. The blobs are biased
 * upward and outward from the crown so the silhouette comes out lopsided, and
 * each tree carries its own sway period so no two move together.
 */
function broadleaves(
  seed: number,
  spots: readonly (readonly [number, number, number])[],
  palette: readonly string[]
): Broadleaf[] {
  const r = rng(seed);
  return spots.map(([x, y, s]) => {
    const canopy: Blob[] = [];
    const n = 12 + Math.floor(r() * 8);
    for (let i = 0; i < n; i++) {
      const a = r() * Math.PI * 2;
      const d = r() ** 0.7;
      canopy.push({
        x: x + Math.cos(a) * 38 * s * d,
        y: y - 78 * s + Math.sin(a) * 30 * s * d,
        rx: (20 + r() * 17) * s,
        ry: (16 + r() * 14) * s,
        fill: palette[Math.floor(r() * palette.length)],
        o: 0.74 + r() * 0.24,
      });
    }
    const w = 5 * s;
    return {
      x, y, s,
      trunk: `M${x - w} ${y} L${x - w * 0.5} ${y - 76 * s} L${x + w * 0.5} ${y - 76 * s} L${x + w} ${y} Z`,
      canopy,
      dur: 4.6 + r() * 3.4,
      delay: -r() * 8,
    };
  });
}

const NEAR_TREES_L = broadleaves(
  4113,
  [[128, 942, 1.25], [34, 980, 1.05], [246, 906, 0.8], [340, 890, 0.6]],
  ["oklch(0.508 0.096 130)", "oklch(0.442 0.084 140)", "oklch(0.586 0.104 118)", "oklch(0.372 0.066 148)"]
);

const NEAR_TREES_R = broadleaves(
  9001,
  [[1288, 946, 1.3], [1382, 982, 1.05], [1176, 906, 0.86], [1444, 930, 0.7], [1092, 884, 0.6]],
  ["oklch(0.396 0.062 172)", "oklch(0.336 0.054 180)", "oklch(0.452 0.070 162)", "oklch(0.286 0.042 186)"]
);

/* ------------------------------------------------------------------ *
 * Air and water
 * ------------------------------------------------------------------ */

type Ripple = { cx: number; cy: number; rx: number; o: number };

/** Ripples. Horizontal, because still water only ever breaks that way, and
 *  widest mid-channel so the surface reads as curved rather than flat. */
const RIPPLES: Ripple[] = (() => {
  const r = rng(7717);
  const out: Ripple[] = [];
  for (let y = 668; y < 1240; y += 13 + r() * 12) {
    const mid = (BANK_L(y) + BANK_R(y)) / 2;
    const half = (BANK_R(y) - BANK_L(y)) / 2;
    const n = 1 + Math.floor(r() * 3);
    for (let i = 0; i < n; i++) {
      out.push({
        cx: mid + (r() - 0.5) * half * 1.3,
        cy: y,
        rx: half * (0.12 + r() * 0.5),
        o: 0.1 + r() * 0.3,
      });
    }
  }
  return out;
})();

/** Glints: the same shape as a ripple but breathing on opacity alone. A glint
 *  that moves is a boat. */
const GLINTS = (() => {
  const r = rng(8823);
  return Array.from({ length: 16 }, () => {
    const y = 668 + r() * 520;
    const mid = (BANK_L(y) + BANK_R(y)) / 2;
    const half = (BANK_R(y) - BANK_L(y)) / 2;
    return {
      cx: mid + (r() - 0.5) * half * 1.1,
      cy: y,
      rx: half * (0.08 + r() * 0.26),
      dur: 4 + r() * 7,
      delay: -r() * 10,
      o2: 0.34 + r() * 0.4,
    };
  });
})();

/** Pollen and insects over the water at dusk. */
const MOTES = (() => {
  const r = rng(5309);
  return Array.from({ length: 34 }, () => ({
    cx: 120 + r() * 1200,
    cy: 740 + r() * 420,
    rad: 1 + r() * 2.4,
    dx: (r() - 0.5) * 90,
    dy: -110 - r() * 190,
    dur: 13 + r() * 16,
    delay: -r() * 26,
    o: 0.32 + r() * 0.5,
  }));
})();

/** A few leaves, tumbling. Ten is the number: enough to notice, few enough that
 *  nobody starts counting. */
const LEAVES = (() => {
  const r = rng(6151);
  return Array.from({ length: 11 }, () => ({
    cx: 60 + r() * 1320,
    cy: 700 + r() * 200,
    rx: 4 + r() * 3.5,
    ry: 2.2 + r() * 1.8,
    dx: (r() - 0.5) * 190,
    dy: 240 + r() * 260,
    dur: 15 + r() * 14,
    delay: -r() * 28,
    fill: r() > 0.5 ? "oklch(0.66 0.106 96)" : "oklch(0.552 0.092 128)",
  }));
})();

const STARS = (() => {
  const r = rng(313);
  return Array.from({ length: 22 }, () => ({
    cx: r() * 1440,
    cy: 16 + r() * 260,
    rad: 0.7 + r() * 1.4,
    o: 0.16 + r() * 0.44,
  }));
})();

/** A flock, two arcs each — the least that still reads as a bird at this size,
 *  and anything more becomes a smudge. */
const BIRDS = [
  [372, 262, 1.0], [408, 244, 0.82], [440, 272, 0.9],
  [342, 296, 0.7], [472, 240, 0.62], [508, 284, 0.55], [278, 282, 0.5],
] as const;

/** Mist banks, lying in the gaps between the ridges. */
const MIST = [
  { y: 598, h: 36, o1: 0.26, o2: 0.44, dx: 90, dur: 64, delay: 0 },
  { y: 648, h: 42, o1: 0.2, o2: 0.38, dx: -110, dur: 82, delay: -14 },
  { y: 708, h: 46, o1: 0.15, o2: 0.3, dx: 70, dur: 96, delay: -30 },
  { y: 778, h: 40, o1: 0.1, o2: 0.22, dx: -80, dur: 74, delay: -46 },
];

/**
 * Where the sun is. Everything that claims to be lit by it — the rays, the
 * glow, the column on the water — reads this rather than repeating a literal.
 *
 * The position took two corrections worth recording. At `y=596` the disc sat
 * *behind* the far ridge, so the rays had no visible source and the sky read as
 * evenly lit from nowhere. Lifted clear of the ridge it then landed squarely
 * behind the word "shipping": the headline is centred in a 56rem column, so the
 * only part of the sky that is reliably clear of type is outside `x≈1200`.
 */
const SUN = { x: 1296, y: 424 };

/**
 * God rays, fanning *down* from the sun into the valley.
 *
 * Down, not up: crepuscular rays are shafts picked out by haze between a high
 * sun and the ground, and a fan pointing up from a low sun is a different
 * effect — a sunset starburst — which is what this drew first. Each wedge has
 * its apex at the sun, so the gradient (opaque at the top of the bounding box,
 * transparent at the bottom) fades them out before they reach the treeline
 * without needing to be clipped there.
 *
 * The widths are deliberately uneven. A fan of identical wedges at even angles
 * is a starburst; real shafts are gaps in something and come in irregular.
 */
const SHAFTS = [11, 19, 27, 36, 44, 52, 60, 68].map((deg, i) => ({
  deg,
  w: 10 + ((i * 29) % 26),
  o: 0.34 + ((i * 17) % 9) / 26,
  dur: 9 + i * 1.7,
  delay: -i * 2.4,
}));

export function HeroScene({ className }: { className?: string }) {
  const still = useReducedMotion();

  /** Wind on a band of foliage: a slow gust wrapping a faster sway. Returns the
   *  outer group's props; the caller nests the inner one. */
  const gust = (dur: number, delay: number, amp: number, shift: number) =>
    still
      ? {}
      : {
          className: "hs-gust",
          style: css({
            "--hs-dur": `${dur}s`,
            "--hs-delay": `${delay}s`,
            "--hs-amp": `${amp}deg`,
            "--hs-shift": `${shift}px`,
          }),
        };

  const sway = (dur: number, delay: number, amp: number) =>
    still
      ? {}
      : {
          className: "hs-sway",
          style: css({
            "--hs-dur": `${dur}s`,
            "--hs-delay": `${delay}s`,
            "--hs-amp": `${amp}deg`,
          }),
        };

  return (
    <div
      // `z-0` with the content at `z-10`, never a negative z-index: a child at
      // `-z-10` paints behind its parent's own background under CSS painting
      // order, and an opaque ancestor then covers the whole scene.
      className={`grain pointer-events-none absolute inset-0 z-0 overflow-hidden ${className ?? ""}`}
      aria-hidden
    >
      <svg
        viewBox="0 0 1440 1240"
        // `slice` on a bottom anchor: a window taller than the drawing crops the
        // sky rather than the ground, so the horizon stays where the composition
        // puts it instead of sliding up behind the headline.
        preserveAspectRatio="xMidYMax slice"
        className="size-full"
      >
        <defs>
          {/* ── Sky ──────────────────────────────────────────────────────
              Six stops. Golden hour is deep blue overhead and gold at the
              horizon, and the whole interest is the crossover in between — a
              two-stop gradient runs straight through it and comes out teal. */}
          <linearGradient id="s-sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="oklch(0.372 0.068 262)" />
            <stop offset="14%" stopColor="oklch(0.462 0.062 256)" />
            <stop offset="27%" stopColor="oklch(0.578 0.052 248)" />
            <stop offset="38%" stopColor="oklch(0.706 0.042 232)" />
            <stop offset="45%" stopColor="oklch(0.818 0.048 128)" />
            <stop offset="49%" stopColor="oklch(0.892 0.070 96)" />
            <stop offset="53%" stopColor="oklch(0.930 0.082 88)" />
          </linearGradient>

          <radialGradient id="s-sun" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="oklch(0.985 0.062 92)" stopOpacity="0.96" />
            <stop offset="32%" stopColor="oklch(0.938 0.088 86)" stopOpacity="0.44" />
            <stop offset="100%" stopColor="oklch(0.912 0.094 82)" stopOpacity="0" />
          </radialGradient>

          {/* Held bright well past halfway before it falls away. A straight
              linear fade puts most of a ray's length below a third of its
              starting opacity, which is where the blur finishes it off — the
              first version's rays were mathematically present and invisible. */}
          <linearGradient id="s-shaft" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="oklch(0.99 0.048 92)" stopOpacity="0.9" />
            <stop offset="42%" stopColor="oklch(0.98 0.052 90)" stopOpacity="0.72" />
            <stop offset="78%" stopColor="oklch(0.97 0.056 88)" stopOpacity="0.34" />
            <stop offset="100%" stopColor="oklch(0.96 0.06 86)" stopOpacity="0" />
          </linearGradient>

          {/* Distance: each range a step closer to the sky than the last. */}
          <linearGradient id="s-range-far" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="oklch(0.766 0.022 232)" />
            <stop offset="100%" stopColor="oklch(0.812 0.020 240)" />
          </linearGradient>
          <linearGradient id="s-range-near" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="oklch(0.628 0.038 206)" />
            <stop offset="100%" stopColor="oklch(0.688 0.034 216)" />
          </linearGradient>

          {/* ── Ground ─────────────────────────────────────────────────── */}
          <linearGradient id="s-bank-l" x1="0.1" y1="0" x2="0.9" y2="1">
            <stop offset="0%" stopColor="oklch(0.636 0.096 126)" />
            <stop offset="55%" stopColor="oklch(0.532 0.092 138)" />
            <stop offset="100%" stopColor="oklch(0.446 0.078 148)" />
          </linearGradient>
          <linearGradient id="s-bank-r" x1="0.9" y1="0" x2="0.1" y2="1">
            <stop offset="0%" stopColor="oklch(0.512 0.068 168)" />
            <stop offset="55%" stopColor="oklch(0.422 0.060 178)" />
            <stop offset="100%" stopColor="oklch(0.352 0.050 184)" />
          </linearGradient>
          <linearGradient id="s-fore-l" x1="0" y1="0" x2="0.7" y2="1">
            <stop offset="0%" stopColor="oklch(0.442 0.086 132)" />
            <stop offset="62%" stopColor="oklch(0.336 0.070 144)" />
            <stop offset="100%" stopColor="oklch(0.238 0.046 154)" />
          </linearGradient>
          <linearGradient id="s-fore-r" x1="1" y1="0" x2="0.3" y2="1">
            <stop offset="0%" stopColor="oklch(0.362 0.058 170)" />
            <stop offset="62%" stopColor="oklch(0.272 0.046 180)" />
            <stop offset="100%" stopColor="oklch(0.196 0.032 188)" />
          </linearGradient>

          {/* The water is the sky lying down: gold where it points back at the
              sun, blue where it points at the top of the sky. */}
          {/* Darker than it looks like it should be. Water returns roughly a
              tenth of what falls on it, so a river painted at the sky's own
              lightness stops reading as water and becomes a road — which is
              exactly what the near-white first version did. */}
          <linearGradient id="s-water" x1="0.1" y1="0" x2="0.35" y2="1">
            <stop offset="0%" stopColor="oklch(0.862 0.048 94)" />
            <stop offset="26%" stopColor="oklch(0.742 0.038 132)" />
            <stop offset="62%" stopColor="oklch(0.598 0.040 208)" />
            <stop offset="100%" stopColor="oklch(0.462 0.046 240)" />
          </linearGradient>

          {/* ── The filters that do the painting ────────────────────────── */}
          <filter id="s-fuzz" x="-14%" y="-14%" width="128%" height="128%">
            <feTurbulence type="fractalNoise" baseFrequency="0.010 0.026" numOctaves="4" seed="11" result="n" />
            <feDisplacementMap in="SourceGraphic" in2="n" scale="32" xChannelSelector="R" yChannelSelector="G" />
            <feGaussianBlur stdDeviation="0.7" />
          </filter>
          <filter id="s-fuzz-near" x="-16%" y="-16%" width="132%" height="132%">
            <feTurbulence type="fractalNoise" baseFrequency="0.015 0.036" numOctaves="5" seed="4" result="n" />
            <feDisplacementMap in="SourceGraphic" in2="n" scale="44" xChannelSelector="R" yChannelSelector="G" />
            <feGaussianBlur stdDeviation="0.6" />
          </filter>
          {/* Undergrowth: a high frequency and a small displacement — many small
              bites rather than a few large ones, which is the difference between
              shrubs and dents. */}
          <filter id="s-tuft" x="-8%" y="-8%" width="116%" height="116%">
            <feTurbulence type="fractalNoise" baseFrequency="0.048 0.068" numOctaves="4" seed="23" result="n" />
            <feDisplacementMap in="SourceGraphic" in2="n" scale="15" xChannelSelector="R" yChannelSelector="G" />
            <feGaussianBlur stdDeviation="1" />
          </filter>
          <filter id="s-tuft-near" x="-8%" y="-8%" width="116%" height="116%">
            <feTurbulence type="fractalNoise" baseFrequency="0.038 0.056" numOctaves="5" seed="57" result="n" />
            <feDisplacementMap in="SourceGraphic" in2="n" scale="24" xChannelSelector="R" yChannelSelector="G" />
            <feGaussianBlur stdDeviation="1.3" />
          </filter>
          {/* Conifers get displacement without much blur: a frayed silhouette is
              the point, a soft one would just look out of focus. */}
          <filter id="s-needle" x="-10%" y="-10%" width="120%" height="120%">
            <feTurbulence type="fractalNoise" baseFrequency="0.09 0.13" numOctaves="3" seed="71" result="n" />
            <feDisplacementMap in="SourceGraphic" in2="n" scale="7" xChannelSelector="R" yChannelSelector="G" />
          </filter>

          <filter id="s-haze" x="-10%" y="-60%" width="120%" height="260%">
            <feGaussianBlur stdDeviation="10" />
          </filter>
          <filter id="s-haze-soft" x="-10%" y="-60%" width="120%" height="260%">
            <feGaussianBlur stdDeviation="4" />
          </filter>
          <filter id="s-mist" x="-20%" y="-300%" width="140%" height="700%">
            <feGaussianBlur stdDeviation="17" />
          </filter>
          <filter id="s-cloud" x="-20%" y="-300%" width="140%" height="700%">
            <feGaussianBlur stdDeviation="22" />
          </filter>
          <filter id="s-shaft-blur" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="15" />
          </filter>
          <filter id="s-ripple" x="-6%" y="-6%" width="112%" height="112%">
            <feGaussianBlur stdDeviation="1.5" />
          </filter>
          <filter id="s-glow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="2.4" />
          </filter>

          {/* The rays reach as far as the middle of the far treeline and stop.
              Any lower and they cross the mist banks, where a shaft of light
              lying flat *over* fog rather than through it reads as a smear. */}
          <clipPath id="s-above">
            <rect x="-40" y="-40" width="1520" height="920" />
          </clipPath>

          <clipPath id="s-river">
            <path d={RIVER} />
          </clipPath>

          {/* The pond. Its own gradient runs the other way to the river's: a
              still surface reflects what is directly above it, so the far edge
              carries the treeline and the near edge carries open sky. */}
          <linearGradient id="s-pond" x1="0" y1="0" x2="0.2" y2="1">
            <stop offset="0%" stopColor="oklch(0.462 0.048 178)" />
            <stop offset="34%" stopColor="oklch(0.606 0.044 214)" />
            <stop offset="72%" stopColor="oklch(0.812 0.046 92)" />
            <stop offset="100%" stopColor="oklch(0.902 0.062 88)" />
          </linearGradient>
          <clipPath id="s-pond-clip">
            <ellipse cx={POND.cx} cy={POND.cy} rx={POND.rx} ry={POND.ry} />
          </clipPath>

          <radialGradient id="s-vig" cx="50%" cy="40%" r="74%">
            <stop offset="52%" stopColor="white" stopOpacity="0" />
            <stop offset="100%" stopColor="white" stopOpacity="1" />
          </radialGradient>
          <mask id="s-vig-mask">
            <rect width="1440" height="1240" fill="url(#s-vig)" />
          </mask>
        </defs>

        {/* ── Sky ───────────────────────────────────────────────────────── */}
        <rect width="1440" height="1240" fill="url(#s-sky)" />

        <g fill="oklch(0.98 0.02 96)">
          {STARS.map((s, i) => (
            <circle key={i} cx={s.cx} cy={s.cy} r={s.rad} opacity={s.o} />
          ))}
        </g>

        {/* God rays, drawn before the sun so its glow covers the point where
            they all converge — a blur softens an edge but cannot soften a point,
            and eight apexes stacked on one spot is a bright wedge with a hard
            corner otherwise. Clipped above the near treeline as well, so nothing
            lands on the forest floor. */}
        <g clipPath="url(#s-above)">
          <g filter="url(#s-shaft-blur)">
            {SHAFTS.map((s, i) => (
              <polygon
                key={i}
                points={`0,0 ${-s.w},1000 ${s.w},1000`}
                transform={`translate(${SUN.x} ${SUN.y}) rotate(${s.deg})`}
                fill="url(#s-shaft)"
                opacity={s.o}
                className={still ? undefined : "hs-glint"}
                style={
                  still
                    ? undefined
                    : css({
                        "--hs-dur": `${s.dur}s`,
                        "--hs-delay": `${s.delay}s`,
                        "--hs-o1": s.o * 0.55,
                        "--hs-o2": s.o * 1.6,
                      })
                }
              />
            ))}
          </g>
        </g>

        {/* The sun: right of centre and clear of the ridgeline. Centred, it
            becomes a spotlight directly behind the headline; below the ridge —
            where it started — the rays have no visible source and the sky reads
            as evenly lit from nowhere.

            It breathes on `scale`, not on `ry`: Framer Motion animates an SVG
            geometry attribute only when it can read a starting value, and `ry`
            has no computed one — it resolved to the string "undefined" and the
            browser rejected the attribute outright. */}
        {/* Kept tight. A wide glow lights the whole right half of the sky, and
            the rays are then drawn over their own halo — they were present and
            invisible at `rx=500` for exactly that reason. Pulling it in gives
            them a darker sky to cross a few hundred units out. */}
        <motion.ellipse
          cx={SUN.x}
          cy={SUN.y}
          rx="330"
          ry="230"
          fill="url(#s-sun)"
          style={{ transformBox: "fill-box", transformOrigin: "center" }}
          {...(still
            ? {}
            : {
                animate: { scaleY: [1, 1.07, 1], opacity: [0.9, 1, 0.9] },
                transition: { duration: 17, repeat: Infinity, ease: "easeInOut" },
              })}
        />
        {/* The disc itself, small and very bright. The glow above reads as haze
            without it — light in the air, with nothing making it. */}
        <circle cx={SUN.x} cy={SUN.y} r="34" fill="oklch(0.99 0.048 94)" opacity="0.9" />
        <circle
          cx={SUN.x}
          cy={SUN.y}
          r="76"
          fill="oklch(0.985 0.062 92)"
          opacity="0.42"
          filter="url(#s-haze-soft)"
        />

        {/* Cloud strata: long, thin, heavily blurred, so they read as layers of
            air rather than as the cotton wool a cloud-shaped path becomes. */}
        <g filter="url(#s-cloud)">
          {[
            { cx: 520, cy: 196, rx: 430, ry: 14, f: "oklch(0.52 0.058 262)", o: 0.5, d: 74 },
            { cx: 980, cy: 268, rx: 500, ry: 19, f: "oklch(0.60 0.050 254)", o: 0.46, d: 62 },
            { cx: 420, cy: 336, rx: 470, ry: 16, f: "oklch(0.78 0.042 232)", o: 0.42, d: 86 },
            { cx: 1010, cy: 400, rx: 540, ry: 21, f: "oklch(0.93 0.058 92)", o: 0.5, d: 54 },
            { cx: 600, cy: 462, rx: 520, ry: 12, f: "oklch(0.96 0.048 88)", o: 0.46, d: 92 },
            { cx: 1140, cy: 498, rx: 380, ry: 10, f: "oklch(0.97 0.042 86)", o: 0.38, d: 68 },
          ].map((c, i) => (
            <ellipse
              key={i}
              cx={c.cx}
              cy={c.cy}
              rx={c.rx}
              ry={c.ry}
              fill={c.f}
              opacity={c.o}
              className={still ? undefined : "hs-drift"}
              style={
                still
                  ? undefined
                  : css({
                      "--hs-dur": `${c.d}s`,
                      "--hs-delay": `${-i * 7}s`,
                      "--hs-dx": `${i % 2 ? -80 : 80}px`,
                      "--hs-o1": c.o,
                      "--hs-o2": c.o * 1.2,
                    })
              }
            />
          ))}
        </g>

        {/* Birds. */}
        <g stroke="oklch(0.30 0.04 250)" fill="none" strokeLinecap="round">
          {BIRDS.map(([x, y, s], i) => (
            <motion.path
              key={i}
              d={`M${x} ${y} q ${7 * s} ${-6 * s} ${14 * s} 0 q ${7 * s} ${-6 * s} ${14 * s} 0`}
              strokeWidth={1.7 * s}
              opacity={0.32 * s + 0.16}
              {...(still
                ? {}
                : {
                    animate: { x: [0, 30, 0], y: [0, -10, 0] },
                    transition: { duration: 26 + i * 3, repeat: Infinity, ease: "easeInOut" },
                  })}
            />
          ))}
        </g>

        {/* ── Distance ───────────────────────────────────────────────────
            Ridge, then its treeline, then the mist that sits in front of both.
            That order is the whole of aerial perspective: each stand is fogged
            by the bank in front of it and not by its own. */}
        <g filter="url(#s-haze)">
          <path
            fill="url(#s-range-far)"
            d="M-40 590 C 100 522, 220 548, 340 542 C 470 536, 560 566, 690 546 C 820 526, 906 566, 1040 540 C 1170 514, 1310 556, 1480 528 L 1480 720 L -40 720 Z"
          />
        </g>
        <g filter="url(#s-needle)" opacity="0.85">
          {STAND_FAR.map((t, i) => (
            <path key={i} d={t.d} fill={t.fill} opacity={t.o * 0.5} />
          ))}
        </g>

        <g filter="url(#s-haze-soft)">
          <path
            fill="url(#s-range-near)"
            d="M-40 654 C 110 606, 230 646, 356 636 C 486 626, 570 660, 692 646 C 818 632, 900 664, 1024 642 C 1160 618, 1312 654, 1480 634 L 1480 800 L -40 800 Z"
          />
        </g>
        <g filter="url(#s-needle)">
          {STAND_NEAR.map((t, i) => (
            <path key={i} d={t.d} fill={t.fill} opacity={t.o * 0.72} />
          ))}
        </g>

        {/* Mist, in the gaps. The layer that does most of the work of making a
            treeline two miles away look two miles away. */}
        <g filter="url(#s-mist)" fill="oklch(0.955 0.012 216)">
          {MIST.map((m, i) => (
            <rect
              key={i}
              x="-260"
              y={m.y}
              width="1960"
              height={m.h}
              opacity={m.o1}
              className={still ? undefined : "hs-drift"}
              style={
                still
                  ? undefined
                  : css({
                      "--hs-dur": `${m.dur}s`,
                      "--hs-delay": `${m.delay}s`,
                      "--hs-dx": `${m.dx}px`,
                      "--hs-o1": m.o1,
                      "--hs-o2": m.o2,
                    })
              }
            />
          ))}
        </g>

        {/* ── The water ─────────────────────────────────────────────────
            Drawn before the banks and then bitten into by them, so the river
            interlocks with the land instead of being a channel painted on top.
            It runs down the centre because that is the one column the product
            panel does not cover until well below the fold. */}
        <path fill="url(#s-water)" d={RIVER} />
        <g clipPath="url(#s-river)">
          {/* The sun's own column on the water — the single detail that reads as
              "water" rather than "pale road". */}
          <path
            fill="oklch(0.985 0.038 90)"
            opacity="0.42"
            filter="url(#s-haze-soft)"
            d="M716 654 C 708 706, 700 750, 668 800 C 640 846, 580 912, 552 972 L 616 972 C 648 900, 704 810, 720 736 Z"
          />
          <g fill="oklch(0.99 0.02 92)" filter="url(#s-ripple)">
            {RIPPLES.map((rp, i) => (
              <ellipse key={i} cx={rp.cx} cy={rp.cy} rx={rp.rx} ry={1.4} opacity={rp.o} />
            ))}
          </g>
          <g fill="oklch(0.995 0.03 92)" filter="url(#s-ripple)">
            {GLINTS.map((g, i) => (
              <ellipse
                key={i}
                cx={g.cx}
                cy={g.cy}
                rx={g.rx}
                ry={1.8}
                opacity={0.3}
                className={still ? undefined : "hs-glint"}
                style={
                  still
                    ? undefined
                    : css({
                        "--hs-dur": `${g.dur}s`,
                        "--hs-delay": `${g.delay}s`,
                        "--hs-o1": 0.12,
                        "--hs-o2": g.o2,
                      })
                }
              />
            ))}
          </g>
        </g>

        {/* ── The valley walls ──────────────────────────────────────────
            The ground never moves; only what grows on it does. Each bank is a
            static path, then its stand and undergrowth inside a gust/sway pair
            with its own period. */}
        <path
          filter="url(#s-fuzz)"
          fill="url(#s-bank-l)"
          d="M-60 706 C 90 652, 236 684, 356 680 C 476 676, 560 714, 646 754 C 720 788, 706 866, 604 916 C 466 984, 214 966, -60 992 Z"
        />
        <path
          filter="url(#s-fuzz)"
          fill="url(#s-bank-r)"
          d="M1500 694 C 1350 652, 1190 686, 1058 682 C 930 678, 856 720, 792 762 C 728 804, 758 876, 862 918 C 1022 982, 1296 962, 1500 984 Z"
        />

        {/* ── The pond ──────────────────────────────────────────────────
            Drawn on the left bank *before* its undergrowth, so the clumps at
            the rim overlap the water and the edge reads as a bank rather than
            as a shape laid on the grass. Nothing grows in it — `scatter` was
            given the pond as a rejection region. */}
        <g>
          <ellipse
            cx={POND.cx}
            cy={POND.cy}
            rx={POND.rx}
            ry={POND.ry}
            fill="url(#s-pond)"
          />
          <g clipPath="url(#s-pond-clip)">
            {/* The treeline, reflected. Darker than the trees themselves and
                blurred sideways: water returns a softened, dimmer copy, and a
                crisp mirror image is the tell of a rendered puddle. */}
            <ellipse
              cx={POND.cx}
              cy={POND.cy - POND.ry * 0.62}
              rx={POND.rx}
              ry={POND.ry * 0.72}
              fill="oklch(0.386 0.062 158)"
              opacity="0.5"
              filter="url(#s-haze-soft)"
            />
            {/* And the sun, low and to the right, laid across the near half. */}
            <ellipse
              cx={POND.cx + POND.rx * 0.34}
              cy={POND.cy + POND.ry * 0.42}
              rx={POND.rx * 0.5}
              ry={POND.ry * 0.3}
              fill="oklch(0.975 0.052 90)"
              opacity="0.42"
              filter="url(#s-haze-soft)"
            />

            {/* Lily pads, before the rings, so the rings run over them. */}
            <g fill="oklch(0.436 0.086 148)">
              {LILIES.map((l, i) => (
                <ellipse key={i} cx={l.cx} cy={l.cy} rx={l.rx} ry={l.rx * 0.34} opacity={l.o} />
              ))}
            </g>

            {!still && (
              <g fill="none" stroke="oklch(0.99 0.024 92)">
                {POND_RINGS.map((p, i) => (
                  <ellipse
                    key={i}
                    cx={p.ox}
                    cy={p.oy}
                    rx={p.rx}
                    ry={p.ry}
                    strokeWidth="1.3"
                    vectorEffect="non-scaling-stroke"
                    className="hs-ring"
                    style={css({
                      "--hs-dur": `${p.dur}s`,
                      "--hs-delay": `${p.delay}s`,
                      "--hs-o": p.o,
                    })}
                  />
                ))}
              </g>
            )}
          </g>
          {/* A wet rim, drawn last and only along the near edge — the far edge
              is where the bank's own undergrowth will meet the water. */}
          <ellipse
            cx={POND.cx}
            cy={POND.cy}
            rx={POND.rx}
            ry={POND.ry}
            fill="none"
            stroke="oklch(0.352 0.056 156)"
            strokeWidth="2"
            opacity="0.32"
          />
        </g>

        <g {...gust(23, -3, 0.42, 5)}>
          <g {...sway(6.4, -1.8, 0.36)}>
            <g filter="url(#s-needle)">
              {STAND_MID_L.map((t, i) => (
                <path key={i} d={t.d} fill={t.fill} opacity={t.o} />
              ))}
            </g>
            <g filter="url(#s-tuft)">
              {COVER_MID_L.map((b, i) => (
                <ellipse key={i} cx={b.x} cy={b.y} rx={b.rx} ry={b.ry} fill={b.fill} opacity={b.o} />
              ))}
            </g>
          </g>
        </g>

        <g {...gust(27, -11, 0.38, -6)}>
          <g {...sway(7.6, -4.2, 0.32)}>
            <g filter="url(#s-needle)">
              {STAND_MID_R.map((t, i) => (
                <path key={i} d={t.d} fill={t.fill} opacity={t.o} />
              ))}
            </g>
            <g filter="url(#s-tuft)">
              {COVER_MID_R.map((b, i) => (
                <ellipse key={i} cx={b.x} cy={b.y} rx={b.rx} ry={b.ry} fill={b.fill} opacity={b.o} />
              ))}
            </g>
          </g>
        </g>

        {/* ── Foreground ────────────────────────────────────────────────
            Both mounds run past the bottom of the canvas: the near filter
            displaces edges by up to 44 units, so a path stopping at 1240 would
            be pulled off the canvas in places and leave the page colour showing
            through as a ragged strip. */}
        <path
          filter="url(#s-fuzz-near)"
          fill="url(#s-fore-l)"
          d="M-80 930 C 80 862, 268 886, 400 930 C 516 968, 556 1024, 524 1320 L -80 1320 Z"
        />
        <path
          filter="url(#s-fuzz-near)"
          fill="url(#s-fore-r)"
          d="M1520 910 C 1360 850, 1156 880, 1010 932 C 892 974, 838 1038, 862 1320 L 1520 1320 Z"
        />

        {/* Near trees, each swaying on its own period inside the bank's gust —
            the reason the foreground never moves as one sheet. */}
        {[
          { trees: NEAR_TREES_L, g: gust(19, -6, 0.6, 8) },
          { trees: NEAR_TREES_R, g: gust(21, -13, 0.55, -7) },
        ].map((band, bi) => (
          <g key={bi} {...band.g}>
            {band.trees.map((t, i) => (
              <g key={i} {...sway(t.dur, t.delay, 0.75)}>
                <g filter="url(#s-tuft-near)">
                  <path d={t.trunk} fill="oklch(0.286 0.034 96)" opacity="0.85" />
                  {t.canopy.map((c, j) => (
                    <ellipse key={j} cx={c.x} cy={c.y} rx={c.rx} ry={c.ry} fill={c.fill} opacity={c.o} />
                  ))}
                </g>
              </g>
            ))}
          </g>
        ))}

        <g {...gust(17, -2, 0.5, 7)}>
          <g {...sway(5.2, -3.1, 0.5)}>
            <g filter="url(#s-tuft-near)">
              {COVER_FORE_L.map((b, i) => (
                <ellipse key={i} cx={b.x} cy={b.y} rx={b.rx} ry={b.ry} fill={b.fill} opacity={b.o} />
              ))}
            </g>
          </g>
        </g>
        <g {...gust(20, -9, 0.46, -8)}>
          <g {...sway(6.1, -0.9, 0.46)}>
            <g filter="url(#s-tuft-near)">
              {COVER_FORE_R.map((b, i) => (
                <ellipse key={i} cx={b.x} cy={b.y} rx={b.rx} ry={b.ry} fill={b.fill} opacity={b.o} />
              ))}
            </g>
          </g>
        </g>

        {/* ── Ambient ───────────────────────────────────────────────────
            Not rendered at all under `prefers-reduced-motion`, rather than
            rendered and held still: a frozen insect is worse than no insect. */}
        {!still && (
          <>
            <g fill="oklch(0.97 0.06 96)" filter="url(#s-glow)">
              {MOTES.map((m, i) => (
                <circle
                  key={i}
                  cx={m.cx}
                  cy={m.cy}
                  r={m.rad}
                  className="hs-mote"
                  style={css({
                    "--hs-dur": `${m.dur}s`,
                    "--hs-delay": `${m.delay}s`,
                    "--hs-dx": `${m.dx}px`,
                    "--hs-dy": `${m.dy}px`,
                    "--hs-o": m.o,
                  })}
                />
              ))}
            </g>

            {LEAVES.map((l, i) => (
              <ellipse
                key={i}
                cx={l.cx}
                cy={l.cy}
                rx={l.rx}
                ry={l.ry}
                fill={l.fill}
                className="hs-leaf"
                style={css({
                  "--hs-dur": `${l.dur}s`,
                  "--hs-delay": `${l.delay}s`,
                  "--hs-dx": `${l.dx}px`,
                  "--hs-dy": `${l.dy}px`,
                })}
              />
            ))}
          </>
        )}

        {/* ── Air ───────────────────────────────────────────────────────
            One warm veil over everything below the horizon. Without it the
            foreground and the ridges read as two unrelated pictures, because
            nothing has put the same light on both. */}
        <rect x="0" y="560" width="1440" height="680" fill="oklch(0.92 0.062 88)" opacity="0.11" />

        {/* The vignette, last, over everything. */}
        <rect
          width="1440"
          height="1240"
          fill="oklch(0.26 0.050 252)"
          opacity="0.22"
          mask="url(#s-vig-mask)"
        />
      </svg>

      {/* The resolve. The one part of the artwork that follows the theme: the
          picture has to land exactly on the page colour beneath it or it ends in
          a seam, and that colour is different in each. */}
      <div className="absolute inset-x-0 bottom-0 h-36 bg-gradient-to-b from-transparent to-bg" />
    </div>
  );
}
