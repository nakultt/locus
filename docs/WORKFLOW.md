# Workflow

How a change moves through Locus, from a pull request opening to a tester
signing it off.

These diagrams render natively on GitHub. They describe what is built, not what
is planned — see [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) for the
latter.

---

## The full lifecycle

```mermaid
flowchart TD
    A([Dev opens PR]) --> WH{{"POST /webhooks/github<br/>HMAC-SHA256 verified"}}
    WH --> JOB[(PRJob queued<br/>202 returned in &lt;10s)]
    JOB --> W[worker_loop]

    W --> CTX

    subgraph CTX ["Context gathering"]
        direction TB
        C1[Extract ticket keys<br/>title · branch · body · commits]
        C1 --> C2[Fetch Jira/Linear tickets<br/>topic search if no key]
        C2 --> C3["Fetch GitHub issues<br/>closes + mentions, with bodies"]
        C3 --> C4{Searched this<br/>ticket before?}
        C4 -->|yes| C5["Reuse stored matches<br/>+ search only since<br/>the watermark"]
        C4 -->|no| C6[Full search.messages<br/>record queries + matches]
        C5 --> C7[Pinned Google Docs]
        C6 --> C7
    end

    CTX --> SCAN

    subgraph SCAN ["Always re-derived from the diff"]
        direction TB
        S1[Semgrep + Gitleaks] --> S2[CONFIRMED findings]
        S3[LLM security pass] --> S4[UNVERIFIED findings]
        S5["run_code_review<br/>fed the accumulated brief"] --> S6[p1 · p2 · p3]
    end

    SCAN --> OUT[Upsert PR comment<br/>+ Slack summary]
    OUT --> LOG[(communication_events<br/>keyed by ticket)]
    OUT --> RQ([Review requested])

    RQ --> LOOP

    subgraph LOOP ["Senior dev loop"]
        direction TB
        L1[awaiting_review] --> L2{Verdict}
        L2 -->|changes_requested| L3[Summarize asks<br/>notify author]
        L3 --> L4[Dev pushes]
        L4 --> L5["round += 1<br/>delta vs reviewed SHA"]
        L5 --> L1
        L2 -->|commented| L6[Recorded<br/>state unchanged]
        L6 --> L1
    end

    LOOP -->|approved| GATE{Merge gate}
    GATE -->|held| SWEEP[Sweeper retries<br/>every 60s, up to 24h]
    SWEEP --> GATE
    GATE -->|passes| MERGE[PUT /pulls/N/merge]

    MERGE --> CLOSED{{"GitHub fires<br/>closed + merged=true"}}
    CLOSED --> POST

    subgraph POST ["Post-merge"]
        direction TB
        P1[Jira → Done<br/>forward-only] --> P2{close_on_qa<br/>_signoff?}
        P2 -->|off, default| P2a["Close issues now<br/>closes only, not mentions"]
        P2 -->|on| P2b[Hold issues open<br/>until a tester confirms]
        P2a --> P3[QA email + Slack thread<br/>store correlation keys]
        P2b --> P3
    end

    POST --> QA

    subgraph QA ["Testing loop"]
        direction TB
        Q1{Tester replies} -->|Slack thread_ts| Q2[Classifier<br/>no tools bound]
        Q1 -->|Email In-Reply-To<br/>polled every 3 min| Q2
        Q2 -->|broken| Q3[Reopen Jira + issues]
        Q2 -->|works| Q4([Resolved · close held issues])
        Q2 -->|unclear| Q5[Ping author<br/>change nothing]
        Q2 -->|not_feedback| Q6[Ignore]
    end

    Q3 --> A
    LOG -.-> WL[Worklist<br/>“Needs you”]
    LOOP -.-> WL
    QA -.-> WL
```

Slack is not re-searched from scratch on every run. `comms_log.cached_search`
returns the stored matches plus a watermark, and only messages newer than it are
fetched — so a discussion that happened between two runs is picked up, without
paying for the whole search again. There is no expiry: discussion that was
relevant an hour ago is still relevant now.

The merge is performed through GitHub's API rather than by calling the
post-merge code directly. GitHub then fires the same `closed` + `merged=true`
webhook a human merge would, so there is one post-merge path rather than two to
keep in sync.

---

## Review states

```mermaid
stateDiagram-v2
    [*] --> awaiting_review: review requested

    awaiting_review --> changes_requested: reviewer requests changes
    awaiting_review --> approved: reviewer approves
    awaiting_review --> awaiting_review: commented (no verdict)

    changes_requested --> awaiting_review: author pushes<br/>round += 1
    changes_requested --> approved: reviewer approves
    changes_requested --> changes_requested: commented

    approved --> awaiting_review: changes requested again
    approved --> approved: review requested<br/>(never un-approves)
    approved --> merged: gate passes

    merged --> [*]

    note right of changes_requested
        Not terminal.
        Where the loop spends
        most of its time.
    end note

    note right of awaiting_review
        Only a push FOLLOWING
        changes_requested opens
        a new round.
    end note
```

