"""Domain exceptions for Poolside."""


class PoolsideError(Exception):
    """Base class for expected Poolside failures."""


class AuthenticationError(PoolsideError):
    """The supplied Poolside credential was rejected."""


class CannotConnectError(PoolsideError):
    """The Poolside service could not be reached."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        content_type: str | None = None,
    ) -> None:
        """Keep safe HTTP metadata without logging response bodies."""
        super().__init__(message)
        self.status = status
        self.content_type = content_type


class ProtocolError(PoolsideError):
    """A Poolside payload violated the confirmed protocol contract."""


class RemoteError(PoolsideError):
    """Poolside returned a JSON-RPC error."""


class UnsafeWriteError(PoolsideError):
    """A write was rejected by the local safety policy."""


class RestrictedControlError(UnsafeWriteError):
    """A discovered Control is currently restricted or disabled."""


class ScheduleMutationUnavailableError(UnsafeWriteError):
    """Schedule mutation is unavailable until conflict behavior is confirmed."""
