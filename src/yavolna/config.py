"""Configuration: behavioural settings from YAML, secrets from the environment."""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from yavolna.errors import ConfigurationError

DEFAULT_CONFIG_PATH = Path("config.yaml")
TOKEN_ENV_VAR = "YANDEX_MUSIC_TOKEN"
USER_ID_ENV_VAR = "YANDEX_MUSIC_USER_ID"


class PlaylistMode(StrEnum):
    REPLACE = "replace"
    DAILY_NEW = "daily_new"


class Visibility(StrEnum):
    PRIVATE = "private"
    PUBLIC = "public"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlaylistConfig(_Base):
    name: str = "YaVolna"
    description: str = "Automatically generated mixed-style daily playlist"
    target_duration_hours: float = Field(default=12.0, gt=0, le=24 * 30)
    mode: PlaylistMode = PlaylistMode.REPLACE
    reuse_existing_playlist: bool = True
    daily_name_template: str = "{name} {date}"
    date_format: str = "%Y-%m-%d"
    keep_daily_playlists: int = Field(default=0, ge=0)
    visibility: Visibility = Visibility.PRIVATE

    @field_validator("name")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("playlist.name must not be empty")
        return value.strip()

    @field_validator("daily_name_template")
    @classmethod
    def _template_has_date(cls, value: str) -> str:
        if "{date}" not in value:
            raise ValueError("playlist.daily_name_template must contain the {date} placeholder")
        unknown = {
            part.split("}")[0]
            for part in value.split("{")[1:]
            if part.split("}")[0] not in {"name", "date"}
        }
        if unknown:
            raise ValueError(
                f"playlist.daily_name_template has unknown placeholders: {sorted(unknown)}"
            )
        return value

    @field_validator("date_format")
    @classmethod
    def _usable_date_format(cls, value: str) -> str:
        from datetime import date

        try:
            rendered = date(2026, 1, 31).strftime(value)
        except Exception as exc:  # pragma: no cover - strftime rarely raises
            raise ValueError(f"playlist.date_format is not a valid strftime format: {exc}") from exc
        if not rendered.strip() or rendered == value:
            raise ValueError("playlist.date_format must contain strftime directives, e.g. %Y-%m-%d")
        return value

    @property
    def target_duration_seconds(self) -> int:
        return int(self.target_duration_hours * 3600)

    def title_for(self, date_label: str) -> str:
        """Playlist title for a run: constant in replace mode, dated otherwise."""
        if self.mode is PlaylistMode.DAILY_NEW:
            return self.daily_name_template.format(name=self.name, date=date_label)
        return self.name


class MixConfig(_Base):
    familiar_ratio: float = Field(default=0.65, ge=0.0, le=1.0)
    discovery_ratio: float = Field(default=0.35, ge=0.0, le=1.0)
    exploratory_ratio_within_discovery: float = Field(default=0.25, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ratios_sum_to_one(self) -> MixConfig:
        total = self.familiar_ratio + self.discovery_ratio
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"mix.familiar_ratio + mix.discovery_ratio must equal 1.0 (got {total:.4f})"
            )
        return self


class RepetitionConfig(_Base):
    track_cooldown_days: int = Field(default=10, ge=0)
    favorite_track_cooldown_days: int = Field(default=4, ge=0)
    same_artist_gap_tracks: int = Field(default=20, ge=0)
    same_album_gap_tracks: int = Field(default=40, ge=0)
    same_cluster_gap_tracks: int = Field(default=3, ge=0)


class HistoryConfig(_Base):
    local_retention_days: int = Field(default=180, ge=1)
    use_remote_listening_history: bool = True


class SelectionConfig(_Base):
    minimum_liked_tracks: int = Field(default=20, ge=1)
    random_seed: int | None = None
    prefer_high_variety: bool = True
    fallback_track_duration_seconds: int = Field(default=240, gt=0)
    max_candidates_per_step: int = Field(default=400, ge=10)


class DiscoveryConfig(_Base):
    seed_groups_max: int = Field(default=8, ge=1)
    seeds_per_group: int = Field(default=4, ge=1)
    max_candidates_per_seed: int = Field(default=20, ge=1)
    use_personal_wave: bool = True


class ClusteringConfig(_Base):
    fallback_cluster: str = "other"
    genre_map: dict[str, str] = Field(default_factory=dict)


