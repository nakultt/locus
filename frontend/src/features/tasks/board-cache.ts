/**
 * The board's view cache.
 *
 * Storage, expiry and per-user keying live in `@/lib/view-cache`, shared with
 * Connections and the chat rail. What is board-specific is which fields must
 * not come back — see `withoutLiveFields`.
 */

import type { TaskBoard } from "@/lib/api";
import { createViewCache } from "@/lib/view-cache";

/**
 * Strip the fields that describe something happening *right now*.
 *
 * The server re-stamps these on every cache hit rather than serving them stale,
 * on the grounds that an "agent working" badge which appears fifty seconds late
 * and lingers fifty seconds after the run ends is worse than no badge at all —
 * it describes the present and gets it wrong. A board out of browser storage
 * can be hours old, so the same argument applies with far more force: it cannot
 * know whether that run is still going, and the honest answer is to say nothing
 * until the live response arrives a moment later.
 */
const withoutLiveFields = (board: TaskBoard): TaskBoard => {
  const clear = (cards: TaskBoard["needs_you"]) =>
    (cards ?? []).map((card) => ({
      ...card,
      authoring_active: false,
      authoring_started_at: null,
    }));

  return {
    ...board,
    needs_you: clear(board.needs_you),
    in_flight: clear(board.in_flight),
    recently_done: clear(board.recently_done),
  };
};

/** Stripping the live fields on the way out is exactly what `revive` is for. */
export const boardCache = createViewCache<TaskBoard>(
  "taskboard",
  1,
  withoutLiveFields
);
