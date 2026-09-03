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
import { fileURLToPath } from "node:url";

// fileURLToPath, not `.pathname`: on Windows the pathname of a file URL keeps a
// leading slash ("/E:/Github/locus/"), which Bun cannot use as a cwd — the spawn
// then fails as ENOENT on the *command*, which reads as "uv is not installed".
const ROOT = fileURLToPath(new URL("..", import.meta.url));

type Service = {
  name: string;
  cmd: string[];
  cwd: string;
};

const SERVICES: Service[] = [
  {
    name: "backend",
    cmd: ["uv", "run", "main.py"],
    cwd: `${ROOT}backend`,
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
    env: process.env,

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
