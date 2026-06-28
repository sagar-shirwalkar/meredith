"""Smoke test: verify the package can be imported and version is readable."""

from __future__ import annotations

from coding_agent import __version__


def test_version() -> None:
    assert __version__ == "0.3.0"
