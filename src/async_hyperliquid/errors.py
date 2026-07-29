class HyperliquidError(Exception):
    """Base exception for failures reported by async-hyperliquid."""


class HttpError(HyperliquidError):
    """An HTTP request failure or non-success response."""

    def __init__(self, status: int | None = None) -> None:
        self.status = status
        message = (
            "HTTP request failed"
            if status is None
            else f"HTTP request failed with status {status}"
        )
        super().__init__(message)


class ProtocolError(HyperliquidError):
    """A response that does not match the Hyperliquid JSON protocol."""
