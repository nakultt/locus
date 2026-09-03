"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CalendarPlus,
  CalendarX2,
  Check,
  Lock,
  MessageSquareWarning,
  RefreshCw,
  Users,
} from "lucide-react";
import { useAuth } from "@/features/auth/auth-context";
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
import { PageHeader, PageShell } from "@/components/layout/app-shell";
import { Badge, Dot, type DotTone } from "@/components/ui/badge";
import { Button, IconButton } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import {
  EmptyState,
  Kicker,
  Notice,
  Panel,
  Section,
  Skeleton,
} from "@/components/ui/surface";
import { useToast } from "@/components/ui/toast";

/**
 * Calendar.
 *
 * Planning and applying stay separate steps. A plan that moves other people's
 * meetings sends invite updates to all of them, so it is shown in full and
 * applied only when the user says so — the button that does it is deliberately
 * not the same button that produces the plan.
 *
 * The composer moved to the top of the page. It was the third panel down,
 * beneath a conflicts list that is usually empty, which put the only thing
 * anyone comes here to do below two panels reporting that nothing is wrong.
 */

const CLASS_TONE: Record<EventClass, { label: string; tone: DotTone }> = {
  flexible: { label: "Flexible", tone: "success" },
  soft_fixed: { label: "Team meeting", tone: "warning" },
  hard_fixed: { label: "Fixed", tone: "danger" },
};

// Always IST, never the browser's zone. A schedule is the one place a wrong
// offset is both most likely to be acted on and hardest to notice.
const when = (iso: string) => formatWithWeekday(iso);

function MoveRow({ move }: { move: ScheduleMove }) {
  const cls = CLASS_TONE[move.event_class];

  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="text-sm font-medium text-ink">{move.title}</span>
        <span className="inline-flex items-center gap-1.5 text-xs text-muted">
          <Dot tone={cls.tone} />
          {cls.label}
        </span>
        {move.attendee_count > 1 && (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted">
            <Users className="size-3.5" aria-hidden />
            {move.attendee_count}
          </span>
        )}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
        {move.from_start ? (
          <>
            <span className="text-subtle line-through">
              {when(move.from_start)}
            </span>
            <ArrowRight className="size-3.5 shrink-0 text-subtle" aria-hidden />
          </>
        ) : (
          <Badge tone="success">New block</Badge>
        )}
        <span className="font-medium text-ink">{when(move.to_start)}</span>
        <span className="text-muted">{move.duration_minutes} min</span>
      </div>

      {move.reason && (
        <p className="mt-1.5 text-sm text-muted">{move.reason}</p>
      )}
    </Panel>
  );
}

/**
 * Whether you can be reached, reading the same value the Slack reply uses.
 *
 * One source, so the channel and this chip cannot disagree about whether you
 * are in a meeting. The type carries a state, a time and nothing else — there
 * is deliberately no field through which "in a 1:1 with Priya re: restructure"
 * could reach a channel other people read.
 */
function AvailabilityChip({ availability }: { availability: Availability }) {
  const map = {
    free: { label: "Free", tone: "success" as DotTone },
    busy: { label: "In a meeting", tone: "warning" as DotTone },
    focus: { label: "Heads-down", tone: "info" as DotTone },
    off_hours: { label: "Outside working hours", tone: "neutral" as DotTone },
  }[availability.state];

  return (
    <span className="inline-flex items-center gap-2 rounded-pill border border-line bg-surface px-3 py-1.5 text-sm">
      <Dot tone={map.tone} pulse={availability.state === "free"} />
      <span className="font-medium text-ink">{map.label}</span>
      {availability.until && (
        <span className="text-muted">until {formatFull(availability.until)}</span>
      )}
    </span>
  );
}

/**
 * How Locus judged an interruption, in plain words.
 *
 * Two of the three are deterministic facts. The third is a model's opinion and
 * is worded — and toned — to read as the weaker claim it is.
 */
const IMPORTANCE: Record<string, { caption: string; tone: DotTone }> = {
  reviewer: { caption: "your reviewer, mid-round", tone: "danger" },
  worklist: { caption: "names work blocked on you", tone: "danger" },
  classifier: { caption: "judged important", tone: "warning" },
};

