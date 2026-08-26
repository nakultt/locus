const pptxgen = require("pptxgenjs");
const { C, F } = require("./theme");
const L = require("./lib");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.author = "Nakul";
pres.company = "Locus";
pres.title = "Locus — two modes, one pipeline";

const S = () => pres.addSlide();

// ===========================================================================
// 1 · TITLE
// ===========================================================================
let s = S();
s.background = { color: C.dark };

L.eyebrow(s, "AI BUILDER HACKATHON 2026", 0.75, 1.42, 6.5, C.kraft);
s.addText("Locus", {
  x: 0.7, y: 1.82, w: 7.2, h: 1.35,
  fontFace: F.display, fontSize: 74, bold: true, color: C.inkOnDk,
  margin: 0, valign: "middle",
});
s.addText("An AI teammate that carries a ticket from assignment to QA sign-off.", {
  x: 0.75, y: 3.3, w: 6.6, h: 0.95,
  fontFace: F.body, fontSize: 20, color: C.kraft,
  margin: 0, lineSpacingMultiple: 1.22,
});
s.addText("Two modes. One pipeline. Every model that reads your code runs locally.", {
  x: 0.75, y: 4.5, w: 6.6, h: 0.36,
  fontFace: F.body, fontSize: 14, italic: true, color: C.mutedDk, margin: 0,
});

// headline proof strip
const proof = [["9", "steps automated\nper work item"], ["706", "tests\npassing"],
                ["8", "tools\nconnected"], ["0", "cloud calls to\nanalyse your code"]];
proof.forEach(([v, k], i) => {
  L.stat(s, 0.78 + i * 1.72, 5.35, 1.6, v, k, { dark: true, size: 30, color: C.coral });
});

// two-lane mark
s.addShape(pres.ShapeType.ellipse, {
  x: 8.55, y: 2.05, w: 1.45, h: 1.45,
  fill: { color: C.dark2 }, line: { color: C.mutedDk, width: 1.25 },
});
s.addText("YOU", {
  x: 8.55, y: 2.05, w: 1.45, h: 1.45, fontFace: F.body, fontSize: 14, bold: true,
  color: C.inkOnDk, align: "center", valign: "middle", margin: 0,
});
L.chip(s, pres, 8.55, 4.05, 1.45, "AGENT", C.coral, C.dark, 12);
s.addShape(pres.ShapeType.line, { x: 10.0, y: 2.78, w: 1.05, h: 0.92, line: { color: C.mutedDk, width: 1.25 } });
s.addShape(pres.ShapeType.line, { x: 10.0, y: 3.7, w: 1.05, h: 1.05, flipV: true, line: { color: C.coral, width: 1.25 } });
s.addText("ONE\nPIPELINE", {
  x: 11.05, y: 2.7, w: 1.9, h: 2.0, shape: pres.ShapeType.roundRect,
  fill: { color: C.dark2 }, line: { color: C.kraft, width: 1 }, rectRadius: 0.1,
  fontFace: F.body, fontSize: 13.5, bold: true, color: C.inkOnDk,
  align: "center", valign: "middle", charSpacing: 1.4, margin: 0,
});
s.addNotes("Locus takes a ticket from the moment it is assigned to the moment testing signs it off. Two modes: you write the code, or the agent does. Everything behind that is the same pipeline. Every model that reads your code automatically runs on your own hardware.");

// ===========================================================================
// 2 · THE PROBLEM, QUANTIFIED
// ===========================================================================
s = S();
s.background = { color: C.cream };
L.title(s, "A work item takes 12 steps. A person does 10 of them by hand.");
L.sub(s, "Only two of them need human judgement. Nine are pure coordination.");

s.addChart(
  pres.ChartType.bar,
  [
    { name: "Done by hand", labels: ["Today", "Locus · Assisted", "Locus · Autonomous"], values: [10, 1, 0] },
    { name: "Human judgement", labels: ["Today", "Locus · Assisted", "Locus · Autonomous"], values: [2, 2, 2] },
    { name: "Automated", labels: ["Today", "Locus · Assisted", "Locus · Autonomous"], values: [0, 9, 10] },
  ],
  L.chartBase({
    x: 0.75, y: 2.32, w: 7.75, h: 3.55,
    barDir: "bar", barGrouping: "stacked",
    chartColors: [C.coral, C.kraft, C.n1],
    dataLabelPosition: "ctr",
    dataLabelColor: C.ink,
    showLegend: true, legendPos: "b", legendColor: C.muted,
    legendFontFace: F.body, legendFontSize: 10.5,
    valAxisMaxVal: 12, valGridLine: { color: C.rule, size: 0.75 },
    barGapWidthPct: 55,
  })
);