class ExclusionsConfig(_Base):
    """What must never reach a playlist, whatever the recommendations suggest.

    Four independent questions: which ids, which content types (podcasts and
    audiobooks are not music), which provider genres, and which of YaVolna's
    own clusters.
    """

    blocked_track_ids: list[str] = Field(default_factory=list)
    blocked_artist_ids: list[str] = Field(default_factory=list)
    blocked_genres: list[str] = Field(default_factory=list)
    blocked_clusters: list[str] = Field(default_factory=list)
    #: Content types that are kept. An empty list disables the check entirely.
    allowed_content_types: list[str] = Field(default_factory=lambda: ["music"])

    @field_validator("blocked_track_ids", "blocked_artist_ids", mode="before")
    @classmethod
    def _stringify(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [str(item) for item in value]
        return value

    @field_validator("blocked_genres", "blocked_clusters", "allowed_content_types", mode="before")
    @classmethod
    def _normalize_labels(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [str(item).strip().casefold() for item in value if str(item).strip()]
        return value


class ValidationConfig(_Base):
    ratio_tolerance: float = Field(default=0.05, ge=0.0, le=1.0)
    duration_tolerance: float = Field(default=0.15, ge=0.0, le=1.0)
    max_playlist_tracks: int = Field(default=10000, ge=1)


class RuntimeConfig(_Base):
    database_path: Path = Path("data/yavolna.sqlite3")
    log_level: str = "INFO"
    dry_run_export_dir: Path = Path("data")

    @field_validator("log_level")
    @classmethod
    def _known_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"runtime.log_level must be one of {sorted(allowed)}")
        return upper


class AppConfig(_Base):
    playlist: PlaylistConfig = Field(default_factory=PlaylistConfig)
    mix: MixConfig = Field(default_factory=MixConfig)
    repetition: RepetitionConfig = Field(default_factory=RepetitionConfig)
    history: HistoryConfig = Field(default_factory=HistoryConfig)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)
    exclusions: ExclusionsConfig = Field(default_factory=ExclusionsConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)


class Secrets(BaseModel):
    """Runtime credentials. Never logged, never read from YAML."""

    model_config = ConfigDict(frozen=True)

    yandex_music_token: str
    yandex_music_user_id: str | None = None

    def __repr__(self) -> str:
        return (
            f"Secrets(yandex_music_token='***', yandex_music_user_id={self.yandex_music_user_id!r})"
        )

    __str__ = __repr__


def load_config(path: Path | str | None = None) -> AppConfig:
    """Load and validate behavioural configuration.

    A missing default config file is not an error: the built-in defaults
    (spec section 29) are used. An explicitly requested file must exist.
    """
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        if path is not None:
            raise ConfigurationError(
                f"Configuration file not found: {config_path}",
                hint="Copy config.example.yaml to config.yaml, or pass --config <path>.",
            )
        return AppConfig()

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"{config_path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigurationError(f"{config_path} must contain a YAML mapping at the top level.")

    _reject_secrets_in_yaml(raw, config_path)

    try:
        return AppConfig.model_validate(raw)
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError(f"Invalid configuration in {config_path}:\n{exc}") from exc


def _reject_secrets_in_yaml(raw: dict[str, Any], config_path: Path) -> None:
    forbidden = {"token", "yandex_music_token", "cookies", "cookie", "password", "oauth_token"}
    found = _find_keys(raw, forbidden)
    if found:
        raise ConfigurationError(
            f"{config_path} contains credential-like keys: {sorted(found)}",
            hint=f"Secrets belong in environment variables or .env ({TOKEN_ENV_VAR}), not in YAML.",
        )


def _find_keys(node: Any, needles: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and key.lower() in needles:
                found.add(key)
            found |= _find_keys(value, needles)
    elif isinstance(node, list):
        for item in node:
            found |= _find_keys(item, needles)
    return found


def load_secrets(*, env_file: Path | str | None = ".env", required: bool = True) -> Secrets | None:
    """Load credentials.

    Priority: real environment variables first, then the local .env file
    (spec section 5.2). Returns None when credentials are absent and not required.
    """
    if env_file:
        env_path = Path(env_file)
        if env_path.exists():
            load_dotenv(env_path, override=False)

    token = (os.environ.get(TOKEN_ENV_VAR) or "").strip()
    user_id = (os.environ.get(USER_ID_ENV_VAR) or "").strip() or None

    if not token:
        if not required:
            return None
        raise ConfigurationError(
            f"{TOKEN_ENV_VAR} is not set.",
            hint="Copy .env.example to .env and add your token, or export the variable. "
            "See the Authentication section of README.md.",
        )
    return Secrets(yandex_music_token=token, yandex_music_user_id=user_id)
