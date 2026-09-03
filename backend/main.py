#!/usr/bin/env python
"""
Run the whole backend: `uv run main.py` from `backend/`.

The application itself lives in `app/main.py`, inside the package, alongside
everything it imports. This file is only the launcher — it exists so there is
one obvious command to start the backend, rather than a uvicorn invocation with
a module path people have to remember correctly.

The four background loops (`worker_loop`, `qa_email_loop`, `merge_gate_loop`,
`calendar_agent_loop`) start with the app's lifespan, so this is the full
backend and not just the HTTP surface.

`uvicorn` is given the import string rather than the imported app object:
`reload=True` needs a path it can re-import in a fresh process, and passing the
object silently disables reloading.
"""

import os

import uvicorn


def main() -> None:
    # Defaults match the frontend's NEXT_PUBLIC_API_URL and the CORS regex in
    # app/main.py. PORT is read because that is what Render and Heroku set.
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    # Reload is a development convenience and is wrong in production, where it
    # would run a file watcher over the whole tree and restart the four
    # background loops on any write. Off unless asked for, so the unsafe case
    # is the one you have to opt into rather than the one you get by default.
    #
    # `bun run dev` sets RELOAD=true, which is what makes the documented dev
    # command reload without making a bare `uv run main.py` unsafe to deploy.
    reload = os.getenv("RELOAD", "false").lower() in {"1", "true", "yes"}

    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
