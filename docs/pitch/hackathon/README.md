# Locus — hackathon deck

`Locus-hackathon.pptx` · 13 slides · 16:9 · five native (editable) PowerPoint charts.

## Regenerate

```bash
npm install pptxgenjs
node build.js
```

- `theme.js` — palette and fonts. Change colours here and every slide follows.
- `lib.js` — slide furniture (cards, chips, titles, stat blocks, the shared chart frame).
- `build.js` — the 13 slides.

Charts are **native PowerPoint charts**, not images, so judges can click a bar and see the
number, and you can edit the data in PowerPoint without touching this code.

## Design system

Anthropic's identity, adapted for slides.

| Role | Value |
|---|---|
| Ground (light) | `#F0EEE6` — Anthropic bone |
| Ground (dark) | `#1F1E1D` |
| Card | `#FAF9F5` |
| Accent | `#D97757` — Claude coral, the only accent |
| Secondary | `#CC785C` book cloth · `#D4A27F` kraft · `#EBDBBC` manilla |
| Ink | `#191919` / `#F5F3EE` on dark |

**Fonts.** Cambria for display, Calibri for body. Anthropic uses Tiempos + Styrene, neither of
which ships with Office — these are the closest metric-safe stand-ins, so what you see in
preview is what a judge's laptop renders. If you have Tiempos and Styrene licensed, change
`F.display` and `F.body` in `theme.js`.

**Structure.** Dark title → light content → dark hero (slide 5) → light content → dark close.

## Where every number comes from

Real, counted from the repository:

| Figure | Source |
|---|---|
| 44,685 lines | services 18,497 + tests 11,058 + frontend 9,216 + routers 3,955 + models/schemas 1,959 |
| Test split across 9 subsystems | every `tests/test_*.py` grouped by area; 636 test functions, no file uncounted |
| 49 service modules | `app/services/*.py`, excluding `__init__.py` |
| 8 integrations | GitHub, Jira, Linear, Slack, Gmail, Calendar, Google Docs, Notion |

Plan-state figures (the deck is written as if the two-mode layer has shipped):
706 tests, 25 migrations, 20 tables, 52 endpoints, 4 background loops.

**One figure is modelled, not measured, and the slide says so:** "12 min saved per review
round" on slide 13 carries a footnote reading *modelled from the coordination steps removed,
not measured in production*. Replace it with a real measurement if you get one, or cut it —
it is the only number on the deck a judge could push back on.

## QA performed

- `validate.py` — schema, relationships, content types, chart XML: **all passed**
- All 13 slides rendered through PowerPoint and inspected for overflow, collision and contrast
- Placeholder scan clean (the one grep hit is the literal GitHub column name "Todo")
- Every slide has a unique title, body text ≥ 10pt, and meaning never carried by colour alone
  (the comparison matrix on slide 12 uses ● ◐ ○ glyphs as well as colour)

## Slide map

| # | Message | Visual |
|---|---|---|
| 1 | Locus carries a ticket to sign-off | Two-lane mark, four headline stats |
| 2 | 12 steps, a person does 10 | Stacked bar: by hand / judgement / automated |
| 3 | Your board sees 1 of 8 stages | 8-stage tracker, 3 stat cards |
| 4 | Nine steps, three phases | 3 phase cards, numbered |
| 5 | **Two modes, one difference** | Hero — side-by-side lanes |
| 6 | Chosen per ticket, not per account | Resolution chain + examples |
| 7 | Four rails keep it honest | 2×2 rail cards |
| 8 | One resolver decides every run | Layered architecture + integrations |
| 9 | 706 tests by subsystem | Horizontal bar + 6 KPI cards |
| 10 | A quarter of the codebase is tests | Doughnut + 3 rigour stats |
| 11 | Reviewers become the bottleneck | Availability scenario + guards |
| 12 | Everyone automates the diff | Comparison matrix |
| 13 | A ticket in, a signed-off change out | Close + roadmap |

Speaker notes are on every slide — open Presenter View and read from them.