L.card(s, pres, 8.85, 2.32, 3.75, 3.55);
L.eyebrow(s, "THE TWO THAT STAY", 9.15, 2.62, 3.2);
s.addText(
  [
    { text: "Reviewing the change against what the team actually agreed.", options: { bullet: { code: "25CF" }, breakLine: true } },
    { text: "Verifying it works before the ticket closes.", options: { bullet: { code: "25CF" } } },
  ],
  { x: 9.2, y: 3.02, w: 3.15, h: 1.4, fontFace: F.body, fontSize: 12.5, color: C.ink, margin: 0, paraSpaceAfter: 9, lineSpacingMultiple: 1.2 }
);
s.addText(
  "Everything else — gathering context, scanning, notifying, chasing, merging, briefing testers, moving the card, writing the record — is coordination a person should never have been doing.",
  { x: 9.2, y: 4.5, w: 3.15, h: 1.3, fontFace: F.body, fontSize: 11.5, color: C.muted, margin: 0, lineSpacingMultiple: 1.22 }
);

L.takeaway(s, "Locus removes the coordination and leaves the judgement.", 6.35);
s.addNotes("Twelve steps in a work item's life. Ten are done by hand today. Only two of them actually need a human: reviewing against the requirement, and verifying it works. Locus takes the other ten.");

// ===========================================================================
// 3 · WHY THE BOARD IS BLIND
// ===========================================================================
s = S();
s.background = { color: C.cream };
L.title(s, "Your board can see one of the eight stages a ticket passes through.");
L.sub(s, "GitHub's project automation has exactly one useful trigger: an item closing.");

const stages = ["Assigned", "Branch\ncreated", "In\nreview", "Changes\nrequested",
                "Approved", "Merged", "With\ntesting", "Signed\noff"];
stages.forEach((st, i) => {
  const x = 0.75 + i * 1.5;
  const visible = i === 7;
  L.chip(s, pres, x + 0.32, 2.42, 0.72, visible ? "✓" : "", visible ? C.coral : C.cream,
         visible ? C.card : C.muted, 18);
  if (!visible) {
    s.addShape(pres.ShapeType.ellipse, {
      x: x + 0.32, y: 2.42, w: 0.72, h: 0.72,
      fill: { color: C.cream }, line: { color: C.n2, width: 1, dashType: "dash" },
    });
  }
  s.addText(st, {
    x, y: 3.26, w: 1.36, h: 0.62, fontFace: F.body, fontSize: 10.5,
    color: visible ? C.ink : C.muted, bold: visible, align: "center",
    valign: "top", margin: 0, lineSpacingMultiple: 1.05,
  });
  if (i < 7) {
    s.addShape(pres.ShapeType.line, {
      x: x + 1.09, y: 2.78, w: 0.37, h: 0, line: { color: C.n2, width: 1 },
    });
  }
});
s.addText("visible to the board", {
  x: 11.2, y: 3.92, w: 1.9, h: 0.28, fontFace: F.body, fontSize: 9.5,
  italic: true, color: C.coral, align: "center", margin: 0,
});

const gaps = [
  ["87%", "of a ticket's pipeline is invisible\non the board today"],
  ["8 of 8", "stages Locus writes to the card,\nordered by the board's own columns"],
  ["1", "backwards move allowed — a QA\nrejection, because the tester said so"],
];
gaps.forEach(([v, k], i) => {
  L.card(s, pres, 0.75 + i * 4.07, 4.42, 3.82, 1.62);
  L.stat(s, 1.05 + i * 4.07, 4.58, 3.3, v, k, { size: 27 });
});

L.takeaway(s, "The half a board can never show is the half Locus automates.", 6.42);
s.addNotes("GitHub's own project workflows trigger on exactly one thing: an item closing. So a ticket sits in Todo through the branch, the review round trip and the whole QA thread, then jumps to Done. Seven of the eight stages are invisible.");

// ===========================================================================
// 4 · THE PIPELINE
// ===========================================================================
s = S();
s.background = { color: C.cream };
L.title(s, "Nine steps run on every push, grouped into three phases.");
L.sub(s, "Driven by webhooks and three background loops — nothing waits for a person to click.");

