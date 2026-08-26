# Locus — 5-minute pitch video script

Deck: `Locus-pitch.pptx` (9 slides). Every line below is also in the slide's
speaker notes, so you can read from Presenter View.

**Split:** 2:45 on slides, 2:00 on the demo, 0:15 to close.
Speak at a normal pace — roughly 150 words a minute. Don't rush the two-mode slide;
it's the one thing the viewer must come away with.

---

## Before you hit record

Have this ready, or the demo falls flat:

- Backend running (`uv run uvicorn main:app --reload`) with a model loaded, or chat returns 503
- Frontend running (`npm run dev`)
- **At least one real pull request already analyzed**, ideally one that went the whole way:
  reviewed → changes requested → approved → merged → QA replied. An empty board is
  the worst thing you can put on screen.
- The task detail panel open in a second tab, so you're not waiting on a load mid-sentence
- The Google Doc that Locus wrote, open in a third tab
- Browser zoom at ~110% so text is readable in a compressed video
- Notifications off

---

## Slides — 0:00 to 2:45

### Slide 1 · Title — 20 seconds

> Hi, I'm Nakul. This is Locus — an AI teammate that takes a ticket all the way from
> the moment it's assigned to you, to the moment your testing team signs it off.
>
> It runs in two modes, and the whole design bet is this: whether a human or an agent
> writes the code, everything behind it is the same pipeline.

### Slide 2 · The problem — 30 seconds

> Here's the problem it solves. A task's information is scattered across four tools and
> joined together only inside somebody's head. The requirement was argued out in Slack.
> The acceptance criteria are in Jira. The code is in GitHub. The sign-off arrives by email.
>
> So the senior dev approving the change has none of it in front of them.
>
> And the half *after* the merge is entirely manual — briefing the testers, chasing a reply,
> reopening the ticket when they say it's broken. GitHub's own automation has exactly one
> useful trigger, an item closing. So a ticket sits in "Todo" through the branch, the review
> and the whole QA thread, and then jumps straight to "Done".

### Slide 3 · The pipeline — 25 seconds

> Locus automates all of it. Ten steps.
>
> It gathers the context. Scans the diff for vulnerabilities. Reviews the code *against the
> requirement it just gathered* — so a change that ignores what the team agreed gets flagged,
> instead of passing silently. It posts the findings, tracks the review round trip that GitHub
> doesn't record anywhere, merges when the gate passes, briefs the testers, reads their reply,
> moves the board card, and keeps one written record per work item.

### Slide 4 · Two modes — 35 seconds ← the one that matters

> And here are the two modes. They differ in exactly one place: who writes the code.
>
> **Assisted.** You write the code. Locus does the other ten steps around you.
>
> **Autonomous.** You hand Locus the ticket. It reads the requirement, makes the change,
> and opens the pull request — and then the exact same ten steps run behind it.
>
> Notice what doesn't change. Your senior dev still reviews it. Your tester still signs it off.
> The author is the only thing that's different.

