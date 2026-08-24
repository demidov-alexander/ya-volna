"""Pre-publish validation (spec section 18)."""

from __future__ import annotations

from yavolna.config import AppConfig
from yavolna.errors import PlaylistValidationError
from yavolna.library.models import MixResult
from yavolna.logging import get_logger

log = get_logger(__name__)


def validate_result(result: MixResult, config: AppConfig) -> list[str]:
    """Return the list of problems; empty means the playlist may be published."""
    problems: list[str] = []
    entries = result.entries

    if not entries:
        problems.append("the generated playlist is empty")
        return problems

    ids = [entry.track.provider_track_id for entry in entries]
    duplicates = len(ids) - len(set(ids))
    if duplicates:
        problems.append(f"{duplicates} duplicate track ids in the same playlist")

    unavailable = [entry.track.describe() for entry in entries if not entry.track.available]
    if unavailable:
        problems.append(
            f"{len(unavailable)} tracks are marked unavailable (first: {unavailable[0]})"
        )

    limit = config.validation.max_playlist_tracks
    if len(entries) > limit:
        problems.append(f"{len(entries)} tracks exceed validation.max_playlist_tracks={limit}")

    target = result.target_duration_seconds or config.playlist.target_duration_seconds
    tolerance = config.validation.duration_tolerance
    if target > 0 and not result.stopped_early:
        deviation = abs(result.total_duration_seconds - target) / target
        if deviation > tolerance:
            problems.append(
                f"duration {result.total_duration_seconds / 3600:.1f} h deviates "
                f"{deviation:.0%} from the {target / 3600:.1f} h target "
                f"(validation.duration_tolerance={tolerance:.0%})"
            )

    ratio_tolerance = config.validation.ratio_tolerance
    ratio_deviation = abs(result.familiar_ratio - config.mix.familiar_ratio)
    if ratio_deviation > ratio_tolerance:
        message = (
            f"familiar/discovery ratio {result.familiar_ratio:.2f}/{result.discovery_ratio:.2f} "
            f"deviates {ratio_deviation:.2f} from the configured "
            f"{config.mix.familiar_ratio:.2f}/{config.mix.discovery_ratio:.2f} "
            f"(validation.ratio_tolerance={ratio_tolerance:.2f})"
        )
        if result.stopped_early:
            # Running out of candidates is a known, logged reason for deviation.
            log.warning("%s; accepted because the run stopped early", message)
        else:
            problems.append(message)

    return problems


def ensure_valid(result: MixResult, config: AppConfig) -> None:
    problems = validate_result(result, config)
    if problems:
        raise PlaylistValidationError(
            problems,
            hint="Loosen the repetition gaps, lower playlist.target_duration_hours, "
            "or widen validation.* tolerances in config.yaml.",
        )