function Interruptions({ entries }: { entries: InterruptionEntry[] }) {
  return (
    <Section
      title="Reached you while you were busy"
      description="Locus replied with your state and when you are next free — never with what you were doing."
    >
      <Panel className="divide-y divide-line">
        {entries.map((entry) => {
          const importance =
            entry.importance === "important"
              ? IMPORTANCE[entry.importance_source]
              : null;

          return (
            <div key={entry.id} className="p-5">
              <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
                <span className="text-sm font-medium text-ink">
                  {entry.participant ?? "Someone"}
                </span>
                <Badge tone="neutral">{entry.availability_state}</Badge>
                {importance && (
                  <Badge tone={importance.tone === "danger" ? "danger" : "warning"}>
                    {importance.caption}
                  </Badge>
                )}
                {!entry.replied && (
                  <Badge
                    tone="neutral"
                    title="Already answered in this thread today, or the send failed"
                  >
                    no reply sent
                  </Badge>
                )}
                {entry.occurred_at && (
                  <span className="ml-auto shrink-0 text-xs text-subtle">
                    {formatFull(entry.occurred_at)}
                  </span>
                )}
              </div>

              {entry.excerpt && (
                <p className="mt-2 line-clamp-2 text-sm text-muted">
                  {entry.excerpt}
                </p>
              )}

              {/* Stored as sent, not reconstructed — a reconstruction drifts
                  from what the channel actually saw. */}
              {entry.reply_body && (
                <p className="mt-2 rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-ink">
                  <span className="text-subtle">Locus replied: </span>
                  {entry.reply_body}
                </p>
              )}
            </div>
          );
        })}
      </Panel>
    </Section>
  );
}

