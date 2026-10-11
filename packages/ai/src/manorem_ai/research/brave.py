"""The one real, opt-in research backend: Brave Search plus a page fetch.

This exists to prove the provider-neutral seam against something that actually
hits the network, not to become a multi-provider search ecosystem -- one real
adapter is enough, and every vendor-specific detail stays inside this module.

Two properties matter more than the vendor:

* **Opt-in and unreachable offline.** Nothing constructs this unless settings
  name ``brave`` explicitly, and ``--offline`` refuses to build it, so the
  default and test paths never touch the network.
* **Transport is injectable.** Every HTTP call goes through one callable, so the
  normal test suite drives the whole provider from a fixture dictionary with no
  socket involved, and the one live test is explicitly marked ``network``.

Retrieved pages are parsed as *data*: the HTML is stripped with a stdlib parser
that emits text, never executed, and the only thing taken from a page is the
bytes that become a :class:`~manorem_ai.research.models.Source`'s content. An api
key is unwrapped only to build a request header; it is never hashed, logged,
persisted or written into an artifact.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote as url_quote
from urllib.request import Request, urlopen

from pydantic import SecretStr

from manorem_ai.research.models import (
    Document,
    ResearchRequest,
    ResearchResult,
    RetrievedSource,
    Source,
)
from manorem_ai.research.providers import ResearchError

__all__ = ["BraveResearchProvider", "Transport", "html_to_text"]

#: One HTTP round trip: (url, headers) -> raw body. The single seam tests replace.
Transport = Callable[[str, Mapping[str, str]], bytes]

_DEFAULT_BASE_URL = "https://api.search.brave.com/res/v1"
#: Brave caps ``count`` at 20; a request above that is clamped, never looped.
_MAX_COUNT = 20
_BLOCK_TAGS = frozenset(
    {"p", "div", "li", "ul", "ol", "table", "tr", "td", "th", "br", "hr", "section", "article"}
)
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "head"})
_HEADING_TAGS = frozenset({f"h{i}" for i in range(1, 7)})


class _TextExtractor(HTMLParser):
    """Turn HTML into plain text with paragraph breaks, discarding markup.

    A deliberately dumb extractor: it walks tags, drops the ones whose *content*
    is code or styling rather than prose, and emits newlines where a block ends.
    Nothing in the input can influence what it does -- it only ever appends to a
    list of strings.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif not self._skip_depth and (tag in _BLOCK_TAGS or tag in _HEADING_TAGS):
            self._parts.append("\n\n" if tag in _HEADING_TAGS else "\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif not self._skip_depth and (tag in _BLOCK_TAGS or tag in _HEADING_TAGS):
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        joined = "".join(self._parts)
        joined = re.sub(r"[ \t\r\f\v]+", " ", joined)
        joined = re.sub(r" *\n *", "\n", joined)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return joined.strip()


def html_to_text(html: str) -> str:
    """Extract readable text from an HTML document. Never executes anything."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # A page that will not parse still yields whatever was read before the
        # parser stopped. Returning partial text keeps a real source real rather
        # than discarding it; it never invents the missing part.
        pass
    return parser.text()


def _require_http(url: str) -> str:
    """Reject anything that is not plain http(s) before a socket is opened."""
    if not url.startswith(("http://", "https://")):
        raise ResearchError(f"refusing to fetch a non-http URL: {url!r}")
    return url


def _urllib_transport(url: str, headers: Mapping[str, str], *, timeout_s: float) -> bytes:
    request = Request(_require_http(url), headers=dict(headers))
    with urlopen(request, timeout=timeout_s) as response:
        body: bytes = response.read()
    return body


class BraveResearchProvider:
    """Brave's Search API, followed by a fetch of each result page.

    The search returns candidate URLs; the *content* a claim can be evidenced
    against is the page itself, fetched and stripped to text. A page that cannot
    be fetched is dropped rather than substituted with the search snippet -- the
    snippet is Brave's summary of the page, not the page, and attributing it to
    the page's URL would be a provenance lie.
    """

    name = "brave"
    #: A live search plus one page fetch per source is genuinely expensive, so
    #: this is the one backend worth caching. Set in ``__init__`` from the gateway
    #: URL alone -- never the key -- and folded into every cache key, so
    #: reconfiguring the gateway misses instead of replaying stale hits.
    cache_identity: str

    def __init__(
        self,
        api_key: SecretStr | str | None = None,
        *,
        base_url: str | None = None,
        transport: Transport | None = None,
        timeout_s: float = 20.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self._transport = transport
        self._timeout_s = timeout_s
        self._clock = clock or (lambda: datetime.now(UTC))
        self.cache_identity = f"brave:{self._base_url}"

    def _key(self) -> str:
        if self._api_key is None:
            raise ResearchError(
                "MANOREM_RESEARCH_API_KEY is not set. Set it, or use "
                "MANOREM_RESEARCH_PROVIDER=stub (offline) or =cassette (recorded replay)."
            )
        return (
            self._api_key.get_secret_value()
            if isinstance(self._api_key, SecretStr)
            else self._api_key
        )

    def _send(self, url: str, headers: Mapping[str, str]) -> bytes:
        if self._transport is not None:
            return self._transport(url, headers)
        try:
            return _urllib_transport(url, headers, timeout_s=self._timeout_s)
        except ResearchError:
            raise
        except Exception as exc:
            raise ResearchError(f"research request failed: {exc}") from exc

    def research(self, request: ResearchRequest) -> ResearchResult:
        key = self._key()
        query = " ".join(part for part in (request.topic, *request.questions) if part)
        count = min(request.max_sources, _MAX_COUNT)
        url = f"{self._base_url}/web/search?q={url_quote(query)}&count={count}"
        headers = {"Accept": "application/json", "X-Subscription-Token": key}

        try:
            payload = json.loads(self._send(url, headers).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResearchError(f"search response was not valid JSON: {exc}") from exc
        results = _results(payload)
        if not results:
            return ResearchResult(request=request, retrieved=())

        retrieved: list[RetrievedSource] = []
        for hit in results[: request.max_sources]:
            item = self._fetch(hit, clock=self._clock)
            if item is not None:
                retrieved.append(item)
        return ResearchResult(request=request, retrieved=tuple(retrieved))

    def retrieve(self, query: str, *, limit: int = 8) -> tuple[Document, ...]:
        """The M1 retrieval seam, adapted onto :meth:`research`."""
        result = self.research(ResearchRequest(topic=query, max_sources=limit))
        return tuple(
            Document(source=item.source, content=item.content) for item in result.retrieved[:limit]
        )

    def _fetch(
        self, hit: dict[str, Any], *, clock: Callable[[], datetime]
    ) -> RetrievedSource | None:
        """Fetch one result page; ``None`` when it cannot honestly be retrieved."""
        page_url = str(hit.get("url", ""))
        if not page_url:
            return None
        try:
            raw = self._send(
                _require_http(page_url),
                {"Accept": "text/html,application/xhtml+xml", "User-Agent": "manorem/0.1"},
            )
        except ResearchError:
            return None
        try:
            html = raw.decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - errors="replace" never raises
            return None
        content = html_to_text(html)
        if not content:
            return None
        return RetrievedSource(
            source=Source.of(
                url=page_url,
                content=content,
                title=str(hit.get("title", "")),
                publisher=_publisher(page_url),
                retrieved_at=clock(),
                media_type="text/html",
                metadata={"search_provider": self.name},
            ),
            content=content,
        )


def _results(payload: object) -> list[dict[str, Any]]:
    """Pull ``web.results`` out of a search response, tolerating a partial one."""
    if not isinstance(payload, dict):
        return []
    web = payload.get("web")
    if not isinstance(web, dict):
        return []
    results = web.get("results")
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict) and item.get("url")]


def _publisher(url: str) -> str:
    """The host part of a URL, used as a neutral publisher label."""
    host = url.split("://", 1)[-1].split("/", 1)[0]
    return host.split("@")[-1].split(":")[0]
