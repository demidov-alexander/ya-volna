from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from yavolna.cli import app
from yavolna.config import TOKEN_ENV_VAR

runner = CliRunner()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    Path("config.yaml").write_text(
        "playlist:\n"
        '  name: "CLI Mix"\n'
        "  target_duration_hours: 1\n"
        "selection:\n"
        "  minimum_liked_tracks: 5\n"
        "validation:\n"
        "  duration_tolerance: 0.25\n"
        "runtime:\n"
        '  database_path: "data/test.sqlite3"\n',
        encoding="utf-8",
    )
    return tmp_path


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "yavolna" in result.stdout


def test_help_lists_the_documented_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "generate",
        "inspect-library",
        "inspect-clusters",
        "validate-config",
        "auth-check",
        "history",
    ):
        assert command in result.stdout


def test_validate_config_without_credentials(workspace):
    result = runner.invoke(app, ["validate-config"])
    assert result.exit_code == 0
    assert "configuration:  OK" in result.stdout
    assert "MISSING" in result.stdout


def test_validate_config_reports_a_bad_config(workspace):
    Path("config.yaml").write_text(
        "mix:\n  familiar_ratio: 0.9\n  discovery_ratio: 0.5\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["validate-config"])
    assert result.exit_code == 2
    assert "must equal 1.0" in result.output


def test_generate_requires_credentials(workspace):
    result = runner.invoke(app, ["generate"])
    assert result.exit_code == 2
    assert TOKEN_ENV_VAR in result.output
    assert "hint:" in result.output


def test_dry_run_with_the_fake_provider(workspace):
    result = runner.invoke(app, ["--provider", "fake", "generate", "--dry-run", "--seed", "5"])
    assert result.exit_code == 0
    assert "Dry run: Yandex Music was not modified." in result.stdout
    exports = list(Path("data").glob("dry-run-*.json"))
    assert len(exports) == 1
    payload = json.loads(exports[0].read_text(encoding="utf-8"))
    assert payload["seed"] == 5
    assert payload["tracks"]


def test_generate_with_the_fake_provider_persists_history(workspace):
    assert runner.invoke(app, ["--provider", "fake", "generate", "--seed", "5"]).exit_code == 0
    stats = runner.invoke(app, ["history", "stats"])
    assert stats.exit_code == 0
    assert "runs:               1 (1 successful)" in stats.stdout


def test_mode_override_is_reflected(workspace):
    result = runner.invoke(
        app, ["--provider", "fake", "generate", "--dry-run", "--mode", "daily_new"]
    )
    assert result.exit_code == 0
    assert "a new dated playlist per day" in result.stdout


def test_invalid_mode_is_rejected(workspace):
    result = runner.invoke(app, ["--provider", "fake", "generate", "--mode", "weekly"])
    assert result.exit_code == 2
    assert "replace" in result.output


def test_duration_override(workspace):
    result = runner.invoke(
        app, ["--provider", "fake", "generate", "--dry-run", "--duration-hours", "2"]
    )
    assert result.exit_code == 0
    assert "of 2.0 h target" in result.stdout


def test_invalid_provider_is_rejected(workspace):
    result = runner.invoke(app, ["--provider", "spotify", "auth-check"])
    assert result.exit_code == 2


def test_inspect_library(workspace):
    result = runner.invoke(app, ["--provider", "fake", "inspect-library"])
    assert result.exit_code == 0
    assert "liked tracks:" in result.stdout
    assert "estimated library duration:" in result.stdout
    assert "top genres" in result.stdout


def test_inspect_library_hides_podcasts_from_the_fake_provider(workspace):
    result = runner.invoke(app, ["--provider", "fake", "inspect-library"])
    assert result.exit_code == 0
    assert "forchildren" not in result.stdout


def test_inspect_library_keeps_podcasts_when_allowed(workspace, tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("exclusions:\n  allowed_content_types: []\n", encoding="utf-8")
    result = runner.invoke(app, ["--config", str(config), "--provider", "fake", "inspect-library"])
    assert result.exit_code == 0
    assert "forchildren" in result.stdout


def test_validate_config_reports_the_exclusions(workspace):
    result = runner.invoke(app, ["validate-config"])
    assert result.exit_code == 0
    assert "exclusions:     content types music" in result.stdout


def test_inspect_clusters(workspace):
    result = runner.invoke(app, ["--provider", "fake", "inspect-clusters", "--samples", "1"])
    assert result.exit_code == 0
    assert "tracks" in result.stdout


def test_auth_check_with_the_fake_provider(workspace):
    result = runner.invoke(app, ["--provider", "fake", "auth-check"])
    assert result.exit_code == 0
    assert "authenticated:" in result.stdout


def test_history_stats_on_an_empty_database(workspace):
    result = runner.invoke(app, ["history", "stats"])
    assert result.exit_code == 0
    assert "runs:               0" in result.stdout


def test_error_exit_code_matches_the_error_class(workspace):
    Path("config.yaml").write_text("selection:\n  minimum_liked_tracks: 100000\n", encoding="utf-8")
    result = runner.invoke(app, ["--provider", "fake", "generate", "--dry-run"])
    assert result.exit_code == 2
    assert "minimum_liked_tracks" in result.output


def test_missing_config_file_is_reported(workspace):
    result = runner.invoke(app, ["--config", "absent.yaml", "validate-config"])
    assert result.exit_code == 2
    assert "not found" in result.output


def test_token_is_never_echoed(workspace, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, "y0_super-secret-token")
    result = runner.invoke(
        app, ["--provider", "fake", "--log-level", "DEBUG", "generate", "--dry-run"]
    )
    assert result.exit_code == 0
    assert "y0_super-secret-token" not in result.output


def test_inspect_clusters_names_unmapped_genres(workspace):
    Path("config.yaml").write_text(
        "selection:\n  minimum_liked_tracks: 5\nclustering:\n  genre_map: {}\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["--provider", "fake", "inspect-clusters"])
    assert result.exit_code == 0
    # The fake catalog is fully mapped, so the hint must stay quiet there.
    assert "unmapped genres" not in result.stdout

    Path("config.yaml").write_text(
        'selection:\n  minimum_liked_tracks: 5\nclustering:\n  genre_map:\n    rock: "other"\n',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["--provider", "fake", "inspect-clusters"])
    assert result.exit_code == 0
    assert "unmapped genres in 'other'" in result.stdout
    assert "rock" in result.stdout


def test_traceback_from_a_crash_is_scrubbed(workspace, capsys, monkeypatch):
    """A traceback printed by the interpreter must not carry the token (--debug path)."""
    from yavolna.cli import _install_scrubbing_excepthook
    from yavolna.logging import REDACTED, redaction_filter

    redaction_filter().add_secret("y0_super-secret-token")
    _install_scrubbing_excepthook()
    try:
        raise RuntimeError("provider said: OAuth y0_super-secret-token rejected")
    except RuntimeError as exc:
        sys.excepthook(type(exc), exc, exc.__traceback__)

    captured = capsys.readouterr()
    assert "y0_super-secret-token" not in captured.err
    assert REDACTED in captured.err
    assert "RuntimeError" in captured.err


def test_loose_env_permissions_are_reported(workspace, monkeypatch):
    from yavolna.cli import _warn_on_loose_env_permissions

    env = Path(".env")
    env.write_text("YANDEX_MUSIC_TOKEN=y0_whatever-token\n", encoding="utf-8")
    env.chmod(0o644)
    result = runner.invoke(app, ["validate-config"])
    assert result.exit_code == 0
    assert "readable by other users" in result.stderr

    env.chmod(0o600)
    result = runner.invoke(app, ["validate-config"])
    assert "readable by other users" not in result.stderr
    _warn_on_loose_env_permissions(Path("does-not-exist"))  # must not raise
