"""One TLS setup for every outgoing HTTPS client: Qloo, Valhalla, Overpass, Nominatim, OpenFreeMap, Google and the AI
providers. Reading the CA bundle takes a noticeable moment on a small server (0.1 CPU), and each httpx client would
read it again as the server starts. The context is httpx's own default: certifi's bundle, or SSL_CERT_FILE or
SSL_CERT_DIR when set.
"""
from __future__ import annotations

import ssl
from functools import lru_cache

import httpx


@lru_cache(maxsize=1)
def context() -> ssl.SSLContext:
    return httpx.create_ssl_context()
