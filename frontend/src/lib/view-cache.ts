/**
 * The last thing a view showed, kept so a reload paints instead of waiting.
 *
 * Stale-while-revalidate and nothing cleverer: the stored value is rendered
 * immediately and the normal request goes out in the same breath, so nothing is
 * ever served *instead* of live data — only ahead of it. The server's own
 * caches cannot help here, because a fresh page load is a miss by definition,
 * which is the one moment the wait is actually felt.
 *
 * The rules live here rather than in each view because each is one you only get
 * wrong once, silently:
 *
 * - **Keyed by user.** Two accounts share a browser, and what these views hold
 *   is assigned work, repo names and connected services. Restoring one
 *   account's under another is the same mistake the backend spent nine query
 *   fixes removing, one surface along — and here it would be rendered rather
 *   than merely read.
 * - **Every access guarded.** Storage throws outright in some contexts (private
 *   windows, embedded previews, browsers set to block site data), and a view
 *   that will not load is far worse than one that starts empty.
 * - **Expired by age.** These are claims about how things are *now*.
 *   Yesterday's is reasonable to glance at for the second before the live one
 *   lands; last month's is a different week, and painting it reads as the page
 *   having loaded.
 *
 * Callers read on mount rather than in a `useState` initializer — the rule
 * `AuthContext` follows, because Next runs the initializer on the server where
 * there is no storage, so the first client render would disagree with the
 * markup the server sent.
 *
 * Two call shapes are exported and they are the *same* cache: `readCached` /
 * `writeCached` take the view's name per call, and `createViewCache` binds that
 * name once. The factory is a thin wrapper over the functions rather than a
 * second implementation — one set of storage rules, so the two cannot drift.
 */

/** Beyond this the value is discarded and the view shows its own skeleton. */
const MAX_AGE_MS = 24 * 60 * 60 * 1000;

const VERSION = 1;

const keyFor = (name: string, userId: number | string, version = VERSION) =>
  `locus.${name}.v${version}.${userId}`;

export type Cached<T> = {
  value: T;
  /** When it was stored, as an ISO instant. */
  storedAt: string;
};

/** The same shape under the name the task board imports it by. */
export type Restored<T> = Cached<T>;

/**
 * The stored value for this view and user, or null.
 *
 * Anything unreadable or expired is discarded rather than repaired — the live
 * response is a moment away regardless. The shape is deliberately not
 * validated: each view already normalises what the API hands it, and a second
 * copy of that guard would drift from the first.
 */
export function readCached<T>(
  name: string,
  userId: number | string,
  version = VERSION
): Cached<T> | null {
  try {
    const raw = window.localStorage.getItem(keyFor(name, userId, version));
    if (!raw) return null;

    const parsed = JSON.parse(raw) as { storedAt?: string; value?: unknown };
    if (!parsed?.storedAt || parsed.value === undefined) return null;

    const age = Date.now() - new Date(parsed.storedAt).getTime();
    if (!Number.isFinite(age) || age < 0 || age > MAX_AGE_MS) {
      window.localStorage.removeItem(keyFor(name, userId, version));
      return null;
    }

    return { value: parsed.value as T, storedAt: parsed.storedAt };
  } catch {
    return null;
  }
}

/** Store what was just rendered. Failure is silent and costs only speed. */
export function writeCached<T>(
  name: string,
  userId: number | string,
  value: T,
  version = VERSION
): void {
  try {
    window.localStorage.setItem(
      keyFor(name, userId, version),
      JSON.stringify({ storedAt: new Date().toISOString(), value })
    );
  } catch {
    // Quota exceeded, or storage blocked. The view still works.
  }
}

/** Drop a view's stored value — on sign-out, or when it will not parse. */
export function clearCached(
  name: string,
  userId: number | string,
  version = VERSION
): void {
  try {
    window.localStorage.removeItem(keyFor(name, userId, version));
  } catch {
    // Nothing to do; the age check discards it anyway.
  }
}

export type ViewCache<T> = {
  read: (userId: number | string) => Cached<T> | null;
  write: (userId: number | string, value: T) => void;
  clear: (userId: number | string) => void;
};

/**
 * The same cache with its name and version bound once.
 *
 * `version` is bumped by whoever changes the stored shape; an older version is
 * simply never read, which is the right answer given the live response is a
 * moment away. `revive` runs over the parsed value on the way out — it is for a
 * payload that does not survive JSON on its own, and is also the right place to
 * drop anything that must not be restored at all.
 */
export function createViewCache<T>(
  name: string,
  version = VERSION,
  revive?: (value: T) => T
): ViewCache<T> {
  return {
    read(userId) {
      const stored = readCached<T>(name, userId, version);
      if (!stored) return null;
      return revive ? { ...stored, value: revive(stored.value) } : stored;
    },
    write: (userId, value) => writeCached(name, userId, value, version),
    clear: (userId) => clearCached(name, userId, version),
  };
}
