#!/usr/bin/env bun
/**
 * Run the whole stack with one command: `bun run dev` from the repo root.
 *
 * Locus is two processes that are useless apart — the Next frontend calls the
 * FastAPI backend for every screen, and the backend is what reaches the local
 * model server. Starting them separately in two terminals is the step people
 * forget, and the failure mode is a UI that loads and then reports every
 * request as a network error.
 *
 * Written against Bun's own APIs rather than a Node script plus a process
 * manager dependency: `Bun.spawn` gives inherited stdio, a `.exited` promise
 * and `.kill()` without pulling in concurrently or npm-run-all.
 */

import { spawn, type Subprocess } from "bun";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// fileURLToPath, not `.pathname`: on Windows the pathname of a file URL keeps a
// leading slash ("/E:/Github/locus/"), which Bun cannot use as a cwd — the spawn
// then fails as ENOENT on the *command*, which reads as "uv is not installed".
const ROOT = fileURLToPath(new URL("..", import.meta.url));

/**
 * The environment for the backend, without anything the repo-root `.env` defined.
 *
 * Bun loads the root `.env` automatically and `Bun.spawn` inherits it, so every
 * variable in that file arrived in the backend as though an operator had
 * exported it. `backend/.env` is then powerless to correct it: python-dotenv's
 * `load_dotenv()` does not override variables already present in the
 * environment.
 *
 * That is not hypothetical. The root file is a leftover from the pre-Next,
 * pre-Postgres stack and still carries `LLM_PROVIDER=gemini` beside a stale
 * `GOOGLE_API_KEY`, so the backend resolved its model backend to Google and
 * sent every diff, Slack thread and ticket body it analysed to a third party --
 * exactly what "the analysis models run locally" exists to prevent. Nothing
 * leaked only because the key was long dead and every call 400'd.
 *
 * Stripping the file's keys rather than a hand-written denylist is deliberate:
 * a denylist has to be updated every time somebody adds a variable, and the
 * failure mode of forgetting is silent. Each half already reads its own `.env`
 * from its own directory, so nothing here needs a root variable to start. A
 * value genuinely exported by the operator's shell is kept, since that is the
 * one case where overriding the file is the point.
 */
function childEnv(root: string): Record<string, string | undefined> {
  const env = { ...process.env } as Record<string, string | undefined>;

  let contents: string;
  try {
    contents = readFileSync(`${root}.env`, "utf8");
  } catch {
    return env; // No root .env: nothing to strip.
  }

  const shellExported = new Set(
    (process.env.LOCUS_KEEP_ROOT_ENV ?? "")
      .split(",")
      .map((name) => name.trim())
      .filter(Boolean),
  );

  for (const line of contents.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    const name = trimmed.slice(0, eq).trim().replace(/^export\s+/, "");
    if (!name || shellExported.has(name)) continue;
    delete env[name];
  }

  return env;
}

type Service = {
  name: string;
  cmd: string[];
  cwd: string;
  /**
   * Whether to hide the repo-root `.env` from this child. See `childEnv`.
   *
   * Only the backend needs it. Next reads its own `.env` files from
   * `frontend/`, but a root-level `NEXT_PUBLIC_*` is a reasonable thing for
   * someone to write, and stripping it would break the browser bundle in a
   * way that looks like a bad build rather than a missing variable. The bug
   * this guards against is specific to the backend, so the blast radius is
   * kept there.
   */
  sanitizeEnv?: boolean;
};

const SERVICES: Service[] = [
  {
    name: "backend",
    cmd: ["uv", "run", "main.py"],
    cwd: `${ROOT}backend`,
    sanitizeEnv: true,
  },
  {
    name: "frontend",
    cmd: ["bun", "run", "dev"],
    cwd: `${ROOT}frontend`,
  },
];

const children: Subprocess[] = [];

/**
 * Stop everything on the way out.
 *
 * Without this, killing the orchestrator leaves uvicorn holding port 8000 and
 * the next run fails to bind — which reads as "the backend is broken" rather
 * than "the last one never exited".
 */
function shutdown(code = 0): never {
  for (const child of children) {
    child.kill();
  }
  process.exit(code);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

for (const service of SERVICES) {
  console.log(`▸ starting ${service.name}: ${service.cmd.join(" ")}`);

  const child = spawn({
    cmd: service.cmd,
    cwd: service.cwd,
    stdio: ["inherit", "inherit", "inherit"],
    env: service.sanitizeEnv ? childEnv(ROOT) : process.env,

    // One process dying takes the pair down. Leaving the survivor running
    // hides which half failed behind a wall of connection-refused errors from
    // the other.
    onExit(_subprocess, exitCode, signalCode) {
      if (signalCode) return; // part of an orderly shutdown
      console.error(`✗ ${service.name} exited with code ${exitCode}`);
      shutdown(exitCode ?? 1);
    },
  });

  children.push(child);
}

await Promise.all(children.map((child) => child.exited));
