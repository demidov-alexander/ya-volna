"""Candidate pools for the two playlist sources."""

from __future__ import annotations

import random

from yavolna.library.models import SourceType, Track


class CandidatePool:
    """A consumable pool of tracks for one source.

    `sample()` bounds how many candidates are scored per position, which keeps a
    750-track playlist over a few thousand candidates fast without changing the
    outcome for a fixed seed.
    """

    def __init__(self, source: SourceType, tracks: list[Track]) -> None:
        self.source = source
        self._tracks: list[Track] = list(tracks)
        self._used: set[str] = set()

    def __len__(self) -> int:
        return len(self._tracks) - len(self._used)

    @property
    def total(self) -> int:
        return len(self._tracks)

    def take(self, track: Track) -> None:
        self._used.add(track.provider_track_id)
        if len(self._used) > max(64, len(self._tracks) // 4):
            self._compact()

    def _compact(self) -> None:
        self._tracks = [t for t in self._tracks if t.provider_track_id not in self._used]
        self._used.clear()

    def remaining(self) -> list[Track]:
        return [t for t in self._tracks if t.provider_track_id not in self._used]

    def sample(self, rng: random.Random, cap: int) -> list[Track]:
        remaining = self.remaining()
        if len(remaining) <= cap:
            return remaining
        return rng.sample(remaining, cap)


class PoolSet:
    def __init__(self, familiar: list[Track], discovery: list[Track]) -> None:
        self.familiar = CandidatePool(SourceType.FAMILIAR, familiar)
        self.discovery = CandidatePool(SourceType.DISCOVERY, discovery)

    def __getitem__(self, source: SourceType) -> CandidatePool:
        return self.familiar if source is SourceType.FAMILIAR else self.discovery

    def other(self, source: SourceType) -> CandidatePool:
        return self.discovery if source is SourceType.FAMILIAR else self.familiar

    @property
    def empty(self) -> bool:
        return len(self.familiar) == 0 and len(self.discovery) == 0