const phases = [
  ["BEFORE THE REVIEW", [
    ["Gather context", "ticket · Slack · issues · specs"],
    ["Scan the diff", "Semgrep · Gitleaks · model pass"],
    ["Review the code", "against the requirement"],
  ]],
  ["AROUND THE REVIEW", [
    ["Post the findings", "PR comment, edited in place"],
    ["Track the rounds", "state GitHub does not keep"],
    ["Merge when gated", "approval + green CI + clean"],
  ]],
  ["AFTER THE MERGE", [
    ["Brief the testers", "email or a Slack thread"],
    ["Read the verdict", "closes, or reopens the ticket"],
    ["Record everything", "board card + one living doc"],
  ]],
];
phases.forEach(([name, items], p) => {
  const x = 0.75 + p * 4.07;
  L.card(s, pres, x, 2.32, 3.82, 3.55);
  L.eyebrow(s, name, x + 0.3, 2.6, 3.3);
  items.forEach(([label, detail], i) => {
    const y = 3.04 + i * 0.92;
    L.chip(s, pres, x + 0.3, y, 0.4, String(p * 3 + i + 1), C.coral, C.card, 11);
    s.addText(label, {
      x: x + 0.82, y: y - 0.03, w: 2.75, h: 0.28,
      fontFace: F.body, fontSize: 12.5, bold: true, color: C.ink, margin: 0,
    });
    s.addText(detail, {
      x: x + 0.82, y: y + 0.25, w: 2.75, h: 0.28,
      fontFace: F.body, fontSize: 10.5, color: C.muted, margin: 0,
    });
  });
});
L.takeaway(s, "Every message searched, sent and received is recorded — never summarized.", 6.35);
s.addNotes("Nine steps in three phases. Before the review it gathers context and scans. Around the review it posts findings, tracks the round trip GitHub does not record, and merges when the gate passes. After the merge it briefs testing, reads the verdict, and keeps the board and the record honest.");

// ===========================================================================
// 5 · TWO MODES  (hero)
// ===========================================================================
s = S();
s.background = { color: C.dark };
L.title(s, "Two modes. They differ in exactly one place.", { dark: true, size: 33 });
L.sub(s, "Who writes the code. Everything behind that is identical.", { dark: true });

L.darkCard(s, pres, 0.75, 2.32, 5.85, 3.35, C.ruleDk);
L.eyebrow(s, "ASSISTED", 1.15, 2.66, 4.5, C.mutedDk);
s.addText("You write the code.", {
  x: 1.12, y: 3.04, w: 5.1, h: 0.5, fontFace: F.display, fontSize: 27,
  bold: true, color: C.inkOnDk, margin: 0, valign: "middle",
});
s.addText("Locus runs the other nine steps around you — the context, the scan, the review chasing, the QA loop, the board, the record.", {
  x: 1.15, y: 3.68, w: 5.1, h: 1.2, fontFace: F.body, fontSize: 13,
  color: C.mutedDk, margin: 0, lineSpacingMultiple: 1.28,
});
s.addText("9 of 12 steps automated", {
  x: 1.15, y: 5.05, w: 5.1, h: 0.32, fontFace: F.body, fontSize: 12,
  bold: true, color: C.kraft, margin: 0,
});

L.darkCard(s, pres, 6.9, 2.32, 5.68, 3.35, C.coral);
L.eyebrow(s, "AUTONOMOUS", 7.3, 2.66, 4.5, C.coral);
s.addText("Locus writes the code.", {
  x: 7.27, y: 3.04, w: 5.0, h: 0.5, fontFace: F.display, fontSize: 27,
  bold: true, color: C.inkOnDk, margin: 0, valign: "middle",
});
s.addText("You assign it the ticket. It reads the requirement, makes the change, opens the pull request — and the same nine steps run behind it.", {
  x: 7.3, y: 3.68, w: 5.0, h: 1.2, fontFace: F.body, fontSize: 13,
  color: C.mutedDk, margin: 0, lineSpacingMultiple: 1.28,
});
s.addText("10 of 12 steps automated", {
  x: 7.3, y: 5.05, w: 5.0, h: 0.32, fontFace: F.body, fontSize: 12,
  bold: true, color: C.coral, margin: 0,
});

