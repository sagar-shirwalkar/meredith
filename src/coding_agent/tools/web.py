"""
Web tools: web_search and web_fetch.

Supports multiple search backends:
  - Brave Search API (default, independent index)
  - Tavily API (AI-native, citation-focused)
  - Exa API (neural / semantic search)

Web fetch extracts readable content from URLs using basic
HTML stripping (no heavy dependencies).
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from coding_agent.config import AppConfig
from coding_agent.tools.base import (
    SCHEMA_WEB_FETCH,
    SCHEMA_WEB_SEARCH,
    ToolExecutor,
)
from coding_agent.types import ToolCall, ToolResult

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Search result normaliser
# ──────────────────────────────────────────────────────────────


class _SearchHit:
    """Simple container for a search result."""

    __slots__ = ("title", "url", "snippet")

    def __init__(self, title: str, url: str, snippet: str) -> None:
        self.title = title
        self.url = url
        self.snippet = snippet


def _normalise_brave_results(data: dict[str, Any]) -> list[_SearchHit]:
    """Parse Brave Search API response."""
    hits: list[_SearchHit] = []
    for item in data.get("web", {}).get("results", []):
        hits.append(
            _SearchHit(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("description", ""),
            )
        )
    return hits


def _normalise_tavily_results(data: dict[str, Any]) -> list[_SearchHit]:
    """Parse Tavily API response."""
    hits: list[_SearchHit] = []
    for item in data.get("results", []):
        hits.append(
            _SearchHit(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
            )
        )
    return hits


def _normalise_exa_results(data: dict[str, Any]) -> list[_SearchHit]:
    """Parse Exa API response."""
    hits: list[_SearchHit] = []
    for item in data.get("results", []):
        hits.append(
            _SearchHit(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("text", "")[:300],
            )
        )
    return hits


def _format_hits(hits: list[_SearchHit], max_results: int) -> str:
    """Format search hits into a concise text block for the LLM."""
    if not hits:
        return "No results found."
    lines: list[str] = []
    for i, h in enumerate(hits[:max_results], 1):
        snippet = h.snippet[:200] + "..." if len(h.snippet) > 200 else h.snippet
        lines.append(f"{i}. {h.title}\n   {h.url}\n   {snippet}")
    return "\n\n".join(lines)


# ──────────────────────────────────────────────────────────────
# HTML content extractor (lightweight, no BeautifulSoup)
# ──────────────────────────────────────────────────────────────


# Sanitization prepass: normalize whitespace inside tags so closing tag
# patterns like </script >, </script\t\n> become </script>
_TAG_WS_RE = re.compile(r"(</\w+)\s+(>)")

# Tags whose content carries no readable text (handles whitespace in closing tags)
_BLOCK_TAG_RE = re.compile(
    r"<(script|style|svg|math|iframe|embed|object|noscript)[^>]*>.*?</\1\s*>",
    re.DOTALL | re.IGNORECASE,
)

# Comments, CDATA, processing instructions
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_CDATA_RE = re.compile(r"<!\[CDATA\[.*?\]\]>", re.DOTALL)
_PI_RE = re.compile(r"<\?.*?\?>", re.DOTALL)

# Event handler attributes (onclick, onload, etc.)
_EVENT_RE = re.compile(r"\s+on\w+\s*=\s*(?:\"[^\"]*\"|'[^']*')", re.IGNORECASE)

# javascript:/vbscript: in href/src
_JS_PROTO_RE = re.compile(
    r"""\s+(?:href|src|action)\s*=\s*(?:"javascript:[^"]*"|'javascript:[^']*')""",
    re.IGNORECASE,
)

