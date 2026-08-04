import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import logging
from types import TracebackType
from typing import Self, cast

from aiohttp import ClientSession, ClientTimeout, web
from aiohttp.test_utils import TestServer
import pytest

from async_hyperliquid._http import _HttpTransport
from async_hyperliquid.errors import HttpError, HyperliquidError, ProtocolError
from async_hyperliquid.types import JsonObject, JsonValue


Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@asynccontextmanager
async def serve(handler: Handler) -> AsyncIterator[TestServer]:
    app = web.Application()
    app.router.add_post("/{path:.*}", handler)
    server = TestServer(app)
    await server.start_server()
    try:
        yield server
    finally:
        await server.close()


class StubResponse:
    status = 200

    def __init__(self, value: JsonValue) -> None:
        self.value = value
        self.json_calls = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def json(self, *, content_type: None) -> JsonValue:
        self.json_calls += 1
        return self.value


class StubSession:
    closed = False

    def __init__(self, response: StubResponse) -> None:
        self.response = response
        self.timeout: ClientTimeout | None = None
        self.url: str | None = None
        self.payload: JsonObject | None = None
        self.allow_redirects: bool | None = None

    def post(
        self,
        url: str,
        *,
        json: JsonObject,
        timeout: ClientTimeout,
        allow_redirects: bool,
    ) -> StubResponse:
        self.url = url
        self.payload = json
        self.timeout = timeout
        self.allow_redirects = allow_redirects
        return self.response


async def test_post_json_decodes_once_and_applies_timeout_to_borrowed_session() -> None:
    response = StubResponse({"ok": True})
    session = StubSession(response)
    transport = _HttpTransport(session=cast(ClientSession, session))
    payload: JsonObject = {"type": "allMids"}

    await transport.open()
    result = await transport.post_json("https://example.test/info", payload)
    await transport.close()

    assert result == {"ok": True}
    assert response.json_calls == 1
    assert session.url == "https://example.test/info"
    assert session.payload is payload
    assert session.allow_redirects is False
    assert session.timeout is not None
    assert session.timeout.total == 15
    assert session.timeout.connect == 3
    assert session.timeout.sock_read == 10


@pytest.mark.parametrize(
    "timeout",
    [
        ClientTimeout(total=None, connect=3, sock_read=10),
        ClientTimeout(total=float("inf"), connect=3, sock_read=10),
        ClientTimeout(total=15, connect=0),
        ClientTimeout(total=15, sock_connect=float("inf")),
        ClientTimeout(total=15, sock_read=-1),
    ],
)
def test_transport_rejects_unbounded_timeouts(timeout: ClientTimeout) -> None:
    with pytest.raises(ValueError, match="finite"):
        _HttpTransport(timeout=timeout)


def test_transport_accepts_a_finite_total_without_phase_budgets() -> None:
    timeout = ClientTimeout(total=5)

    transport = _HttpTransport(timeout=timeout)

    assert transport._timeout is timeout


async def test_non_success_status_is_sanitized_without_decoding_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def reject(request: web.Request) -> web.Response:
        return web.json_response({"error": "response-body-secret"}, status=429)

    caplog.set_level(logging.DEBUG, logger="async_hyperliquid._http")
    payload: JsonObject = {"type": "order", "signature": "signature-secret"}
    async with serve(reject) as server:
        url = str(
            server.make_url("/provider-path-secret/exchange")
            .with_user("userinfo-secret")
            .with_password("password-secret")
            .with_query(api_key="query-secret")
        )
        async with _HttpTransport() as transport:
            with pytest.raises(HttpError) as caught:
                await transport.post_json(url, payload)

    assert caught.value.status == 429
    assert isinstance(caught.value, HyperliquidError)
    rendered = f"{caught.value!r}\n{caught.value}\n{caplog.text}"
    for secret in (
        "provider-path-secret",
        "userinfo-secret",
        "password-secret",
        "query-secret",
        "signature-secret",
        "response-body-secret",
    ):
        assert secret not in rendered


async def test_invalid_json_success_raises_sanitized_protocol_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def invalid_json(request: web.Request) -> web.Response:
        return web.Response(text="response-body-secret")

    caplog.set_level(logging.DEBUG, logger="async_hyperliquid._http")
    async with serve(invalid_json) as server:
        url = str(
            server.make_url("/provider-path-secret/info").with_query(
                api_key="query-secret"
            )
        )
        async with _HttpTransport() as transport:
            with pytest.raises(ProtocolError) as caught:
                await transport.post_json(url, {"type": "allMids"})

    rendered = f"{caught.value!r}\n{caught.value}\n{caplog.text}"
    for secret in ("provider-path-secret", "query-secret", "response-body-secret"):
        assert secret not in rendered


async def test_invalid_url_is_wrapped_without_exposing_credentials() -> None:
    url = "http://userinfo-secret:password-secret@[invalid/provider-secret?key=query-secret"

    async with _HttpTransport() as transport:
        with pytest.raises(HttpError) as caught:
            await transport.post_json(url, {"signature": "signature-secret"})

    assert caught.value.status is None
    rendered = f"{caught.value!r}\n{caught.value}"
    for secret in (
        "userinfo-secret",
        "password-secret",
        "provider-secret",
        "query-secret",
        "signature-secret",
    ):
        assert secret not in rendered


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "allMids"},
        {"action": {"type": "order"}, "nonce": 1, "signature": {"r": "x"}},
    ],
)
async def test_post_json_never_forwards_payloads_through_redirects(
    payload: JsonObject,
) -> None:
    redirected_requests = 0

    async def redirect(request: web.Request) -> web.Response:
        nonlocal redirected_requests
        if request.path == "/target":
            redirected_requests += 1
            return web.json_response({"ok": True})
        return web.Response(status=307, headers={"Location": "/target"})

    async with serve(redirect) as server:
        async with _HttpTransport() as transport:
            with pytest.raises(HttpError) as caught:
                await transport.post_json(str(server.make_url("/source")), payload)

    assert caught.value.status == 307
    assert redirected_requests == 0


async def test_total_timeout_is_enforced() -> None:
    async def slow(request: web.Request) -> web.Response:
        await asyncio.sleep(0.1)
        return web.json_response({"ok": True})

    timeout = ClientTimeout(total=0.02, connect=0.01, sock_read=0.01)
    async with serve(slow) as server:
        async with _HttpTransport(timeout=timeout) as transport:
            with pytest.raises(asyncio.TimeoutError):
                await transport.post_json(str(server.make_url("/info")), {})


async def test_cancellation_propagates_and_transport_remains_usable() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    request_count = 0

    async def handler(request: web.Request) -> web.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            started.set()
            await release.wait()
        return web.json_response({"request": request_count})

    async with serve(handler) as server:
        async with _HttpTransport() as transport:
            request = asyncio.create_task(
                transport.post_json(str(server.make_url("/info")), {})
            )
            await started.wait()
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request

            release.set()
            assert await transport.post_json(str(server.make_url("/info")), {}) == {
                "request": 2
            }


async def test_owned_session_reuses_a_connection_for_sequential_requests() -> None:
    connections: set[int] = set()

    async def handler(request: web.Request) -> web.Response:
        connections.add(id(request.transport))
        return web.json_response({"ok": True})

    async with serve(handler) as server:
        async with _HttpTransport() as transport:
            url = str(server.make_url("/info"))
            await transport.post_json(url, {})
            await transport.post_json(url, {})

    assert len(connections) == 1
