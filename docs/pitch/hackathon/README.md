# Locus — hackathon deck

`Locus-hackathon.pptx` · 15 slides · 16:9 · three native (editable) PowerPoint charts.

> Earlier revisions of this file claimed five charts. There have only ever been three —
> the bar on slide 9, the doughnut on slide 10, and the stacked bar on slide 2.

## Regenerate

```bash
cd src
npm install pptxgenjs
node build.js
```

`src/package.json` pins this folder to CommonJS. The repository root sets
`"type": "module"`, which makes every `.js` here an ES module and breaks
`require()` — that file scopes the deck build without touching the app.

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

Real, counted from the repository on 28 Aug 2026:

| Figure | Source |
|---|---|
| 53,691 lines | services 22,082 + tests 14,249 + frontend 9,983 + routers 4,872 + models/schemas 2,505 |
| 859 tests | `pytest --collect-only`; 832 test functions across 51 files, no file uncounted |
| Test split across 9 subsystems | every `tests/test_*.py` grouped by area |
| 57 service modules | `app/services/*.py`, excluding `__init__.py` |
| 25 migrations · 21 tables · 59 endpoints · 4 loops | migrations dir, SQLAlchemy metadata, `@router.*` decorators |
| 8 integrations | GitHub, Jira, Linear, Slack, Gmail, Calendar, Google Docs, Notion |

**The two-mode layer is no longer plan-state.** Slides 11 and 12 describe a run that
actually happened against live GitHub, Slack, Gmail and Google Docs: a ticket was
assigned, the agent wrote the code, a human approved it, it merged, the testing team
was briefed, a tester replied, and the ticket closed on that reply. Slide 11's
reopen-after-merge detail is from that run's issue timeline.

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
| 9 | 859 tests by subsystem | Horizontal bar + 6 KPI cards |
| 10 | A quarter of the codebase is tests | Doughnut + 3 rigour stats |
| 11 | **It has now run on live services** | Six-step run timeline + the reopen detail |
| 12 | **Live running found six defects tests could not** | 2x3 defect cards |
| 13 | Reviewers become the bottleneck | Availability scenario + guards |
| 14 | Everyone automates the diff | Comparison matrix |
| 15 | A ticket in, a signed-off change out | Close + roadmap |

Speaker notes are on every slide — open Presenter View and read from them.

## Asset staleness

`assets/Slide1–13.PNG` were exported from the 26 Aug build and are **stale**: the deck is
now 15 slides, and slides 11–15 no longer correspond to those files. They were exported by
hand from PowerPoint — no renderer in this repo produces them — so re-export after opening
the deck, or delete them rather than leaving a set that silently disagrees with the file.