s.addText("Your senior dev still reviews it. Your tester still signs it off. The author is the only thing that changes.", {
  x: 0.78, y: 5.98, w: 11.9, h: 0.45, fontFace: F.display, fontSize: 18,
  bold: true, color: C.kraft, margin: 0,
});
s.addNotes("Assisted: you write the code, Locus does the rest. Autonomous: you hand it the ticket and it opens the pull request. The review and the QA sign-off are unchanged in both. The author is the only difference.");

// ===========================================================================
// 6 · PER-TICKET RESOLUTION
// ===========================================================================
s = S();
s.background = { color: C.cream };
L.title(s, "The mode is chosen per ticket, not per account.");
L.sub(s, "One global switch means the riskiest ticket in the backlog sets policy for every ticket.");

L.card(s, pres, 0.75, 2.32, 5.5, 2.35);
L.eyebrow(s, "WHAT GOES WRONG WITHOUT IT", 1.08, 2.6, 4.9, C.cloth);
s.addText("Teams pick manual, leave it there, and the autonomous path is never exercised at all. The feature ships and nobody turns it on.", {
  x: 1.08, y: 3.0, w: 4.85, h: 1.4, fontFace: F.body, fontSize: 13.5,
  color: C.ink, margin: 0, lineSpacingMultiple: 1.3,
});

L.eyebrow(s, "RESOLUTION ORDER — MOST SPECIFIC WINS", 6.85, 2.32, 5.7);
const chain = [
  ["WORK ITEM", "this one ticket", C.coral, C.card, 5.7],
  ["REPOSITORY", "this codebase", C.cloth, C.card, 5.1],
  ["ACCOUNT", "your default", C.kraft, C.ink, 4.5],
];
chain.forEach(([n, sub2, fill, fg, w], i) => {
  const y = 2.76 + i * 0.8;
  s.addShape(pres.ShapeType.roundRect, {
    x: 6.85, y, w, h: 0.64, fill: { color: fill }, rectRadius: 0.08,
  });
  s.addText(n, { x: 7.12, y, w: 2.4, h: 0.64, fontFace: F.body, fontSize: 12.5,
    bold: true, color: fg, valign: "middle", charSpacing: 1.4, margin: 0 });
  s.addText(sub2, { x: 9.4, y, w: w - 2.8, h: 0.64, fontFace: F.body, fontSize: 11.5,
    color: fg, valign: "middle", align: "right", margin: 0 });
});

const ex = [
  ["Bump a dependency", "Autonomous", C.coral],
  ["Rename a config key", "Autonomous", C.coral],
  ["Touch the auth path", "You", C.ink],
  ["Rotate encryption keys", "You", C.ink],
];
L.card(s, pres, 0.75, 4.88, 5.5, 1.45);
ex.forEach(([task, who, col], i) => {
  const y = 5.06 + (i % 2) * 0.58, x = 1.08 + Math.floor(i / 2) * 2.55;
  s.addText(task, { x, y, w: 1.62, h: 0.28, fontFace: F.body, fontSize: 10.5, color: C.muted, margin: 0 });
  s.addText(who, { x: x + 1.6, y, w: 0.9, h: 0.28, fontFace: F.body, fontSize: 10.5, bold: true, color: col, margin: 0 });
});

L.takeaway(s, "Autonomy you can grant one ticket at a time is autonomy teams actually use.", 6.52, { w: 11.9 });
s.addNotes("The mode resolves work item, then repo, then account default. Most specific wins. A dependency bump goes to the agent; the auth path stays with you.");

// ===========================================================================
// 7 · SAFETY RAILS
// ===========================================================================
s = S();
s.background = { color: C.cream };
L.title(s, "Four rails make “autonomous” a promise the system keeps.");
L.sub(s, "Each one exists because of a specific way the feature could fail quietly.");

