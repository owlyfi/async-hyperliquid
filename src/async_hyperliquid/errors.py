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


class IndeterminateActionError(HyperliquidError):
    """A signed action may have reached the exchange without a trusted reply."""

    def __init__(self, action_type: str, nonce: int) -> None:
        self.action_type = action_type
        self.nonce = nonce
        super().__init__(
            f"signed action outcome is indeterminate: type={action_type} nonce={nonce}"
        )
