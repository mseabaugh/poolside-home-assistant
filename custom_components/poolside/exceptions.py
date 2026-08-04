"""Domain exceptions for Poolside."""


class PoolsideError(Exception):
    """Base class for expected Poolside failures."""


class AuthenticationError(PoolsideError):
    """The supplied Poolside credential was rejected."""


class CannotConnectError(PoolsideError):
    """The Poolside service could not be reached."""


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