const rails = [
  ["3", "Attempts, then it stops", "Three tries on a ticket. Then it hands the work back and announces it in Slack — a mode that degrades silently is worse than no mode."],
  ["0", "Merge capability", "The agent's entire contract is “open a pull request”. It has no merge path, and its token cannot modify CI configuration."],
  ["1", "Commit from you ends it", "Push to the branch yourself and autonomous mode ends for that ticket immediately. You took over."],
  ["3", "Open agent PRs, capped", "The approver is a real person — the risk is rubber-stamping, so throughput is capped rather than gated."],
];
rails.forEach(([n, head, body], i) => {
  const x = 0.75 + (i % 2) * 6.09, y = 2.32 + Math.floor(i / 2) * 2.0;
  L.card(s, pres, x, y, 5.82, 1.85);
  L.chip(s, pres, x + 0.32, y + 0.34, 0.62, n, C.coral, C.card, 20);
  s.addText(head, {
    x: x + 1.12, y: y + 0.34, w: 4.4, h: 0.34, fontFace: F.body, fontSize: 14.5,
    bold: true, color: C.ink, valign: "middle", margin: 0,
  });
  s.addText(body, {
    x: x + 1.12, y: y + 0.76, w: 4.42, h: 0.9, fontFace: F.body, fontSize: 11.5,
    color: C.muted, margin: 0, lineSpacingMultiple: 1.22,
  });
});
L.takeaway(s, "An agent that reads the ticket, Slack and email — then writes code — earns every one of these.", 6.5, { w: 11.9 });
s.addNotes("Bounded at three attempts. No merge capability at all. A human commit ends autonomous mode for that ticket. And a cap on concurrent agent PRs, because the real risk is not the absence of a human, it is rubber-stamping.");

// ===========================================================================
// 8 · ARCHITECTURE
// ===========================================================================
s = S();
s.background = { color: C.cream };
L.title(s, "One settings resolver decides every run. Nothing else may disagree.");
L.sub(s, "Webhook in, four loops running, eight integrations out — and the analysis never leaves the machine.");

const layers = [
  ["CLIENT", "React SPA · task board · pipeline view · settings", C.n1, C.ink],
  ["API", "FastAPI · 52 endpoints · identity from the JWT, never a parameter", C.n2, C.ink],
  ["ORCHESTRATION", "Settings resolver · analysis worker · merge sweeper · QA poller · time agent", C.coral, C.card],
  ["MODELS & DATA", "Local server for analysis · OpenCode's model for authoring · PostgreSQL", C.cloth, C.card],
];
layers.forEach(([name, detail, fill, fg], i) => {
  const y = 2.32 + i * 0.9;
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.75, y, w: 8.6, h: 0.76, fill: { color: fill }, rectRadius: 0.08,
  });
  s.addText(name, { x: 1.05, y, w: 2.2, h: 0.76, fontFace: F.body, fontSize: 11.5,
    bold: true, color: fg, valign: "middle", charSpacing: 1.4, margin: 0 });
  s.addText(detail, { x: 3.15, y, w: 6.05, h: 0.76, fontFace: F.body, fontSize: 11,
    color: fg, valign: "middle", margin: 0 });
  if (i < 3) {
    s.addShape(pres.ShapeType.line, {
      x: 5.05, y: y + 0.76, w: 0, h: 0.16, line: { color: C.n3, width: 1.25, endArrowType: "triangle" },
    });
  }
});

L.card(s, pres, 9.65, 2.32, 2.95, 3.46);
L.eyebrow(s, "CONNECTED", 9.95, 2.6, 2.4);
s.addText(
  ["GitHub", "Jira", "Linear", "Slack", "Gmail", "Calendar", "Google Docs", "Notion"]
    .map((t, i, a) => ({ text: t, options: { bullet: { code: "25CF" }, breakLine: i < a.length - 1 } })),
  { x: 10.0, y: 3.0, w: 2.4, h: 2.65, fontFace: F.body, fontSize: 11.5, color: C.ink, margin: 0, paraSpaceAfter: 4 }
);

L.takeaway(s, "Every model that reads your code automatically runs on the developer's own hardware.", 6.25, { w: 11.9 });
s.addNotes("A React front end over a FastAPI backend. One settings resolver decides what every run does, so the worker, the API and the UI preview cannot disagree. Four background loops. The security scan, the code review and the QA classifier are all loopback-bound to a local model server; only the authoring agent reaches out, and only when you hand it a ticket.");

// ===========================================================================
// 9 · BY THE NUMBERS
// ===========================================================================
s = S();
s.background = { color: C.cream };
L.title(s, "706 tests, and every one pins a behaviour we broke at least once.");
L.sub(s, "Test coverage by subsystem — the loops that reach other people carry the most.");

