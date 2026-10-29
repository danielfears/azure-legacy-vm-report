"""HTTP transport abstraction so the ARM client, Retail Prices client and auth can be tested offline."""

from __future__ import annotations

import http.client
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, Mapping, Optional


@dataclass
class Response:
    status: int
    headers: Dict[str, str]
    body: bytes


class TransportError(Exception):
    """The request could not be completed (DNS, connection, TLS or timeout)."""


class Transport:
    def request(
        self, method: str, url: str, headers: Mapping[str, str], body: Optional[bytes], timeout: float,
    ) -> Response:
        raise NotImplementedError


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects, so bearer tokens cannot be forwarded to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


class UrllibTransport(Transport):
    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_NoRedirect)

    def request(
        self, method: str, url: str, headers: Mapping[str, str], body: Optional[bytes], timeout: float,
    ) -> Response:
        request = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
        try:
            with self._opener.open(request, timeout=timeout) as reply:
                return Response(reply.status, _lower(reply.headers.items()), reply.read())
        except urllib.error.HTTPError as err:
            try:
                try:
                    payload = err.read()
                except Exception:  # noqa: BLE001
                    payload = b""
                return Response(err.code, _lower(err.headers.items()), payload)
            finally:
                _close_quietly(err)
        except urllib.error.URLError as err:
            raise TransportError(str(err.reason)) from None
        except (socket.timeout, TimeoutError):
            raise TransportError("the request timed out") from None
        except (OSError, http.client.HTTPException) as err:
            raise TransportError(str(err)) from None


def _lower(items) -> Dict[str, str]:
    return {key.lower(): value for key, value in items}


def _close_quietly(handle) -> None:
    try:
        handle.close()
    except Exception:  # noqa: BLE001
        pass