export default function SchedulerView() {
  const { user } = useAuth();
  const toast = useToast();

  const [conflicts, setConflicts] = useState<CalendarConflict[]>([]);
  const [totalEvents, setTotalEvents] = useState(0);
  const [loading, setLoading] = useState(true);
  const [unreadable, setUnreadable] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [whenText, setWhenText] = useState("");
  const [duration, setDuration] = useState(60);
  const [attendees, setAttendees] = useState(1);

  const [proposal, setProposal] = useState<ScheduleProposal | null>(null);
  const [planning, setPlanning] = useState(false);
  const [applying, setApplying] = useState(false);
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [interruptions, setInterruptions] = useState<InterruptionEntry[]>([]);

  const refresh = useCallback(async () => {
    try {
      const data = await getScheduleConflicts();
      setConflicts(data.conflicts);
      setTotalEvents(data.total_events);
      setUnreadable(null);
    } catch (e) {
      setUnreadable(
        e instanceof Error ? e.message : "Could not read the calendar"
      );
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

  const plan = async () => {
    if (!title.trim() || !whenText.trim()) return;
    setPlanning(true);
    try {
      setProposal(
        await planSchedule(title.trim(), whenText.trim(), duration, attendees)
      );
    } catch (e) {
      toast.error(
        "Could not build a plan",
        e instanceof Error ? e.message : undefined
      );
      setProposal(null);
    } finally {
      setPlanning(false);
    }
  };

  const apply = async () => {
    if (!proposal) return;
    setApplying(true);
    try {
      const result = await applySchedule(proposal.moves, proposal.additions);
      if (result.failed.length > 0) {
        toast.error(
          `${result.applied.length} applied, ${result.failed.length} failed`,
          result.failed.join("; ")
        );
      } else {
        toast.success(
          `Calendar updated`,
          `${result.applied.length} change${result.applied.length === 1 ? "" : "s"} applied.`
        );
      }
      setProposal(null);
      await refresh();
    } catch (e) {
      toast.error(
        "Could not apply the plan",
        e instanceof Error ? e.message : undefined
      );
    } finally {
      setApplying(false);
    }
  };

  const movesOthers = proposal?.moves.some((m) => m.attendee_count > 1);
  const hasChanges =
    (proposal?.moves.length ?? 0) + (proposal?.additions.length ?? 0) > 0;

  return (
    <PageShell width="narrow">
      <PageHeader
        title="Calendar"
        description={`Rearranges your week around new work, protecting deadlines and refusing to move anything with external attendees. Times are read in ${user?.timezone ?? "Asia/Kolkata"}.`}
        eyebrow={availability && <AvailabilityChip availability={availability} />}
        actions={
          <IconButton label="Refresh" variant="secondary" onClick={refresh}>
            <RefreshCw />
          </IconButton>
        }
      />

      {/* An unreadable calendar reads free, never busy — a broken token and a
          real meeting produce identical silence, and defaulting to busy tells
          everybody you are in a meeting you are not in. Said out loud here. */}
      {unreadable && (
        <Notice
          tone="warning"
          className="mt-6"
          icon={<AlertTriangle aria-hidden />}
          title="Your calendar could not be read"
        >
          {unreadable} Until this is fixed, Locus treats you as free rather than
          busy — an auto-reply saying you are in a meeting you are not in is
          worse than none.
        </Notice>
      )}

      <div className="mt-8 space-y-10">
        {/* ── Composer ──────────────────────────────────────────────────── */}
        <Section
          title="Fit something in"
          description="Planning changes nothing. You see exactly what would move first."
        >
          <Panel className="p-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="What is it?" htmlFor="ev-title">
                <Input
                  id="ev-title"
                  placeholder="Design review"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                />
              </Field>
              <Field
                label="When"
                htmlFor="ev-when"
                hint="Plain language. Nothing is guessed — an unreadable time returns no plan."
              >
                <Input
                  id="ev-when"
                  placeholder="tomorrow at 3pm"
                  value={whenText}
                  onChange={(e) => setWhenText(e.target.value)}
                />
              </Field>
            </div>

            <div className="mt-4 flex flex-wrap items-end gap-4">
              <Field label="Minutes" htmlFor="ev-mins" className="w-28">
                <Input
                  id="ev-mins"
                  type="number"
                  min={5}
                  max={720}
                  value={duration}
                  onChange={(e) => setDuration(Number(e.target.value))}
                />
              </Field>
              <Field label="Attendees" htmlFor="ev-att" className="w-28">
                <Input
                  id="ev-att"
                  type="number"
                  min={1}
                  value={attendees}
                  onChange={(e) => setAttendees(Number(e.target.value))}
                />
              </Field>
              <Button
                className="ml-auto"
                onClick={plan}
                loading={planning}
                disabled={!title.trim() || !whenText.trim()}
              >
                {!planning && <CalendarPlus aria-hidden />}
                Plan it
              </Button>
            </div>
          </Panel>
        </Section>

        {/* ── Proposal ──────────────────────────────────────────────────── */}
        {proposal && (
          <Section title="Proposed plan" description={proposal.summary}>
            <div className="space-y-4">
              {proposal.moves.length > 0 && (
                <div className="space-y-2">
                  <Kicker>Would move</Kicker>
                  {proposal.moves.map((m) => (
                    <MoveRow key={m.event_id} move={m} />
                  ))}
                </div>
              )}

              {proposal.additions.length > 0 && (
                <div className="space-y-2">
                  <Kicker>Would add</Kicker>
                  {proposal.additions.map((m, i) => (
                    <MoveRow key={i} move={m} />
                  ))}
                </div>
              )}

              {/* Anything with external attendees is reported as blocked
                  rather than moved. The solver is plain Python for exactly
                  this reason — a model asked to rearrange a calendar produces
                  plausible schedules with overlaps and missed deadlines. */}
              {proposal.blocked.length > 0 && (
                <div className="space-y-2">
                  <Kicker>Cannot resolve</Kicker>
                  <Panel tone="warning" className="divide-y divide-warning-border">
                    {proposal.blocked.map((b, i) => (
                      <p
                        key={i}
                        className="flex items-start gap-2.5 px-4 py-3 text-sm text-ink"
                      >
                        <Lock className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
                        {b}
                      </p>
                    ))}
                  </Panel>
                </div>
              )}

              {hasChanges && (
                <>
                  {movesOthers && (
                    <Notice
                      tone="warning"
                      icon={<Users aria-hidden />}
                      title="This reaches other people"
                    >
                      Some of these have other attendees. Applying sends every
                      one of them an updated invite.
                    </Notice>
                  )}
                  <div className="flex flex-wrap gap-2">
                    <Button onClick={apply} loading={applying}>
                      {!applying && <Check aria-hidden />}
                      Apply plan
                    </Button>
                    <Button variant="secondary" onClick={() => setProposal(null)}>
                      Discard
                    </Button>
                  </div>
                </>
              )}
            </div>
          </Section>
        )}

        {/* ── Conflicts ─────────────────────────────────────────────────── */}
        <Section
          title="Double-bookings"
          description="The next fourteen days on your primary calendar."
        >
          {loading ? (
            <Skeleton className="h-24 w-full" />
          ) : conflicts.length === 0 ? (
            <EmptyState
              compact
              icon={<Check aria-hidden />}
              title="No conflicts"
              description={`Nothing overlaps across ${totalEvents} event${totalEvents === 1 ? "" : "s"}.`}
            />
          ) : (
            <div className="space-y-2">
              {conflicts.map((c, i) => (
                <Panel key={i} tone="warning" className="p-4">
                  <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                    <CalendarX2 className="size-4 shrink-0 text-warning" aria-hidden />
                    <span className="font-medium text-ink">{c.first.title}</span>
                    <span className="text-muted">overlaps</span>
                    <span className="font-medium text-ink">{c.second.title}</span>
                  </p>
                  <p className="mt-1 pl-6 text-sm text-muted">
                    {when(c.first.start)}
                  </p>
                </Panel>
              ))}
            </div>
          )}
        </Section>

        {/* ── Interruptions ─────────────────────────────────────────────── */}
        {interruptions.length > 0 ? (
          <Interruptions entries={interruptions} />
        ) : (
          <Section
            title="Reached you while you were busy"
            description="Locus replies with your state and when you are next free, at most once per thread per day."
          >
            <EmptyState
              compact
              icon={<MessageSquareWarning aria-hidden />}
              title="Nobody has been auto-replied to"
              description="Messages that arrive during a meeting or a focus block appear here, along with exactly what was sent back."
            />
          </Section>
        )}
      </div>
    </PageShell>
  );
}