s.addChart(
  pres.ChartType.bar,
  [{
    name: "Tests",
    labels: ["Context & records", "Review & merge loop", "Task board & worklist",
             "Security & code review", "Integrations & auth", "Authoring & modes",
             "Scheduler & availability", "Worker & platform", "QA sign-off loop"],
    values: [114, 102, 100, 93, 90, 70, 56, 48, 33],
  }],
  L.chartBase({
    x: 0.75, y: 2.32, w: 7.7, h: 3.55,
    barDir: "bar",
    chartColors: [C.coral],
    dataLabelPosition: "outEnd",
    dataLabelColor: C.muted,
    catAxisLabelFontSize: 10,
    valAxisMinVal: 0, valAxisMaxVal: 130, valAxisMajorUnit: 25,
    barGapWidthPct: 42,
  })
);

const kpis = [
  ["44,685", "lines of\nproduction code"],
  ["49", "backend service\nmodules"],
  ["25", "schema\nmigrations"],
  ["20", "database\ntables"],
  ["52", "API\nendpoints"],
  ["4", "concurrent\nbackground loops"],
];
kpis.forEach(([v, k], i) => {
  const x = 8.75 + (i % 2) * 1.95, y = 2.32 + Math.floor(i / 2) * 1.22;
  L.card(s, pres, x, y, 1.82, 1.12, { flat: true });
  L.miniStat(s, x + 0.2, y + 0.05, 1.5, v, k);
});

L.takeaway(s, "Nothing here was scaffolded. Every subsystem was debugged into existence.", 6.35);
s.addNotes("706 tests across nine subsystems. The heaviest coverage sits on the loops that send messages to real people, because those are the ones where a bug is visible to somebody else's team.");

// ===========================================================================
// 10 · ENGINEERING RIGOUR
// ===========================================================================
s = S();
s.background = { color: C.cream };
L.title(s, "A quarter of the codebase is tests.");
L.sub(s, "And every invariant in the repository is written down beside the failure that produced it.");

s.addChart(
  pres.ChartType.doughnut,
  [{
    name: "Lines of code",
    labels: ["Services", "Tests", "Frontend", "Routers", "Models & schemas"],
    values: [18497, 11058, 9216, 3955, 1959],
  }],
  L.chartBase({
    x: 0.75, y: 2.32, w: 5.2, h: 3.6,
    chartColors: [C.coral, C.cloth, C.kraft, C.n2, C.n1],
    holeSize: 58,
    showLegend: true, legendPos: "b", legendColor: C.muted,
    legendFontFace: F.body, legendFontSize: 10.5,
    dataLabelPosition: "bestFit",
    dataLabelColor: C.card,
    dataLabelFontSize: 9.5,
    showPercent: true, showValue: false,
    valGridLine: { style: "none" },
  })
);

const rigour = [
  ["31", "invariants documented with the\nbug that caused each one"],
  ["9", "loops that swallow their own errors\nso one dead integration costs one integration"],
  ["4", "models read attacker-controlled text —\nnone of them has a single tool bound"],
];
rigour.forEach(([v, k], i) => {
  const y = 2.32 + i * 1.22;
  L.card(s, pres, 6.5, y, 6.1, 1.12);
  s.addText(v, {
    x: 6.8, y, w: 1.0, h: 1.12, fontFace: F.display, fontSize: 30, bold: true,
    color: C.coral, valign: "middle", align: "center", margin: 0,
  });
  s.addText(k, {
    x: 7.85, y, w: 4.5, h: 1.12, fontFace: F.body, fontSize: 11.5, color: C.ink,
    valign: "middle", margin: 0, lineSpacingMultiple: 1.22,
  });
});

L.takeaway(s, "Almost none of these bugs announced themselves — they all looked like success.", 6.35);
s.addNotes("A quarter of the codebase is tests. Every invariant is written down next to the failure that produced it, because the hardest bugs here all looked like success: a clean scan, a merged PR, a working link.");

// ===========================================================================
// 11 · TIME AGENT
// ===========================================================================
s = S();
s.background = { color: C.cream };
L.title(s, "In autonomous mode, your reviewers become the bottleneck.");
L.sub(s, "They are the only humans left in the loop — so Locus protects their time.");

L.card(s, pres, 0.75, 2.32, 5.82, 2.7);
s.addText("14:10 — someone messages you", {
  x: 1.08, y: 2.58, w: 5.2, h: 0.28, fontFace: F.body, fontSize: 11, color: C.muted, margin: 0 });
