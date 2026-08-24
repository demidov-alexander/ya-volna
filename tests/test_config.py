from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from yavolna.config import (
    TOKEN_ENV_VAR,
    AppConfig,
    PlaylistMode,
    load_config,
    load_secrets,
)
from yavolna.errors import ConfigurationError


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_match_the_documented_policy():
    config = AppConfig()
    assert config.mix.familiar_ratio == 0.65
    assert config.mix.discovery_ratio == 0.35
    assert config.repetition.track_cooldown_days == 10
    assert config.repetition.favorite_track_cooldown_days == 4
    assert config.repetition.same_artist_gap_tracks == 20
    assert config.repetition.same_album_gap_tracks == 40
    assert config.repetition.same_cluster_gap_tracks == 3
    assert config.playlist.target_duration_hours == 48
    assert config.playlist.mode is PlaylistMode.REPLACE


@pytest.mark.parametrize(
    ("familiar", "discovery"),
    [(0.65, 0.35), (1.0, 0.0), (0.0, 1.0), (0.5, 0.5)],
)
def test_valid_ratio_combinations(familiar, discovery):
    config = AppConfig.model_validate(
        {"mix": {"familiar_ratio": familiar, "discovery_ratio": discovery}}
    )
    assert config.mix.familiar_ratio == familiar


@pytest.mark.parametrize(("familiar", "discovery"), [(0.7, 0.4), (0.5, 0.4), (0.0, 0.0)])
def test_ratios_must_sum_to_one(familiar, discovery, tmp_path):
    path = write(tmp_path, f"mix:\n  familiar_ratio: {familiar}\n  discovery_ratio: {discovery}\n")
    with pytest.raises(ConfigurationError, match=r"must equal 1\.0"):
        load_config(path)


def test_ratios_outside_zero_one_are_rejected(tmp_path):
    path = write(tmp_path, "mix:\n  familiar_ratio: 1.4\n  discovery_ratio: -0.4\n")
    with pytest.raises(ConfigurationError):
        load_config(path)


def test_unknown_keys_are_rejected(tmp_path):
    path = write(tmp_path, "playlist:\n  target_duration_hour: 48\n")
    with pytest.raises(ConfigurationError, match="target_duration_hour"):
        load_config(path)


def test_secrets_in_yaml_are_rejected(tmp_path):
    path = write(tmp_path, "playlist:\n  name: x\ntoken: abc123\n")
    with pytest.raises(ConfigurationError, match="credential-like keys"):
        load_config(path)


def test_missing_explicit_config_is_an_error(tmp_path):
    with pytest.raises(ConfigurationError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_missing_default_config_falls_back_to_defaults(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert load_config(None).playlist.name == "Daily Chaos"


def test_invalid_yaml_is_reported(tmp_path):
    path = write(tmp_path, "playlist: [unclosed\n")
    with pytest.raises(ConfigurationError, match="not valid YAML"):
        load_config(path)


def test_daily_template_requires_date_placeholder(tmp_path):
    path = write(tmp_path, 'playlist:\n  daily_name_template: "{name} today"\n')
    with pytest.raises(ConfigurationError, match=r"\{date\}"):
        load_config(path)


def test_daily_template_rejects_unknown_placeholders(tmp_path):
    path = write(tmp_path, 'playlist:\n  daily_name_template: "{name} {date} {mood}"\n')
    with pytest.raises(ConfigurationError, match="unknown placeholders"):
        load_config(path)


def test_date_format_must_contain_directives(tmp_path):
    path = write(tmp_path, 'playlist:\n  date_format: "today"\n')
    with pytest.raises(ConfigurationError, match="strftime"):
        load_config(path)


def test_title_for_depends_on_mode():
    replace = AppConfig().playlist
    assert replace.title_for("2026-08-24") == "Daily Chaos"

    daily = AppConfig.model_validate({"playlist": {"mode": "daily_new"}}).playlist
    label = date(2026, 8, 24).strftime(daily.date_format)
    assert daily.title_for(label) == "Daily Chaos 2026-08-24"


def test_custom_daily_template():
    playlist = AppConfig.model_validate(
        {"playlist": {"mode": "daily_new", "daily_name_template": "{date} · {name}"}}
    ).playlist
    assert playlist.title_for("24.08") == "24.08 · Daily Chaos"


def test_log_level_is_validated(tmp_path):
    path = write(tmp_path, 'runtime:\n  log_level: "LOUD"\n')
    with pytest.raises(ConfigurationError, match="log_level"):
        load_config(path)


def test_environment_wins_over_dotenv(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(f"{TOKEN_ENV_VAR}=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv(TOKEN_ENV_VAR, "from-environment")
    secrets = load_secrets(env_file=tmp_path / ".env")
    assert secrets is not None
    assert secrets.yandex_music_token == "from-environment"


def test_dotenv_is_used_when_environment_is_empty(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(f"{TOKEN_ENV_VAR}=from-dotenv\n", encoding="utf-8")
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    secrets = load_secrets(env_file=tmp_path / ".env")
    assert secrets is not None
    assert secrets.yandex_music_token == "from-dotenv"


def test_missing_token_is_actionable(monkeypatch, tmp_path):
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    with pytest.raises(ConfigurationError) as excinfo:
        load_secrets(env_file=tmp_path / "absent.env")
    assert TOKEN_ENV_VAR in str(excinfo.value)
    assert excinfo.value.hint


def test_optional_secrets_return_none(monkeypatch, tmp_path):
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    assert load_secrets(env_file=tmp_path / "absent.env", required=False) is None


def test_secrets_never_render_the_token(monkeypatch, tmp_path):
    monkeypatch.setenv(TOKEN_ENV_VAR, "super-secret-token")
    secrets = load_secrets(env_file=None)
    assert secrets is not None
    assert "super-secret-token" not in repr(secrets)
    assert "super-secret-token" not in str(secrets)
