"""HTTP client for the AITerminal Netlify Functions."""

from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx

DEFAULT_API_URL = "https://aiterminal-cloud.netlify.app"


class AITerminalError(Exception):
    """Base exception for user-safe service errors."""


class ServiceError(AITerminalError):
    """The backend returned a safe, user-facing error."""


class AITerminalClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 35.0,
    ) -> None:
        configured_url = base_url or os.getenv("AIT_TERMINAL_API_URL") or DEFAULT_API_URL
        self.base_url = configured_url.rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("AIT_TERMINAL_API_URL must use HTTPS (HTTP is allowed only for localhost).")
        if not parsed.netloc:
            raise ValueError("AIT_TERMINAL_API_URL must be an absolute URL.")
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)

    def ask(self, message: str, history: list[dict[str, str]]) -> str:
        try:
            result = self._http.post(
                "/.netlify/functions/chat",
                json={"message": message, "history": history},
            )
        except httpx.TimeoutException as exc:
            raise ServiceError("The request timed out. Please try again.") from exc
        except httpx.RequestError as exc:
            raise ServiceError("Could not connect to AITerminal. Check your internet connection and try again.") from exc
        if result.status_code == 401:
            raise ServiceError("The request was not accepted.")
        if result.status_code == 429:
            raise ServiceError(self._error_message(result, "Too many requests. Please wait and try again."))
        if result.status_code >= 500:
            raise ServiceError(self._error_message(result, "AITerminal is temporarily unavailable."))
        if result.status_code != 200:
            raise ServiceError(self._error_message(result, "The request was rejected."))
        try:
            payload = result.json()
        except ValueError as exc:
            raise ServiceError("AITerminal returned an invalid response.") from exc
        answer = payload.get("answer") if isinstance(payload, dict) else None
        if not isinstance(answer, str) or not answer.strip():
            raise ServiceError("AITerminal returned an invalid response.")
        return answer

    @staticmethod
    def _error_message(result: httpx.Response, fallback: str) -> str:
        try:
            payload = result.json()
        except ValueError:
            return fallback
        message = payload.get("error") if isinstance(payload, dict) else None
        return message if isinstance(message, str) and message else fallback

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> AITerminalClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
