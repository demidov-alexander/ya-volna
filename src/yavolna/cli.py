"""Command line interface (spec section 19)."""

from __future__ import annotations

import os
import sqlite3
import sys
import traceback
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Annotated

import typer

from yavolna import __version__
from yavolna.config import (
    DEFAULT_CONFIG_PATH,
    AppConfig,
    PlaylistMode,
    Secrets,
    load_config,
    load_secrets,
)
from yavolna.errors import YaVolnaError
from yavolna.library.models import Library
from yavolna.logging import get_logger, redaction_filter, setup_logging
from yavolna.persistence.db import connect
from yavolna.persistence.repository import Repository
from yavolna.providers.base import MusicProvider
from yavolna.providers.fake import FakeMusicProvider
from yavolna.services.generate_mix import GenerateMixService, describe_mode

log = get_logger(__name__)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="YaVolna — build a long, style-mixing daily playlist in Yandex Music.",
)
history_app = typer.Typer(no_args_is_help=True, help="Local generation history.")
app.add_typer(history_app, name="history")


@dataclass
class Context:
    config_path: Path | None
    config: AppConfig
    debug: bool
    provider_name: str

    def open_repository(self) -> Repository:
        return Repository(connect(self.config.runtime.database_path))

    def build_provider(self) -> MusicProvider:
        if self.provider_name == "fake":
            log.warning("Using the built-in fake provider: nothing will touch Yandex Music")
            return FakeMusicProvider()
        secrets = _require_secrets()
        from yavolna.providers.yandex_music import YandexMusicProvider

        return YandexMusicProvider(secrets)


def _require_secrets() -> Secrets:
    secrets = load_secrets(required=True)
    assert secrets is not None  # load_secrets raises when required and missing
    redaction_filter().add_secret(secrets.yandex_music_token)
    _warn_on_loose_env_permissions()
    return secrets


def _warn_on_loose_env_permissions(path: Path = Path(".env")) -> None:
    """A token file other local users can read is a leak waiting to happen."""
    if os.name == "nt" or not path.is_file():
        return
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:  # pragma: no cover - unreadable stat
        return
    if mode & 0o077:
        typer.secho(
            f"warning: {path} is readable by other users (mode {mode:03o}). Run: chmod 600 {path}",
            fg=typer.colors.YELLOW,
            err=True,
        )


def _install_scrubbing_excepthook() -> None:
    """Route unexpected tracebacks through the redaction filter.

    Log records are scrubbed by the logging handler, but a traceback printed by
    the interpreter (``--debug``, or a genuine crash) bypasses logging entirely
    and may carry a provider exception message. This closes that path.
    """

    def hook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
        text = "".join(traceback.format_exception(exc))
        sys.stderr.write(redaction_filter().scrub(text))

    sys.excepthook = hook


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"yavolna {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to config.yaml (defaults to ./config.yaml)."),
    ] = None,
    log_level: Annotated[
        str | None, typer.Option("--log-level", help="Override runtime.log_level.")
    ] = None,
    debug: Annotated[
        bool, typer.Option("--debug", help="Show tracebacks and debug logging.")
    ] = False,
    provider: Annotated[
        str,
        typer.Option(
            "--provider", help="Provider to use: yandex (default) or fake (offline demo)."
        ),
    ] = "yandex",
    _version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Show the version."
        ),
    ] = False,
) -> None:
    try:
        app_config = load_config(config)
    except YaVolnaError as exc:
        if debug:
            raise
        _report(exc)
        raise typer.Exit(code=exc.exit_code) from None

    level = (log_level or app_config.runtime.log_level).upper()
    if debug:
        level = "DEBUG"
    setup_logging(level)
    _install_scrubbing_excepthook()
    if provider not in {"yandex", "fake"}:
        raise typer.BadParameter("--provider must be 'yandex' or 'fake'")
    resolved = config or (DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.exists() else None)
    ctx.obj = Context(config_path=resolved, config=app_config, debug=debug, provider_name=provider)


# -- commands ----------------------------------------------------------------


