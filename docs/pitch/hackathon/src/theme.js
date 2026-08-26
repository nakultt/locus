// Anthropic / Claude design language, adapted for slides.
//
// Cream ground, one coral accent, warm neutrals. Serif display (Cambria stands
// in for Tiempos) over a sans body (Calibri stands in for Styrene) — both are
// metric-safe so text-fit in QA is trustworthy.

const C = {
  cream:   "F0EEE6", // Anthropic bone — page ground
  card:    "FAF9F5", // raised surface
  dark:    "1F1E1D", // dark ground for title / section / closing
  dark2:   "2A2826", // raised surface on dark
  ink:     "191919",
  inkOnDk: "F5F3EE",
  muted:   "73716C",
  mutedDk: "A8A49C",
  rule:    "DFDBD1",
  ruleDk:  "3D3A36",

  coral:   "D97757", // Claude coral — the single accent
  cloth:   "CC785C", // book cloth, secondary
  kraft:   "D4A27F",
  manilla: "EBDBBC",

  // chart neutrals — coral highlights the point, greys carry the rest
  n1: "C9C3B8",
  n2: "AFA89C",
  n3: "8C857A",
};

const F = { display: "Cambria", body: "Calibri" };

const SLIDE = { w: 13.333, h: 7.5, m: 0.75 };

module.exports = { C, F, SLIDE };
