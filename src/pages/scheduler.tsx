import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  Check,
  Loader2,
  Lock,
  RefreshCw,
  Users,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { formatFull, formatWithWeekday } from "@/lib/datetime";
import {
  applySchedule,
  getAvailability,
  getInterruptions,
  getScheduleConflicts,
  planSchedule,
  type Availability,
  type CalendarConflict,
  type EventClass,
  type InterruptionEntry,
  type ScheduleMove,
  type ScheduleProposal,
} from "@/lib/api";

/**
 * Adaptive Scheduler.
 *
 * Planning and applying are separate steps. A plan that moves other people's
 * meetings sends invite updates to all of them, so it is shown in full and
 * applied only when the user says so.
 */

const CLASS_LABEL: Record<EventClass, { label: string; tone: string }> = {
  flexible: { label: "flexible", tone: "text-green-600 dark:text-green-400" },
  soft_fixed: { label: "team meeting", tone: "text-yellow-600 dark:text-yellow-400" },
  hard_fixed: { label: "fixed", tone: "text-red-600 dark:text-red-400" },
};

// Always IST, never the browser's zone. A schedule is the one place a wrong
// offset is both most likely to be acted on and hardest to notice.
const formatWhen = (iso: string) => formatWithWeekday(iso);

const MoveRow = ({ move }: { move: ScheduleMove }) => {
  const tone = CLASS_LABEL[move.event_class];

  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium text-foreground">{move.title}</span>
        <span className={`text-xs ${tone.tone}`}>{tone.label}</span>
        {move.attendee_count > 1 && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Users size={11} />
            {move.attendee_count}
          </span>
        )}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {move.from_start ? (
          <>
            <span className="line-through">{formatWhen(move.from_start)}</span>
            <ArrowRight size={11} />
          </>
        ) : (
          <span className="text-green-600 dark:text-green-400">new block</span>
        )}
        <span className="font-medium text-foreground">
          {formatWhen(move.to_start)}
        </span>
        <span>({move.duration_minutes} min)</span>
      </div>
      {move.reason && (
        <p className="mt-1 text-xs text-muted-foreground">{move.reason}</p>
      )}
    </div>
  );
};

/**
 * Whether you can be reached, reading the same value the Slack reply uses.
 *
 * One source, so the channel and this chip cannot disagree about whether you
 * are in a meeting. Times render through `src/lib/datetime.ts` with its
 * explicit zone, so every viewer reads the same wall clock.
 */
