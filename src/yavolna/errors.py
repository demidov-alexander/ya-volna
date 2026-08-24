"""Exception hierarchy (spec section 23).

Every user-facing failure should be one of these: the CLI turns them into a
short actionable message and hides the traceback unless --debug is used.
"""

from __future__ import annotations


class YaVolnaError(Exception):
    """Base class for all expected application errors."""

    exit_code: int = 1

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class ConfigurationError(YaVolnaError):
    exit_code = 2


class AuthenticationError(YaVolnaError):
    exit_code = 3


class ProviderError(YaVolnaError):
    exit_code = 4


class RecommendationError(YaVolnaError):
    exit_code = 5


class PlaylistWriteError(YaVolnaError):
    exit_code = 6


class DatabaseError(YaVolnaError):
    exit_code = 7


class PlaylistValidationError(YaVolnaError):
    """Raised when the generated playlist fails pre-publish validation."""

    exit_code = 8

    def __init__(self, problems: list[str], *, hint: str | None = None) -> None:
        self.problems = problems
        super().__init__(
            "Generated playlist failed validation:\n  - " + "\n  - ".join(problems), hint=hint
        )
