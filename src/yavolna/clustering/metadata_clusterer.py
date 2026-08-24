"""Coarse metadata clustering (spec section 13.1).

The point is not musicology: it is to give the scheduler a signal it can use to
stop the playlist from sitting in one style for an hour.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from yavolna.clustering.base import Clusterer
from yavolna.library.models import Track
from yavolna.library.normalization import normalize_genre

#: Provider genre code -> coarse cluster. Extendable via clustering.genre_map.
DEFAULT_GENRE_MAP: dict[str, str] = {
    # rock family
    "rock": "rock",
    "allrock": "rock",
    "hardrock": "rock",
    "prog": "rock",
    "progmetal": "metal",
    "postrock": "ambient_melodic",
    "alternative": "rock",
    "indie": "rock",
    "britishrock": "rock",
    "newwave": "rock",
    "punk": "rock",
    "postpunk": "rock",
    "grunge": "rock",
    "psychedelic": "rock",
    "stonerrock": "rock",
    "shoegaze": "rock",
    # russian-language rock family
    "rusrock": "russian_rock",
    "rusbards": "russian_rock",
    "bard": "russian_rock",
    "rusfolk": "russian_rock",
    "shanson": "russian_rock",
    # metal family
    "metal": "metal",
    "epicmetal": "metal",
    "metalcore": "metal",
    "folkmetal": "metal",
    "numetal": "metal",
    "black": "metal",
    "death": "metal",
    "doom": "metal",
    "thrash": "metal",
    "hardcore": "metal",
    "industrial": "metal",
    # electronic family
    "electronics": "electronic",
    "electronic": "electronic",
    "idm": "electronic",
    "breakbeat": "electronic",
    "dnb": "electronic",
    "dubstep": "electronic",
    "trip": "electronic",
    "triphop": "electronic",
    "experimental": "electronic",
    "techno": "techno",
    "minimal": "techno",
    "house": "techno",
    "deephouse": "techno",
    "techhouse": "techno",
    "trance": "techno",
    "psytrance": "techno",
    "hardstyle": "techno",
    "dance": "dance",
    "eurodance": "dance",
    "disco": "dance",
    "edmpop": "dance",
    # calm / atmospheric
    "ambient": "ambient_melodic",
    "newage": "ambient_melodic",
    "relax": "ambient_melodic",
    "lounge": "ambient_melodic",
    "chillout": "ambient_melodic",
    "meditation": "ambient_melodic",
    "soundtrack": "ambient_melodic",
    "films": "ambient_melodic",
    "videogame": "ambient_melodic",
    "modernclassical": "ambient_melodic",
    "classical": "ambient_melodic",
    "classicalmasterpieces": "ambient_melodic",
    # pop family
    "pop": "pop",
    "ruspop": "pop",
    "foreignpop": "pop",
    "kpop": "pop",
    "jpop": "pop",
    "indiepop": "pop",
    "estrada": "pop",
    "local-indie": "pop",
    # hip-hop family
    "rap": "hiphop",
    "hiphop": "hiphop",
    "rusrap": "hiphop",
    "foreignrap": "hiphop",
    "phonk": "hiphop",
    "trap": "hiphop",
    "grime": "hiphop",
    # soul / jazz / world
    "jazz": "jazz_soul",
    "blues": "jazz_soul",
    "soul": "jazz_soul",
    "funk": "jazz_soul",
    "rnb": "jazz_soul",
    "reggae": "jazz_soul",
    "ska": "jazz_soul",
    "dub": "jazz_soul",
    "folk": "folk_world",
    "world": "folk_world",
    "country": "folk_world",
    "latinfolk": "folk_world",
    "eastern": "folk_world",
    "celtic": "folk_world",
}


class MetadataClusterer(Clusterer):
    """Maps provider genres to coarse clusters, with artist-based back-fill."""

    def __init__(
        self,
        *,
        genre_map: dict[str, str] | None = None,
        fallback_cluster: str = "other",
    ) -> None:
        merged = dict(DEFAULT_GENRE_MAP)
        for genre, cluster in (genre_map or {}).items():
            merged[normalize_genre(genre)] = cluster
        self._genre_map = merged
        self._fallback = fallback_cluster

    def assign(self, tracks: Sequence[Track]) -> None:
        # Pass 1: direct genre lookup.
        undecided: list[Track] = []
        for track in tracks:
            cluster = self._from_genres(track)
            if cluster is None:
                undecided.append(track)
            track.cluster_id = cluster

        # Pass 2: inherit the dominant cluster of the artist's other tracks.
        artist_votes: dict[str, Counter[str]] = {}
        for track in tracks:
            if track.cluster_id is None:
                continue
            for artist_id in track.artist_ids:
                artist_votes.setdefault(artist_id, Counter())[track.cluster_id] += 1

        for track in undecided:
            votes: Counter[str] = Counter()
            for artist_id in track.artist_ids:
                votes.update(artist_votes.get(artist_id, Counter()))
            track.cluster_id = votes.most_common(1)[0][0] if votes else self._fallback

    def _from_genres(self, track: Track) -> str | None:
        for genre in track.genres:
            cluster = self._genre_map.get(normalize_genre(genre))
            if cluster:
                return cluster
        return None