@app.command()
def generate(
    ctx: typer.Context,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Select and export tracks without modifying Yandex Music."),
    ] = False,
    seed: Annotated[
        int | None, typer.Option("--seed", help="Random seed; makes the run reproducible.")
    ] = None,
    duration_hours: Annotated[
        float | None,
        typer.Option("--duration-hours", help="Override playlist.target_duration_hours."),
    ] = None,
    mode: Annotated[
        str | None,
        typer.Option(
            "--mode",
            help="Override playlist.mode: 'replace' (one playlist) or 'daily_new' (dated playlist per day).",
        ),
    ] = None,
) -> None:
    """Create or update the configured playlist."""
    context: Context = ctx.obj
    config = context.config
    if duration_hours is not None:
        config = config.model_copy(
            update={
                "playlist": config.playlist.model_copy(
                    update={"target_duration_hours": duration_hours}
                )
            }
        )
    if mode is not None:
        try:
            playlist_mode = PlaylistMode(mode)
        except ValueError as exc:
            raise typer.BadParameter("--mode must be 'replace' or 'daily_new'") from exc
        config = config.model_copy(
            update={"playlist": config.playlist.model_copy(update={"mode": playlist_mode})}
        )

    def action() -> None:
        provider = context.build_provider()
        repository = context.open_repository()
        try:
            service = GenerateMixService(
                provider=provider, config=config, repository=repository, now=datetime.now(UTC)
            )
            typer.echo(f"Playlist mode: {describe_mode(config)}")
            report = service.run(dry_run=dry_run, seed=seed)
        finally:
            repository.close()

        typer.echo("")
        for line in report.summary_lines():
            typer.echo(line)
        if dry_run:
            typer.echo("\nDry run: Yandex Music was not modified.")

    _run(context, action)


@app.command("inspect-library")
def inspect_library(ctx: typer.Context) -> None:
    """Print statistics about the liked library."""
    context: Context = ctx.obj

    def action() -> None:
        provider = context.build_provider()
        repository = context.open_repository()
        try:
            service = GenerateMixService(
                provider=provider, config=context.config, repository=repository
            )
            library = service.load_library()
        finally:
            repository.close()

        stats = library.stats(context.config.selection.fallback_track_duration_seconds)
        typer.echo(f"liked tracks:               {stats['liked_tracks']:,}")
        typer.echo(f"artists:                    {stats['artists']:,}")
        typer.echo(f"albums:                     {stats['albums']:,}")
        typer.echo(f"clusters:                   {stats['clusters']}")
        typer.echo(f"unavailable tracks:         {stats['unavailable_tracks']:,}")
        typer.echo(f"tracks without duration:    {stats['tracks_without_duration']:,}")
        hours = stats["estimated_duration_seconds"] / 3600
        typer.echo(f"estimated library duration: {hours:,.1f} h")

    _run(context, action)


@app.command("inspect-clusters")
def inspect_clusters(
    ctx: typer.Context,
    samples: Annotated[int, typer.Option("--samples", help="Sample tracks per cluster.")] = 3,
) -> None:
    """Show cluster sizes and sample tracks to diagnose poor metadata grouping."""
    context: Context = ctx.obj

    def action() -> None:
        provider = context.build_provider()
        repository = context.open_repository()
        try:
            service = GenerateMixService(
                provider=provider, config=context.config, repository=repository
            )
            library = service.load_library()
        finally:
            repository.close()
        _print_clusters(library, samples, context.config.clustering.fallback_cluster)

    _run(context, action)


def _print_clusters(library: Library, samples: int, fallback_cluster: str) -> None:
    grouped = library.by_cluster()
    total = len(library) or 1
    for cluster_id, tracks in sorted(grouped.items(), key=lambda item: -len(item[1])):
        share = len(tracks) / total
        typer.echo(f"{cluster_id:<18} {len(tracks):>6} tracks  {share:>6.1%}")
        for track in tracks[:samples]:
            genres = ", ".join(track.genres) or "no genre metadata"
            typer.echo(f"    {track.describe()}  [{genres}]")

    # The fallback cluster is where unmapped genres pile up; naming them turns
    # "why is everything in other?" into a concrete clustering.genre_map entry.
    unmapped = Counter(
        genre or "(no genre metadata)"
        for track in grouped.get(fallback_cluster, [])
        for genre in (track.genres or ("",))
    )
    if unmapped:
        typer.echo(f"\nunmapped genres in {fallback_cluster!r} (add them to clustering.genre_map):")
        for genre, count in unmapped.most_common(15):
            typer.echo(f"    {genre:<24} {count:>5} tracks")


