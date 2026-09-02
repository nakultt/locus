"""
Where the browser is sent back to after an OAuth round trip.

Both OAuth routers used to build these URLs inline, which meant the frontend's
integrations route was written out twenty times across two files as an f-string
prefix. Renaming that route — as the move to Next did — meant finding every one
of them, and a missed occurrence fails only in the browser, at the end of a
consent flow that is tedious to re-run.

The provider never sees these URLs. It knows only the backend's own callback
(`GOOGLE_REDIRECT_URI` / `LINEAR_REDIRECT_URI`); this is the last hop, from the
callback back to the application, so it can change freely with the frontend.
"""

import os
from urllib.parse import urlencode

# Next serves on 3000. This default was Vite's 5173 until the frontend moved,
# and a stale default here is silent: the OAuth flow completes, stores the
# credential, and then redirects the browser to a port with nothing on it.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# The page a user starts these flows from, and the one that reads the
# `success` / `error` parameters below.
INTEGRATIONS_PATH = "/integrations"


def integrations_url(**params: str) -> str:
    """
    The integrations page, with query parameters attached.

    Values are URL-encoded rather than interpolated: `error` carries provider
    text that has contained spaces and quotes, which produced a redirect the
    browser rejected outright — reported by the user as the connect button
    doing nothing.
    """
    base = f"{FRONTEND_URL}{INTEGRATIONS_PATH}"
    return f"{base}?{urlencode(params)}" if params else base
