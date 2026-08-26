// Shared slide furniture. Every helper returns fresh option objects, because
// pptxgenjs converts values to EMU in place on first use and a shared object
// silently corrupts the second call that borrows it.

const { C, F } = require("./theme");

const shadow = () => ({
  type: "outer", color: "8C857A", blur: 12, offset: 2, angle: 90, opacity: 0.16,
});

/** Raised surface on the cream ground. */
function card(s, pres, x, y, w, h, opts = {}) {
  s.addShape(pres.ShapeType.roundRect, {
    x, y, w, h,
    fill: { color: opts.fill || C.card },
    line: { color: opts.line || C.rule, width: 0.75 },
    rectRadius: 0.09,
    shadow: opts.flat ? undefined : shadow(),
  });
}

/** Raised surface on a dark ground. */
function darkCard(s, pres, x, y, w, h, lineColor) {
  s.addShape(pres.ShapeType.roundRect, {
    x, y, w, h,
    fill: { color: C.dark2 },
    line: { color: lineColor || C.ruleDk, width: 1 },
    rectRadius: 0.09,
  });
}

/** The deck's repeated motif: a filled circle carrying a number or glyph. */
function chip(s, pres, x, y, d, text, fill, fg, size) {
  s.addText(text, {
    x, y, w: d, h: d,
    shape: pres.ShapeType.ellipse,
    fill: { color: fill },
    color: fg,
    fontFace: F.body, fontSize: size, bold: true,
    align: "center", valign: "middle", margin: 0,
  });
}

/** Small uppercase tracking label. */
function eyebrow(s, text, x, y, w, color) {
  s.addText(text, {
    x, y, w, h: 0.26,
    fontFace: F.body, fontSize: 10.5, bold: true,
    color: color || C.coral, charSpacing: 2.4, margin: 0,
  });
}

/** Slide title. Says the point, not the topic. */
function title(s, text, opts = {}) {
  s.addText(text, {
    x: 0.75, y: opts.y ?? 0.5, w: opts.w ?? 11.9, h: opts.h ?? 1.28,
    fontFace: F.display, fontSize: opts.size ?? 31, bold: true,
    color: opts.dark ? C.inkOnDk : C.ink,
    valign: "middle", margin: 0,
  });
}

/** Deck under the title. */
function sub(s, text, opts = {}) {
  s.addText(text, {
    x: 0.75, y: opts.y ?? 1.84, w: opts.w ?? 11.9, h: 0.32,
    fontFace: F.body, fontSize: opts.size ?? 14.5,
    color: opts.dark ? C.mutedDk : C.muted, margin: 0,
  });
}

/** The "so what" line that closes a data slide. */
function takeaway(s, text, y, opts = {}) {
  s.addText(text, {
    x: 0.75, y, w: opts.w ?? 11.9, h: 0.4,
    fontFace: F.display, fontSize: 17, bold: true,
    color: opts.dark ? C.kraft : C.cloth, margin: 0,
  });
}

/** Headline number with a caption under it. */
function stat(s, x, y, w, value, label, opts = {}) {
  s.addText(value, {
    x, y, w, h: 0.85,
    fontFace: F.display, fontSize: opts.size ?? 40, bold: true,
    color: opts.color || C.coral, margin: 0, valign: "middle",
  });
  s.addText(label, {
    x, y: y + 0.82, w, h: 0.46,
    fontFace: F.body, fontSize: 11.5,
    color: opts.dark ? C.mutedDk : C.muted, margin: 0,
    lineSpacingMultiple: 1.15,
  });
}

/** Common chart frame — quiet axes, no legend noise, labelled values. */
const chartBase = (over = {}) => Object.assign({
  chartColors: [C.coral, C.n1, C.n3],
  showLegend: false,
  showTitle: false,
  showValue: true,
  dataLabelColor: C.ink,
  dataLabelFontFace: F.body,
  dataLabelFontSize: 10,
  catAxisLabelColor: C.muted,
  catAxisLabelFontFace: F.body,
  catAxisLabelFontSize: 10.5,
  valAxisLabelColor: C.muted,
  valAxisLabelFontFace: F.body,
  valAxisLabelFontSize: 9.5,
  catGridLine: { style: "none" },
  valGridLine: { color: C.rule, size: 0.75 },
  chartArea: { fill: { color: C.card } },
  plotArea: { fill: { color: C.card } },
}, over);

/** Tight stat for a KPI grid cell. */
function miniStat(s, x, y, w, value, label) {
  s.addText(value, {
    x, y, w, h: 0.52,
    fontFace: F.display, fontSize: 21, bold: true, color: C.coral,
    margin: 0, valign: "middle",
  });
  s.addText(label, {
    x, y: y + 0.52, w, h: 0.5,
    fontFace: F.body, fontSize: 10, color: C.muted, margin: 0,
    lineSpacingMultiple: 1.1,
  });
}

module.exports = { card, darkCard, chip, eyebrow, title, sub, takeaway, stat, miniStat, chartBase, shadow };
