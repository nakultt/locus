import { ExternalLink } from "lucide-react";
import type { CommunicationEvent, WorklistItem } from "@/lib/api";
import {
  CHANNEL_LABEL,
  DIRECTION_GLYPH,
  KIND_STYLE,
  LOOP_STYLE,
  ageLabel,
  timeOf,
} from "./shared";

/**
 * One message, shown with its actual text.
 *
 * The body is rendered verbatim in a monospace block rather than summarized.
 * A summary answers the easy questions; "what exactly did the bot say to my
 * team" is the one people actually ask, and only the real text answers it.
 */
export const MessageRow = ({ event }: { event: CommunicationEvent }) => {
  const dir = DIRECTION_GLYPH[event.direction];
  const loop = LOOP_STYLE[event.loop];

  return (
    <div className="flex gap-2.5">
      <span className={`mt-0.5 shrink-0 text-sm ${dir.tone}`} title={event.direction}>
        {dir.glyph}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className={`rounded px-1.5 py-0.5 text-[10px] ${loop.className}`}>
            {loop.label}
          </span>
          <span className="text-[11px] font-medium text-foreground">
            {event.direction === "searched"
              ? `Searched ${CHANNEL_LABEL[event.channel]}`
              : event.direction === "sent"
                ? `Sent via ${CHANNEL_LABEL[event.channel]}`
                : `From ${CHANNEL_LABEL[event.channel]}`}
          </span>
          {event.participant && (
            <span className="text-[11px] text-muted-foreground">
              {event.direction === "sent" ? "to" : ""} {event.participant}
            </span>
          )}
          {event.target && event.target !== event.participant && (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {event.target}
            </span>
          )}
          {event.outcome && (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {event.outcome}
            </span>
          )}
          {/* Reused context, not discussion about this PR. Labelled rather
              than hidden: the reviewer was given it, so the timeline would be
              misleading without it — and misleading with it, unmarked. */}
          {event.inherited && (
            <span
              className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-700 dark:text-amber-400"
              title="Found earlier on this work item and reused as context for this pull request"
            >
              earlier on this task
            </span>
          )}
          {!event.succeeded && (
            <span className="rounded bg-red-500/10 px-1.5 py-0.5 text-[10px] text-red-600 dark:text-red-400">
              not delivered
            </span>
          )}
          <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
            {timeOf(event.created_at)}
          </span>
        </div>

        {event.query && (
          <p className="mt-1 font-mono text-[11px] text-muted-foreground">
            query: {event.query}
          </p>
        )}

        {event.subject && (
          <p className="mt-1 text-[11px] font-medium text-foreground">{event.subject}</p>
        )}

        {event.body && (
          <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted/50 p-2 font-mono text-[11px] leading-relaxed text-foreground">
            {event.body}
          </pre>
        )}

        {event.permalink && (
          <a
            href={event.permalink}
            target="_blank"
            rel="noreferrer"
            className="mt-1 inline-flex items-center gap-1 text-[11px] text-blue-600 hover:underline dark:text-blue-400"
          >
            Open in {CHANNEL_LABEL[event.channel]} <ExternalLink size={10} />
          </a>
        )}
      </div>
    </div>
  );
};

/** One thing waiting on you, with the words that prompted it. */
export const WorklistItemRow = ({ item }: { item: WorklistItem }) => {
  const style = KIND_STYLE[item.kind];

  return (
    <div className="flex gap-2">
      <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${style.dot}`} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className={`text-xs font-medium ${style.className}`}>
            {item.headline}
          </span>
          <span className="text-[11px] text-muted-foreground">
            {item.repo}#{item.pr_number}
          </span>
          {item.round_number > 1 && (
            <span className="rounded bg-muted px-1.5 text-[10px] text-muted-foreground">
              round {item.round_number}
            </span>
          )}
          <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
            {ageLabel(item.age_hours)}
          </span>
        </div>

        {/* Checklist for scanning. */}
        {item.detail.length > 0 && (
          <ul className="mt-1 space-y-0.5">
            {item.detail.map((d, i) => (
              <li key={i} className="text-[11px] text-muted-foreground">
                • {d}
              </li>
            ))}
          </ul>
        )}

        {/* Their own words, which is what someone acts on. */}
        {item.quotes.map((q, i) => (
          <pre
            key={i}
            className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap break-words rounded bg-muted/50 p-1.5 font-mono text-[11px] text-foreground"
          >
            {q}
          </pre>
        ))}

        {item.pr_url && (
          <a
            href={item.pr_url}
            target="_blank"
            rel="noreferrer"
            className="mt-1 inline-flex items-center gap-1 text-[11px] text-blue-600 hover:underline dark:text-blue-400"
          >
            Open PR <ExternalLink size={10} />
          </a>
        )}
      </div>
    </div>
  );
};