@app.command("validate-config")
def validate_config(ctx: typer.Context) -> None:
    """Validate configuration and credentials without touching the network."""
    context: Context = ctx.obj
    config = context.config
    source = context.config_path or "built-in defaults (no config.yaml found)"
    typer.echo(f"configuration:  OK ({source})")
    typer.echo(f"playlist:       {config.playlist.name!r} — {describe_mode(config)}")
    typer.echo(f"target:         {config.playlist.target_duration_hours} h")
    typer.echo(
        f"mix:            familiar {config.mix.familiar_ratio:.2f} / "
        f"discovery {config.mix.discovery_ratio:.2f}"
    )
    typer.echo(f"database:       {config.runtime.database_path}")
    secrets = load_secrets(required=False)
    typer.echo(
        f"credentials:    {'present' if secrets else 'MISSING (YANDEX_MUSIC_TOKEN not set)'}"
    )
    if not secrets:
        raise typer.Exit(code=0)
    redaction_filter().add_secret(secrets.yandex_music_token)
    _warn_on_loose_env_permissions()


@app.command("auth-check")
def auth_check(ctx: typer.Context) -> None:
    """Verify that the credentials work against the provider."""
    context: Context = ctx.obj

    def action() -> None:
        provider = context.build_provider()
        account = provider.check_auth()
        typer.echo(f"authenticated:  {account.describe()}")

    _run(context, action)


@history_app.command("stats")
def history_stats(ctx: typer.Context) -> None:
    """Show statistics from the local generation history."""
    context: Context = ctx.obj

    def action() -> None:
        repository = context.open_repository()
        try:
            stats = repository.stats()
            top = repository.top_tracks(limit=10)
            last = repository.last_run()
        finally:
            repository.close()

        typer.echo(
            f"runs:               {stats['runs_total']} ({stats['runs_successful']} successful)"
        )
        typer.echo(f"first run:          {stats['first_run'] or '-'}")
        typer.echo(f"last run:           {stats['last_run'] or '-'}")
        typer.echo(f"known tracks:       {stats['known_tracks']:,}")
        typer.echo(f"total selections:   {stats['total_selections']:,}")
        typer.echo(f"managed playlists:  {stats['managed_playlists']}")
        if last:
            typer.echo(
                f"last playlist:      {last['playlist_title'] or '-'} "
                f"({last['familiar_count'] or 0} familiar / {last['discovery_count'] or 0} discovery)"
            )
        if top:
            typer.echo("\nmost frequently selected tracks:")
            for row in top:
                typer.echo(
                    f"  {row['provider_track_id']:<16} {row['generation_count']:>3}x  "
                    f"last: {row['last_generated_at'] or '-'}"
                )

    _run(context, action)


# -- error handling ----------------------------------------------------------


def _report(exc: YaVolnaError) -> None:
    typer.secho(f"error: {exc.message}", fg=typer.colors.RED, err=True)
    if exc.hint:
        typer.secho(f"hint:  {exc.hint}", fg=typer.colors.YELLOW, err=True)


def _run(context: Context, action: Callable[[], None]) -> None:
    """Run a command, turning expected errors into short CLI messages."""
    try:
        action()
    except YaVolnaError as exc:
        if context.debug:
            raise
        _report(exc)
        raise typer.Exit(code=exc.exit_code) from None
    except sqlite3.Error as exc:
        if context.debug:
            raise
        typer.secho(f"error: database failure: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=7) from None
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        typer.secho("interrupted", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=130) from None


def main() -> None:
    """Entry point. Config/credential failures happen before a command runs."""
    _install_scrubbing_excepthook()
    try:
        app()
    except YaVolnaError as exc:  # pragma: no cover - safety net
        if "--debug" in sys.argv:
            raise
        _report(exc)
        raise SystemExit(exc.exit_code) from None


if __name__ == "__main__":  # pragma: no cover
    main()
