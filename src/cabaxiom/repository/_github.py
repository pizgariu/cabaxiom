"""A tiny zero-dependency GitHub REST client - stdlib urllib only, no requests, no PyGithub.

The transport is INJECTABLE: a session carries a callable that turns a request into a response and
the default one hits GitHub over urllib. Tests hand it a fake in-memory GitHub, so a compliance run is
rehearsed against a throwaway world exactly the way the kernel rehearses everything and no test ever
touches the network by accident."""
import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from http.client import HTTPMessage
from typing import IO, Any

# A transport maps (method, url, headers, body) to (status, decoded json body or None).
Transport = Callable[[str, str, Mapping[str, str], bytes | None], tuple[int, Any]]


class _SameOrigin(urllib.request.HTTPRedirectHandler):
    """A redirect handler that will not carry credentials off the origin they were meant for.

    urllib copies every header but the content ones onto the redirected request with no origin check,
    so a peer answering 302 with somebody else's URL would be handed the caller's token. Here the
    Authorization header survives only a redirect that stays on the same scheme, host and port."""

    def redirect_request(self, req: urllib.request.Request, fp: IO[bytes], code: int, msg: str,
                         headers: HTTPMessage, newurl: str) -> urllib.request.Request | None:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        here = urllib.parse.urlsplit(req.full_url)
        there = urllib.parse.urlsplit(newurl)
        if redirected is not None and (here.scheme, here.netloc) != (there.scheme, there.netloc):
            # Both stores, because urllib keeps caller-set headers in one and its own in the other.
            redirected.headers.pop("Authorization", None)
            redirected.unredirected_hdrs.pop("Authorization", None)
        return redirected


class _Urllib:
    """The default Transport - stdlib urllib, carrying a timeout and the same-origin redirect rule.

    A callable object rather than a plain function, because both are state a session owns. The timeout
    bounds every phase of the request, since a peer that accepts a connection and then says nothing
    would otherwise block the calling thread forever - and under a pooled executor that worker is gone
    for the life of the pool, where the run's Cancellation is only checked between units of work. The
    opener carries the redirect rule that keeps the token at home."""

    def __init__(self, timeout: float) -> None:
        self._timeout = timeout
        self._opener = urllib.request.build_opener(_SameOrigin)

    def __call__(self, method: str, url: str, headers: Mapping[str, str],
                 body: bytes | None) -> tuple[int, Any]:  # pragma: no cover - real network
        request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        with self._opener.open(request, timeout=self._timeout) as response:
            payload = response.read()
            return response.status, (json.loads(payload) if payload else None)


class GitHub:
    """A GitHub session - a token, a base URL and the transport that carries the requests. Reconcile a
    repo's settings, topics and labels through it. Pass `transport=` a fake to run offline."""

    def __init__(self, token: str, *, base: str = "https://api.github.com", timeout: float = 30.0,
                 transport: Transport | None = None) -> None:
        self._token = token
        self._base = base.rstrip("/")
        self._transport = transport or _Urllib(timeout)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "cabaxiom",
        }

    def get(self, path: str) -> Any:
        _, data = self._transport("GET", f"{self._base}{path}", self._headers(), None)
        return data

    def patch(self, path: str, body: Mapping[str, object]) -> None:
        self._transport("PATCH", f"{self._base}{path}", self._headers(), json.dumps(body).encode())

    def put(self, path: str, body: Mapping[str, object]) -> None:
        self._transport("PUT", f"{self._base}{path}", self._headers(), json.dumps(body).encode())

