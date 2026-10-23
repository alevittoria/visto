"""Bounded W3C/Appium HTTP transport, independent of the device platform."""

import http.client
import json
from typing import Protocol
from urllib.parse import urlsplit

from visto.application.ports import PortError

MAX_RESPONSE = 32 * 1024 * 1024


class Wire(Protocol):
    def request(self, method: str, path: str, body: dict | None, timeout_ms: int) -> dict: ...


class CommandError(PortError):
    """W3C error answer; `message` is the server's text, for adapter diagnosis only."""

    def __init__(self, summary: str, message: str):
        super().__init__(summary)
        self.message = message


class HttpWire:
    """No redirects, proxy discovery, raw error logging or automatic retries."""

    def __init__(self, server_url: str):
        parsed = urlsplit(server_url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Expected an Appium HTTP(S) URL without credentials/query")
        self._url = parsed

    def request(self, method: str, path: str, body: dict | None, timeout_ms: int) -> dict:
        # AppiumSession._request re-raises every wire failure with its own component
        # prefix, so these messages stay internal and name no platform.
        connection_class = (
            http.client.HTTPSConnection
            if self._url.scheme == "https"
            else http.client.HTTPConnection
        )
        connection = connection_class(self._url.hostname, self._url.port, timeout=timeout_ms / 1000)
        try:
            connection.request(
                method,
                self._url.path.rstrip("/") + path,
                body=None if body is None else json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE:
                raise PortError("appium: HTTP failure")
            try:
                result = json.loads(data)
            except ValueError:
                result = None
            # https://w3c.github.io/webdriver/#errors: failures carry error and message.
            value = result.get("value") if isinstance(result, dict) else None
            if isinstance(value, dict) and "error" in value:
                message = value.get("message")
                raise CommandError(
                    "appium: command failure", message if isinstance(message, str) else ""
                )
            if response.status < 200 or response.status >= 300:
                raise PortError("appium: HTTP failure")
            if not isinstance(result, dict) or "value" not in result:
                raise PortError("appium: malformed response")
            return result
        except (OSError, ValueError, http.client.HTTPException):
            raise PortError("appium: transport failure") from None
        finally:
            connection.close()