_MULTI_SPACE_RE = re.compile(r"\s+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def _extract_text_from_html(html: str) -> str:
    """
    Extract readable text from HTML by stripping tags.

    This is a lightweight alternative to BeautifulSoup — good enough
    for documentation pages and articles, not for complex SPAs.
    """
    # Sanitization prepass: normalize whitespace in closing tags
    # e.g. </script > → </script>, </style\t\n> → </style>
    text = _TAG_WS_RE.sub(r"\1\2", html)

    # Remove block content that carries no readable text
    text = _BLOCK_TAG_RE.sub("", text)
    # Remove comments, CDATA, processing instructions
    text = _COMMENT_RE.sub("", text)
    text = _CDATA_RE.sub("", text)
    text = _PI_RE.sub("", text)
    # Remove event handlers and javascript: URLs
    text = _EVENT_RE.sub("", text)
    text = _JS_PROTO_RE.sub("", text)
    # Replace <br> and block tags with newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    tag_pattern = r"</(p|div|h[1-6]|li|tr|section|article|blockquote|pre|td|th)\s*>"
    text = re.sub(tag_pattern, "\n", text, flags=re.IGNORECASE)
    # Strip remaining tags (with re.DOTALL to handle newlines in tag content)
    text = re.sub(r"<[^>]+>", "", text)
    # Decode common HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    text = text.replace("&ndash;", "–").replace("&mdash;", "—")
    # Normalise whitespace
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


# ──────────────────────────────────────────────────────────────
# WebTools executor
# ──────────────────────────────────────────────────────────────


class WebTools(ToolExecutor):
    """
    Web search and fetch tools.

    Backend is selected via config (brave / tavily / exa).
    API keys are read from environment variables.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(config.tools.web.timeout_seconds, connect=5.0),
            follow_redirects=True,
        )

    # ── Schema ────────────────────────────────────────────────

    def schemas(self) -> list[Any]:
        return [SCHEMA_WEB_SEARCH, SCHEMA_WEB_FETCH]

    # ── Dispatch ──────────────────────────────────────────────

    def _dispatch(self) -> dict[str, Callable[[ToolCall], Awaitable[ToolResult]]]:
        return {
            "web_search": self._web_search,
            "web_fetch": self._web_fetch,
        }

    # ── web_search ────────────────────────────────────────────

    async def _web_search(self, call: ToolCall) -> ToolResult:
        """Search the web using the configured backend."""
        query = call.arguments.get("query", "")
        if not query:
            return self._error_result(call, "Error: search query is empty", "empty_query")

        max_results = call.arguments.get("max_results", self.config.tools.web.max_results)
        backend = self.config.tools.web.backend

        try:
            if backend == "brave":
                output = await self._search_brave(query, max_results)
            elif backend == "tavily":
                output = await self._search_tavily(query, max_results)
            elif backend == "exa":
                output = await self._search_exa(query, max_results)
            else:
                return self._error_result(
                    call,
                    f"Error: unknown web search backend '{backend}'",
                    f"unknown_backend: {backend}",
                )
        except httpx.HTTPStatusError as exc:
            return self._error_result(
                call,
                f"Search API returned HTTP {exc.response.status_code}",
                str(exc),
            )
        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            return self._error_result(
                call,
                f"Search API connection error: {exc}",
                str(exc),
            )

        return self._success_result(call, output)

    # ── Brave Search ──────────────────────────────────────────

    async def _search_brave(self, query: str, max_results: int) -> str:
        """
        Search using Brave Search API.

        Requires BRAVE_API_KEY environment variable.
        Free tier: 2000 queries/month.
        """
        api_key = os.environ.get("BRAVE_API_KEY", "")
        if not api_key:
            return "Error: BRAVE_API_KEY environment variable not set"

        resp = await self._http.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
            },
            params={
                "q": query,
                "count": max_results,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        hits = _normalise_brave_results(data)
        return _format_hits(hits, max_results)

    # ── Tavily Search ─────────────────────────────────────────

    async def _search_tavily(self, query: str, max_results: int) -> str:
        """
        Search using Tavily API.

        Requires TAVILY_API_KEY environment variable.
        Free tier: 1000 queries/month.
        """
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            return "Error: TAVILY_API_KEY environment variable not set"

        resp = await self._http.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": False,
                "include_raw_content": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        hits = _normalise_tavily_results(data)
        return _format_hits(hits, max_results)

    # ── Exa Search ────────────────────────────────────────────

    async def _search_exa(self, query: str, max_results: int) -> str:
        """
        Search using Exa (neural search) API.

        Requires EXA_API_KEY environment variable.
        """
        api_key = os.environ.get("EXA_API_KEY", "")
        if not api_key:
            return "Error: EXA_API_KEY environment variable not set"

        resp = await self._http.post(
            "https://api.exa.ai/search",
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "num_results": max_results,
                "type": "auto",
                "contents": {"text": {"maxCharacters": 300}},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        hits = _normalise_exa_results(data)
        return _format_hits(hits, max_results)

    # ── web_fetch ─────────────────────────────────────────────

    async def _web_fetch(self, call: ToolCall) -> ToolResult:
        """
        Fetch a web page and extract its text content.

        For documentation pages, this returns clean text.
        For code files on GitHub, the raw content is preferred.
        """
        url = call.arguments.get("url", "")
        if not url:
            return self._error_result(call, "Error: URL is empty", "empty_url")

        extract = call.arguments.get("extract", True)

        # Convert GitHub blob URLs to raw URLs for better extraction
        fetch_url = self._github_url_to_raw(url)

        try:
            resp = await self._http.get(
                fetch_url,
                headers={"User-Agent": "meredith/0.3"},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return self._error_result(
                call,
                f"HTTP {exc.response.status_code} fetching {url}",
                str(exc),
            )
        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            return self._error_result(
                call,
                f"Connection error fetching {url}: {exc}",
                str(exc),
            )

        content_type = resp.headers.get("content-type", "")
        body = resp.text

        # If it's already plain text or code, return as-is
        if "text/plain" in content_type or "application/json" in content_type:
            output = body[:8000]
        elif extract and "html" in content_type:
            output = _extract_text_from_html(body)
            # Limit extracted text size
            if len(output) > 8000:
                output = output[:4000] + "\n... [content truncated] ...\n" + output[-3000:]
        else:
            # Raw HTML (not extracting)
            output = body[:6000] + "\n... [HTML truncated] ..."

        return self._success_result(call, output)

    @staticmethod
    def _github_url_to_raw(url: str) -> str:
        """
        Convert a GitHub blob URL to a raw URL.

        https://github.com/owner/repo/blob/main/file.py
        → https://raw.githubusercontent.com/owner/repo/main/file.py
        """
        m = re.match(
            r"https://github\.com/([^/]+/[^/]+)/blob/([^/]+)/(.+)",
            url,
        )
        if m:
            repo = m.group(1)
            branch = m.group(2)
            path = m.group(3)
            return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
        return url

    # ── Lifecycle ─────────────────────────────────────────────

    async def close(self) -> None:
        await self._http.aclose()
