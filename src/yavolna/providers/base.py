"""Provider abstraction (spec section 9).

Everything Yandex-specific lives behind this interface so that API changes stay
contained and tests can run without an account.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from yavolna.library.models import PlaybackEvent, Playlist, Track


@dataclass(frozen=True, slots=True)
class AccountInfo:
    provider: str
    user_id: str | None
    login: str | None = None
    display_name: str | None = None
    has_subscription: bool | None = None

    def describe(self) -> str:
        parts = [self.display_name or self.login or "unknown account"]
        if self.user_id:
            parts.append(f"uid={self.user_id}")
        if self.has_subscription is not None:
            parts.append("subscription: " + ("yes" if self.has_subscription else "no"))
        return ", ".join(parts)


class MusicProvider(ABC):
    """Read the library, ask for recommendations, own one playlist."""

    name: str = "unknown"

    @abstractmethod
    def check_auth(self) -> AccountInfo:
        """Verify credentials. Raises AuthenticationError when they do not work."""

    @abstractmethod
    def get_liked_tracks(self) -> list[Track]:
        """All liked tracks, normalized into the internal model."""

    @abstractmethod
    def get_recent_history(self) -> list[PlaybackEvent]:
        """Recent playback events. Returns [] when the provider cannot supply them."""

    @abstractmethod
    def get_recommendations(self, seeds: Sequence[Track], *, limit: int = 20) -> list[Track]:
        """Candidate tracks similar to the given seeds."""

    @abstractmethod
    def get_or_create_playlist(
        self, title: str, *, description: str | None = None, visibility: str = "private"
    ) -> Playlist:
        """Return the playlist with this title, creating it when missing."""

    @abstractmethod
    def replace_playlist_tracks(self, playlist_id: str, tracks: Sequence[Track]) -> Playlist:
        """Replace the whole content of the playlist."""

    def list_playlists(self) -> list[Playlist]:
        """Optional: playlists owned by the account. Used for daily-playlist clean-up."""
        return []

    def delete_playlist(self, playlist_id: str) -> None:
        """Optional: delete a playlist. Only ever called for playlists we created."""
        raise NotImplementedError(f"{self.name} provider cannot delete playlists")

    def get_personal_wave(self, *, limit: int = 30) -> list[Track]:
        """Optional extra discovery source (Yandex "My Wave" and equivalents)."""
        return []
