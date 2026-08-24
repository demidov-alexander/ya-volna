"""Title/track normalization and deduplication helpers."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from yavolna.library.models import Track

_NOISE_PATTERNS = (
    re.compile(r"\((?:feat|ft|with|prod)\.?[^)]*\)", re.IGNORECASE),
    re.compile(r"\[(?:feat|ft|with|prod)\.?[^\]]*\]", re.IGNORECASE),
    re.compile(
        r"\((?:[^)]*\b(?:remaster(?:ed)?|version|edit|mono|stereo|bonus)\b[^)]*)\)", re.IGNORECASE
    ),
    re.compile(r"-\s*(?:remaster(?:ed)?|single|radio\s+edit)\b.*$", re.IGNORECASE),
)
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Casefold, strip accents/punctuation and collapse whitespace."""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    for pattern in _NOISE_PATTERNS:
        text = pattern.sub(" ", text)
    text = _PUNCTUATION.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def content_key(track: Track) -> tuple[str, str]:
    """Key identifying the same recording released under different ids.

    Used to drop the "same song, different album" duplicates that
    recommendation endpoints readily return.
    """
    artist = normalize_text(track.artist_names[0]) if track.artist_names else ""
    return (normalize_text(track.title), artist)


def dedupe_tracks(tracks: Iterable[Track], *, by_content: bool = True) -> list[Track]:
    """Deduplicate by provider id, then optionally by normalized content key."""
    seen_ids: set[str] = set()
    seen_content: set[tuple[str, str]] = set()
    result: list[Track] = []
    for track in tracks:
        if track.provider_track_id in seen_ids:
            continue
        if by_content:
            key = content_key(track)
            if key != ("", "") and key in seen_content:
                continue
            seen_content.add(key)
        seen_ids.add(track.provider_track_id)
        result.append(track)
    return result


def normalize_genre(genre: str) -> str:
    return re.sub(r"[\s\-_]+", "", genre.strip().casefold())
