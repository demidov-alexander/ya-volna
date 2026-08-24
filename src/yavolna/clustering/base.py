"""Clustering abstraction (spec section 13)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from yavolna.library.models import Track


class Clusterer(ABC):
    """Assigns an opaque cluster_id to every track.

    The scheduler must work with any number of clusters and never looks at the
    cluster names, so implementations are free to use whatever labels they like.
    """

    @abstractmethod
    def assign(self, tracks: Sequence[Track]) -> None:
        """Set `track.cluster_id` in place for every track."""

    def cluster_ids(self, tracks: Sequence[Track]) -> list[str]:
        return sorted({t.cluster_id for t in tracks if t.cluster_id})