s.addText("You are in a meeting until 15:30.", {
  x: 1.08, y: 2.9, w: 5.2, h: 0.32, fontFace: F.body, fontSize: 14.5, bold: true, color: C.ink, margin: 0 });
s.addShape(pres.ShapeType.roundRect, {
  x: 1.08, y: 3.42, w: 5.15, h: 1.0, fill: { color: C.manilla }, rectRadius: 0.08 });
s.addText("“Nakul is booked until 15:30 IST.”", {
  x: 1.35, y: 3.42, w: 4.6, h: 1.0, fontFace: F.body, fontSize: 14.5, italic: true,
  color: C.ink, valign: "middle", margin: 0 });
s.addText("Status and end time only. There is no field on the type that could carry the meeting's subject.", {
  x: 1.08, y: 4.5, w: 5.15, h: 0.45, fontFace: F.body, fontSize: 10.5, color: C.muted,
  margin: 0, lineSpacingMultiple: 1.2 });

L.card(s, pres, 6.78, 2.32, 5.82, 2.7);
L.eyebrow(s, "IF IT ACTUALLY MATTERS", 7.11, 2.58, 5.2);
s.addText("Importance is decided before any model is asked:", {
  x: 7.11, y: 2.94, w: 5.2, h: 0.28, fontFace: F.body, fontSize: 11.5, color: C.ink, margin: 0 });
s.addText(
  [
    { text: "the sender is a reviewer mid-round", options: { bullet: { code: "25CF" }, breakLine: true } },
    { text: "the message names a ticket already blocked on you", options: { bullet: { code: "25CF" }, breakLine: true } },
    { text: "otherwise — a classifier with no tools bound", options: { bullet: { code: "25CF" } } },
  ],
  { x: 7.15, y: 3.3, w: 5.1, h: 1.15, fontFace: F.body, fontSize: 11.5, color: C.muted, margin: 0, paraSpaceAfter: 5 }
);
s.addText("Then it proposes times instead of deflecting, and the reschedule waits in the UI.", {
  x: 7.11, y: 4.5, w: 5.2, h: 0.48, fontFace: F.body, fontSize: 11.5, bold: true, color: C.ink,
  margin: 0, lineSpacingMultiple: 1.2 });

const guards = [
  ["Off by default", "it posts to real people"],
  ["1 reply per thread, per day", "a repeating bot gets muted"],
  ["An unreadable calendar reads “free”", "never “busy” — that makes you unreachable"],
];
guards.forEach(([h, d], i) => {
  const x = 0.75 + i * 4.07;
  L.card(s, pres, x, 5.35, 3.82, 1.1, { flat: true });
  s.addText(h, { x: x + 0.25, y: 5.5, w: 3.35, h: 0.3, fontFace: F.body, fontSize: 11.5, bold: true, color: C.coral, margin: 0 });
  s.addText(d, { x: x + 0.25, y: 5.8, w: 3.35, h: 0.42, fontFace: F.body, fontSize: 10.5, color: C.muted, margin: 0, lineSpacingMultiple: 1.15 });
});
s.addNotes("The time agent answers on your behalf when you are booked. Importance is decided deterministically first — a reviewer mid-round, or a ticket already blocked on you — and only unstructured messages reach a classifier, which has no tools bound.");

// ===========================================================================
// 12 · WHY THIS WINS
// ===========================================================================
s = S();
s.background = { color: C.cream };
L.title(s, "Everyone automates writing the diff. Nobody automates the work around it.");
L.sub(s, "Which is what makes the author swappable in the first place.");