Three rules are deliberate:

- **Only a push after a changes-requested review opens a round.** A push to a
  PR nobody has reviewed is ordinary development; counting it would turn the
  round number into a commit counter.
- **A `commented` review moves nothing.** It carries no verdict, and letting
  drive-by remarks bump the count would make a converging review look stuck.
- **A review request never un-approves.** Asking for a second opinion is
  normal; silently dropping the approval would make a merge-ready PR look
  blocked.

---

## The merge gate

Auto-merge is **off by default**. It is the only path that writes to a default
branch with no human in the loop.

```mermaid
flowchart TD
    A([Approval lands]) --> B{auto_merge<br/>enabled?}
    B -->|no, default| Z([Human merges])
    B -->|yes| C{state ==<br/>approved?}

    C -->|no| H
    C -->|yes| D{CI green?}
    D -->|failing| H
    D -->|pending| H
    D -->|"no CI configured"| E
    D -->|green| E{mergeable?}

    E -->|"false — conflict"| H
    E -->|"null — unknown"| H
    E -->|true| F{Confirmed<br/>security finding?}

    F -->|yes| H
    F -->|no| G{P1 review<br/>finding?}

    G -->|yes| H
    G -->|no| M[Merge via API]

    H[Hold · report every<br/>blocker at once] --> R[Sweeper<br/>every 60s / 24h]
    R --> C

    M --> W{{closed + merged=true}}
    W --> P([Post-merge actions])

    style M fill:#22c55e,color:#fff
    style H fill:#f59e0b,color:#fff
```

An approval means "the change is right" — not that CI passed. The reviewer may
not have looked, and on a fast-moving PR the checks may not have finished when
they clicked, so every gate is checked independently of the approval.

**Unverified findings and p2/p3 deliberately do not block.** Blocking on a
model's opinion would make the feature unusable, and would hand an unverified
finding the authority the confirmed/unverified split exists to deny it.

**The gate is retried, not evaluated once.** GitHub computes mergeability
lazily: the first read after any change returns `null`, and the approval
webhook fires within a second of the click. Without the sweeper, the common
case is an approved PR that never merges. Held retries stay silent — the reason
was reported when the approval landed.

---

## What caches and what does not

```mermaid
flowchart LR
    subgraph STABLE ["Caches — keyed by ticket"]
        direction TB
        A1[Slack discussion]
        A2[Issue bodies]
        A3[Jira summary]
        A4[Review history]
    end

    subgraph VOLATILE ["Never caches — re-derived every round"]
        direction TB
        B1[Diff]
        B2[Semgrep / Gitleaks]
        B3[Code review]
    end

    STABLE --> BR["context_brief.build()<br/>rendered on demand"]
    VOLATILE --> BR

    BR --> U1[Code reviewer]
    BR --> U2[QA brief]
    BR --> U3[Asks summarizer]

    T1[(LOC-42)] -.spans.-> PR1[PR #42<br/>feature]
    T1 -.spans.-> PR2[PR #57<br/>fix after QA]
    PR1 --> STABLE
    PR2 --> STABLE

    style VOLATILE fill:#fee2e2,stroke:#ef4444
    style STABLE fill:#dcfce7,stroke:#22c55e
```

PR #57 inherits PR #42's discussion — including the QA rejection that caused it
to exist — and shares its **Google Doc**, since the report belongs to the work
item rather than to any one pull request. What it never inherits is **findings**. Reusing an analysis across a round would
report round one's scan against round two's code, so a vulnerability introduced
while fixing something else would pass unreported.

`context_brief.build()` takes the current run's analysis as an argument and
never reads a stored one, which is what enforces that split.

---

## Inbound correlation

Nothing is captured on receipt. Each path establishes relevance
deterministically before storing anything:

| Path | Transport | How relevance is proven |
|---|---|---|
| Slack search results | `search.messages`, incremental from a watermark | The query contained the ticket key or PR number |
| Slack QA reply | Events API webhook, sub-second | `thread_ts` matches a thread Locus posted |
| Email QA reply | Gmail polled every 3 min | `In-Reply-To` matches a `Message-ID` Locus set when sending |
| Review verdict | `pull_request_review` webhook | GitHub supplies the PR directly |

Gmail is polled rather than pushed because its `users.watch` registration
expires every seven days and needs a renewal job regardless — at which point
polling is the simpler mechanism.

Threads stop being watched after 14 days: a reply weeks after a merge is almost
certainly about something else.
