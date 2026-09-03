"use client";

import { ArrowDownLeft, ArrowUpRight, ExternalLink, Search } from "lucide-react";
import type { CommunicationEvent, WorklistItem } from "@/lib/api";
import { Badge, Dot } from "@/components/ui/badge";
import {
  CHANNEL_LABEL,
  KIND,
  LOOP,
  ageLabel,
  timeOf,
} from "./shared";
import { cn } from "@/lib/utils";

/**
 * One message, shown with its actual text.
 *
 * The body is rendered verbatim in a monospace block rather than summarised.
 * A summary answers the easy questions; "what exactly did the bot say to my
 * team" is the one people actually ask, and only the real text answers it.
 *
 * The direction is an icon in a tinted well rather than an arrow glyph in a
 * span — searched, sent and received are the three things a reader sorts this
 * log by, and at a glance colour and shape do that faster than ↗ and ↙, which
 * are easy to confuse and were rendering at 10px.
 */

const DIRECTION = {
  searched: { icon: Search, well: "bg-surface-2 text-subtle", verb: "Searched" },
  sent: { icon: ArrowUpRight, well: "bg-info-soft text-info", verb: "Sent via" },
  received: {
    icon: ArrowDownLeft,
    well: "bg-success-soft text-success",
    verb: "From",
  },
} as const;

export function MessageRow({ event }: { event: CommunicationEvent }) {
  const dir = DIRECTION[event.direction];
  const Icon = dir.icon;
  const loop = LOOP[event.loop];

  return (
    <div className="flex gap-3">
      <span
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-pill",
          dir.well
        )}
        aria-hidden
      >
        <Icon className="size-3.5" />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Badge tone={loop.tone}>{loop.label}</Badge>
          <span className="text-sm font-medium text-ink">
            {dir.verb} {CHANNEL_LABEL[event.channel]}
          </span>
          {event.participant && (
            <span className="text-sm text-muted">
              {event.direction === "sent" ? "to " : ""}
              {event.participant}
            </span>
          )}
          {event.target && event.target !== event.participant && (
            <Badge tone="neutral">{event.target}</Badge>
          )}
          {event.outcome && <Badge tone="neutral">{event.outcome}</Badge>}

          {/* Reused context, not discussion about this PR. Labelled rather
              than hidden: the reviewer was given it, so the timeline would be
              misleading without it — and misleading with it, unmarked. */}
          {event.inherited && (
            <Badge
              tone="warning"
              title="Found earlier on this work item and reused as context for this pull request"
            >
              earlier on this task
            </Badge>
          )}

          {/* A message nobody received looks exactly like one nobody answered,
              so a failed send says so. */}
          {!event.succeeded && <Badge tone="danger">not delivered</Badge>}

          <span className="ml-auto shrink-0 text-xs text-subtle">
            {timeOf(event.created_at)}
          </span>
        </div>

        {event.query && (
          <p className="mt-1.5 font-mono text-xs text-muted">
            <span className="text-subtle">query </span>
            {event.query}
          </p>
        )}

        {event.subject && (
          <p className="mt-1.5 text-sm font-medium text-ink">{event.subject}</p>
        )}

        {event.body && (
          <pre className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-line bg-surface-2 p-3 font-mono text-xs leading-relaxed text-ink">
            {event.body}
          </pre>
        )}

        {event.permalink && (
          <a
            href={event.permalink}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-flex items-center gap-1.5 text-xs text-accent-strong underline-offset-2 hover:underline"
          >
            Open in {CHANNEL_LABEL[event.channel]}
            <ExternalLink className="size-3" aria-hidden />
          </a>
        )}
      </div>
    </div>
  );
}

/** One thing waiting on you, with the words that prompted it. */
export function WorklistItemRow({ item }: { item: WorklistItem }) {
  const kind = KIND[item.kind];

  return (
    <div className="flex gap-3">
      <span className="mt-1.5">
        <Dot tone={kind.tone} />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="text-sm font-medium text-ink">{item.headline}</span>
          <span className="font-mono text-xs text-muted">
            {item.repo}#{item.pr_number}
          </span>
          {item.round_number > 1 && (
            <Badge tone="neutral">round {item.round_number}</Badge>
          )}
          <span className="tabular ml-auto shrink-0 text-xs text-subtle">
            {ageLabel(item.age_hours)}
          </span>
        </div>

        {item.detail.length > 0 && (
          <ul className="mt-1.5 space-y-1">
            {item.detail.map((d, i) => (
              <li key={i} className="flex gap-2 text-sm text-muted">
                <span className="text-subtle" aria-hidden>
                  •
                </span>
                {d}
              </li>
            ))}
          </ul>
        )}

        {/* Their own words, which is what someone acts on. */}
        {item.quotes.map((q, i) => (
          <pre
            key={i}
            className="mt-2 max-h-32 overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-line bg-surface p-3 font-mono text-xs leading-relaxed text-ink"
          >
            {q}
          </pre>
        ))}

        {item.pr_url && (
          <a
            href={item.pr_url}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-flex items-center gap-1.5 text-xs text-accent-strong underline-offset-2 hover:underline"
          >
            Open pull request
            <ExternalLink className="size-3" aria-hidden />
          </a>
        )}
      </div>
    </div>
  );
}