const cols = ["Locus", "AI coding\nassistants", "CI review\nbots", "PM board\nautomation"];
const rows = [
  ["Writes the code",                       2, 2, 0, 0],
  ["Gathers Slack + Jira context first",    2, 1, 0, 0],
  ["Reviews against the requirement",       2, 0, 1, 0],
  ["Tracks the review round trip",          2, 0, 0, 0],
  ["Routes to QA and reads the verdict",    2, 0, 0, 0],
  ["Moves the card through all 8 stages",   2, 0, 0, 1],
  ["Analyses your code locally",            2, 0, 0, 0],
];
const gx = 6.05, gw = 1.62;
const rowY = (r) => 2.86 + r * 0.5;
cols.forEach((c, i) => {
  s.addText(c, {
    x: gx + i * gw, y: 1.98, w: gw, h: 0.62,
    fontFace: F.body, fontSize: 10.5, bold: i === 0,
    color: i === 0 ? C.coral : C.muted, align: "center", valign: "bottom", margin: 0,
    lineSpacingMultiple: 1.05,
  });
});
rows.forEach(([label, ...vals], r) => {
  const y = 2.78 + r * 0.5;
  if (r % 2 === 0) {
    s.addShape(pres.ShapeType.rect, { x: 0.75, y: y - 0.05, w: 11.85, h: 0.48, fill: { color: C.card }, line: { color: C.card, width: 0 } });
  }
  s.addText(label, {
    x: 0.95, y, w: 5.0, h: 0.38, fontFace: F.body, fontSize: 12, color: C.ink,
    valign: "middle", margin: 0,
  });
  vals.forEach((v, i) => {
    const glyph = v === 2 ? "●" : v === 1 ? "◐" : "○";
    const col = v === 2 ? C.coral : v === 1 ? C.kraft : C.n2;
    s.addText(glyph, {
      x: gx + i * gw, y, w: gw, h: 0.38, fontFace: F.body, fontSize: 15,
      color: col, align: "center", valign: "middle", margin: 0,
    });
  });
});
s.addText("●  full     ◐  partial     ○  none", {
  x: gx, y: 6.46, w: gw * 4, h: 0.3, fontFace: F.body, fontSize: 10,
  color: C.muted, align: "center", margin: 0,
});
L.takeaway(s, "Build the 80%. The author becomes a plug.", 6.4, { w: 5.6 });
s.addNotes("Every AI coding tool solves the same twenty percent: writing the diff. Locus builds the eighty percent around it — which is exactly what makes the author swappable, and why adding autonomous mode changed one setting instead of forking the product.");

// ===========================================================================
// 13 · CLOSING
// ===========================================================================
s = S();
s.background = { color: C.dark };
L.eyebrow(s, "WHAT WE BUILT", 0.75, 1.55, 6.0, C.kraft);
s.addText("A ticket goes in.\nA signed-off change comes out.", {
  x: 0.7, y: 1.9, w: 8.0, h: 1.7, fontFace: F.display, fontSize: 34, bold: true,
  color: C.inkOnDk, margin: 0, valign: "middle", lineSpacingMultiple: 1.15,
});
s.addText("You choose, per ticket, whether you write the code or Locus does. The review, the testing sign-off and the record are the same either way — and every model that reads your code runs on your own hardware.", {
  x: 0.75, y: 3.95, w: 7.3, h: 1.2, fontFace: F.body, fontSize: 15, color: C.mutedDk,
  margin: 0, lineSpacingMultiple: 1.3,
});

const close = [["706", "tests passing"], ["9", "steps automated"], ["12", "min saved per\nreview round*"], ["0", "cloud calls to\nreview your code"]];
close.forEach(([v, k], i) => {
  L.stat(s, 0.78 + i * 1.85, 5.3, 1.7, v, k, { dark: true, size: 30 });
});
s.addText("* modelled from the coordination steps removed, not measured in production", {
  x: 0.78, y: 6.72, w: 7.5, h: 0.28, fontFace: F.body, fontSize: 9,
  italic: true, color: C.muted, margin: 0,
});

L.darkCard(s, pres, 8.85, 1.95, 3.73, 4.2, C.coral);
L.eyebrow(s, "NEXT", 9.2, 2.28, 3.1, C.coral);
s.addText(
  [
    { text: "Multi-tenant: answer availability for a whole team, not one account", options: { bullet: { code: "25CF" }, breakLine: true } },
    { text: "Pluggable authoring drivers behind the same contract", options: { bullet: { code: "25CF" }, breakLine: true } },
    { text: "Measure the round-trip saving against real teams", options: { bullet: { code: "25CF" }, breakLine: true } },
    { text: "Row locking, so the loops run multi-instance", options: { bullet: { code: "25CF" } } },
  ],
  { x: 9.22, y: 2.72, w: 3.05, h: 3.1, fontFace: F.body, fontSize: 11.5,
    color: C.mutedDk, margin: 0, paraSpaceAfter: 10, lineSpacingMultiple: 1.2 }
);
s.addNotes("A ticket goes in and a signed-off change comes out. You pick per ticket whether you write the code or Locus does. Thank you.");

pres.writeFile({ fileName: "Locus-hackathon.pptx" }).then(() => console.log("wrote Locus-hackathon.pptx"));