const AvailabilityChip = ({ availability }: { availability: Availability }) => {
  const tone = {
    free: "bg-green-500/10 text-green-600 dark:text-green-400",
    busy: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
    focus: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
    off_hours: "bg-muted text-muted-foreground",
  }[availability.state];

  const label = {
    free: "Free",
    busy: "In a meeting",
    focus: "Heads-down",
    off_hours: "Outside working hours",
  }[availability.state];

  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${tone}`}
    >
      {label}
      {availability.until && ` until ${formatFull(availability.until)}`}
    </span>
  );
};

/**
 * How Locus judged an interruption, in plain words.
 *
 * Two of the three are deterministic facts. The third is a model's opinion and
 * is worded to read as the weaker claim it is.
 */
const IMPORTANCE_CAPTION: Record<string, string> = {
  reviewer: "your reviewer, mid-round",
  worklist: "names work blocked on you",
  classifier: "judged important",
};

/** Who reached you while you were busy, and what Locus said back. */
const InterruptionsStrip = ({
  interruptions,
}: {
  interruptions: InterruptionEntry[];
}) => (
  <div className="mb-6 rounded-xl border border-border bg-card p-4">
    <h2 className="text-sm font-semibold text-foreground">
      Reached you while you were busy
    </h2>
    <ul className="mt-2 space-y-2">
      {interruptions.map((entry) => (
        <li key={entry.id} className="rounded-lg border border-border p-2.5">
          <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
            <span className="font-medium text-foreground">
              {entry.participant ?? "Someone"}
            </span>
            <span className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
              {entry.availability_state}
            </span>
            {entry.importance === "important" && (
              <span className="rounded bg-orange-500/10 px-1.5 py-0.5 text-orange-600 dark:text-orange-400">
                {IMPORTANCE_CAPTION[entry.importance_source] ?? "important"}
              </span>
            )}
            {!entry.replied && (
              <span
                title="Already answered in this thread today, or the send failed"
                className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground"
              >
                no reply sent
              </span>
            )}
            {entry.occurred_at && (
              <span className="ml-auto text-muted-foreground">
                {formatFull(entry.occurred_at)}
              </span>
            )}
          </div>
          {entry.excerpt && (
            <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
              {entry.excerpt}
            </p>
          )}
          {/* Stored as sent, not reconstructed — a reconstruction drifts from
              what the channel actually saw. */}
          {entry.reply_body && (
            <p className="mt-1 text-xs text-foreground">
              Locus replied: {entry.reply_body}
            </p>
          )}
        </li>
      ))}
    </ul>
  </div>
);

export default function SchedulerPage() {
  const { user } = useAuth();

  const [conflicts, setConflicts] = useState<CalendarConflict[]>([]);
  const [totalEvents, setTotalEvents] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [when, setWhen] = useState("");
  const [duration, setDuration] = useState(60);
  const [attendees, setAttendees] = useState(1);

  const [proposal, setProposal] = useState<ScheduleProposal | null>(null);
  const [planning, setPlanning] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState<string[] | null>(null);
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [interruptions, setInterruptions] = useState<InterruptionEntry[]>([]);

  const refresh = useCallback(async () => {
    try {
      const data = await getScheduleConflicts();
      setConflicts(data.conflicts);
      setTotalEvents(data.total_events);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read the calendar");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    // Both are decoration on the page below. A failure costs the chip or the
    // strip, never the conflicts view that is the point of the page.
    getAvailability().then(setAvailability).catch(() => setAvailability(null));
    getInterruptions().then(setInterruptions).catch(() => setInterruptions([]));
  }, [refresh]);

  const handlePlan = async () => {
    if (!title.trim() || !when.trim()) return;
    setPlanning(true);
    setError(null);
    setApplied(null);
    try {
      setProposal(await planSchedule(title.trim(), when.trim(), duration, attendees));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not build a plan");
      setProposal(null);
    } finally {
      setPlanning(false);
    }
  };

  const handleApply = async () => {
    if (!proposal) return;
    setApplying(true);
    try {
      const result = await applySchedule(proposal.moves, proposal.additions);
      setApplied([...result.applied, ...result.failed.map((f) => `Failed: ${f}`)]);
      setProposal(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not apply the plan");
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl p-6">
        <div className="mb-6 flex items-start justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
              Scheduler
              {availability && <AvailabilityChip availability={availability} />}
            </h1>
            <p className="text-sm text-muted-foreground">
              Rearranges your calendar around new work, protecting deadlines.
              Times are read in {user?.timezone ?? "Asia/Kolkata"}.
            </p>
          </div>
          <button
            onClick={refresh}
            className="rounded-lg border border-border p-2 hover:bg-muted"
            aria-label="Refresh"
          >
            <RefreshCw size={15} className="text-muted-foreground" />
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        )}

        {interruptions.length > 0 && (
          <InterruptionsStrip interruptions={interruptions} />
        )}

        {applied && (
          <div className="mb-4 rounded-lg bg-green-500/10 px-3 py-2 text-sm text-green-600 dark:text-green-400">
            <p className="mb-1 font-medium">Applied</p>
            <ul className="space-y-0.5 text-xs">
              {applied.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Conflicts already on the calendar */}
        <div className="mb-6 rounded-xl border border-border bg-card p-4">
          <h2 className="mb-2 text-sm font-semibold text-foreground">
            Double-bookings
            <span className="ml-1 font-normal text-muted-foreground">
              — next 14 days
            </span>
          </h2>
          {loading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 size={13} className="animate-spin" /> Reading calendar...
            </div>
          ) : conflicts.length === 0 ? (
            <p className="flex items-center gap-1.5 text-xs text-green-600 dark:text-green-400">
              <Check size={13} /> No conflicts across {totalEvents} events.
            </p>
          ) : (
            <div className="space-y-1.5">
              {conflicts.map((c, i) => (
                <div
                  key={i}
                  className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 px-3 py-2 text-xs"
                >
                  <span className="font-medium text-foreground">{c.first.title}</span>
                  <span className="text-muted-foreground"> overlaps </span>
                  <span className="font-medium text-foreground">{c.second.title}</span>
                  <div className="mt-0.5 text-muted-foreground">
                    {formatWhen(c.first.start)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Plan a new event */}
        <div className="mb-6 rounded-xl border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold text-foreground">
            Fit something in
          </h2>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="What is it?"
              className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
            <input
              value={when}
              onChange={(e) => setWhen(e.target.value)}
              placeholder="tomorrow at 3pm"
              className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              Minutes
              <input
                type="number"
                value={duration}
                min={5}
                max={720}
                onChange={(e) => setDuration(Number(e.target.value))}
                className="w-20 rounded-lg border border-border bg-background px-2 py-1.5 text-sm text-foreground"
              />
            </label>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              Attendees
              <input
                type="number"
                value={attendees}
                min={1}
                onChange={(e) => setAttendees(Number(e.target.value))}
                className="w-20 rounded-lg border border-border bg-background px-2 py-1.5 text-sm text-foreground"
              />
            </label>
            <button
              onClick={handlePlan}
              disabled={planning || !title.trim() || !when.trim()}
              className="ml-auto flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {planning ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <CalendarClock size={14} />
              )}
              Plan it
            </button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Planning changes nothing. You will see exactly what would move first.
          </p>
        </div>

        {/* The proposal */}
        {proposal && (
          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="mb-1 text-sm font-semibold text-foreground">
              Proposed plan
            </h2>
            <p className="mb-3 text-xs text-muted-foreground">{proposal.summary}</p>

            {proposal.moves.length > 0 && (
              <div className="mb-3 space-y-1.5">
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Would move
                </p>
                {proposal.moves.map((m) => (
                  <MoveRow key={m.event_id} move={m} />
                ))}
              </div>
            )}

            {proposal.additions.length > 0 && (
              <div className="mb-3 space-y-1.5">
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Would add
                </p>
                {proposal.additions.map((m, i) => (
                  <MoveRow key={i} move={m} />
                ))}
              </div>
            )}

            {proposal.blocked.length > 0 && (
              <div className="mb-3">
                <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Cannot resolve
                </p>
                <ul className="space-y-1">
                  {proposal.blocked.map((b, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-1.5 rounded-lg bg-yellow-500/10 px-3 py-2 text-xs text-yellow-700 dark:text-yellow-400"
                    >
                      <Lock size={11} className="mt-0.5 shrink-0" />
                      {b}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {proposal.moves.length + proposal.additions.length > 0 && (
              <>
                {proposal.moves.some((m) => m.attendee_count > 1) && (
                  <p className="mb-2 flex items-start gap-1.5 text-xs text-yellow-700 dark:text-yellow-400">
                    <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                    Some of these have other attendees. Applying sends them
                    updated invites.
                  </p>
                )}
                <div className="flex gap-2">
                  <button
                    onClick={handleApply}
                    disabled={applying}
                    className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                  >
                    {applying ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Check size={14} />
                    )}
                    Apply plan
                  </button>
                  <button
                    onClick={() => setProposal(null)}
                    className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-muted"
                  >
                    Discard
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