*(Pause for a beat after that last line. It's the thesis.)*

### Slide 5 · Per-ticket — 20 seconds

> Crucially, you pick the mode per ticket — not per account.
>
> As one global switch, the riskiest ticket in your backlog ends up setting policy for every
> ticket. So teams leave it off forever and the autonomous path never gets used.
>
> Here it resolves work item, then repo, then your account default. Most specific wins.
> A version bump goes to the agent. A change touching authentication stays with you.

### Slide 6 · Safety rails — 25 seconds

> Four things make "autonomous" a promise the system can actually keep.
>
> It's bounded — three attempts on a ticket, then it hands the work back and says so in Slack.
> If you push a commit yourself, autonomous mode ends for that ticket immediately, because an
> agent overwriting your work is the worst thing it could do quietly. It opens pull requests
> and has no merge capability at all. And there's a cap on how many agent-written PRs can be
> open at once — because the real risk isn't "no human in the loop", the approver is a real
> person. It's rubber-stamping.

### Slide 7 · Time agent — 20 seconds

> One last piece. In autonomous mode, your reviewer and your tester are the only humans left —
> which makes *their* time the constraint.
>
> So a time agent answers on your behalf when you're booked. And if the message actually
> matters — a reviewer mid-round, or a ticket already blocked on you — it proposes times
> instead of just deflecting. It says your status and when you're free. Never what the
> meeting is about.

### Slide 8 · Where it stands — 15 seconds

> To be straight about where this stands. The pipeline is built and running — 651 passing
> tests, 49 service modules, 21 migrations, eight integrations, and inference entirely local,
> so no diff and no Slack thread ever leaves the machine.
>
> The two-mode layer on top is designed and specced against that running architecture. That's
> what I'd build next.

### Slide 9 · Transition — 5 seconds

> Let me show you what's running today.

---

## Demo — 2:45 to 4:45

Switch to the app. Keep the cursor moving deliberately; don't hunt for things.

### Beat 1 · The board — 25 seconds

**Screen:** `/tasks`, Board tab

> This is the board. Every ticket assigned to me, pulled from GitHub and Jira using the
> credentials I connected — there's no login or account ID to configure anywhere.
>
> It's split into "Needs you" and everything else, and that ordering is decided server-side,
> so the API and the UI can't disagree about what's urgent. A ticket with no pull request yet
> is real work, and it shows up here — it's invisible to every PR-shaped view.

### Beat 2 · One task's pipeline — 30 seconds

**Screen:** click a task → detail panel, stepper visible

> Open one and you get the whole pipeline. Assigned, branch created, senior dev review,
> changes requested, approved, merged, with the testing team, signed off.
>
> Every stage is shown including the ones it hasn't reached, so the card tells you what
> happens next — not just what's happened. And this stage isn't stored anywhere; it's derived
> live from the review state, the QA thread and the job status, because a stored one goes
> stale exactly when someone's watching.

### Beat 3 · What it gathered — 30 seconds

**Screen:** the analysis view — context, security findings, review findings

> Here's what it actually gathered for this change. The ticket. The Slack discussion it found
> about the same work. The linked issues. Any spec documents pinned to the repo.
>
> Then two separate passes. A security scan — Semgrep and Gitleaks are deterministic, so
> those get reported as confirmed; the model pass is reported as unverified, and neither is
> ever auto-merged. And a code review, which gets all that context, so it can tell me the diff
> ignores something the team agreed to.

### Beat 4 · The record — 25 seconds

**Screen:** the messages/timeline tab → then the Google Doc tab

> And every message is recorded, not summarized. What it searched for, what came back, what
> it actually sent. Including searches that found nothing — because a search that found
> nothing and one that never ran look identical everywhere else, and only one of those means
> the context is missing.
>
> All of it lands in one Google Doc per work item, rewritten in place. This is what the senior
> dev and the testing team actually read.

### Beat 5 · The controls — 10 seconds

**Screen:** `/tasks` → Settings tab

> And the settings that decide all of it. Auto-merge is off by default — it's the only path
> that writes to a default branch. This is where the mode toggle from the slides would live.

---

## Close — 4:45 to 5:00

**Screen:** back to Slide 4, or your face

> So: the pipeline around the code is built and tested. The two-mode layer on top of it is
> designed. And the reason I think that ordering is right — AI coding tools all solve the same
> twenty percent. Locus builds the eighty percent around it, which is what makes the coding
> step swappable in the first place.
>
> Thanks for watching.

---

## If you're running long

Cut in this order — each is self-contained:

1. **Slide 7** (time agent), 20s — the least load-bearing idea
2. **Beat 5** (settings), 10s
3. **Slide 5** (per-ticket), 20s — but only if you must; it's the strongest answer to
   "why would anyone turn this on"

Never cut Slide 4 or Beat 3. Those are the pitch.

## If you're running short

Add to Beat 3: open the pull request on GitHub and show the comment Locus posted — point out
it edits its own previous comment instead of adding a new one on every push.
