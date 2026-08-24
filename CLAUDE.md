# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**YaVolna** (`ya-volna` on GitHub, `yavolna` as the Python package and CLI) — a self-hosted CLI that builds one long (12 h default) style-mixing daily playlist in Yandex Music from liked tracks plus recommendations.

`yandex_daily_mix_spec.md` is the design document. Docstrings reference its section numbers; section 36 was added during implementation and documents the playlist rotation modes. Deviating from the spec on purpose means updating the spec in the same change.

Central principle: **the provider suggests candidates; YaVolna decides what plays next.** All sequencing policy lives in `mixing/`, never delegated to Yandex recommendations.

## Commands

```bash
pip install -e ".[dev]"

pytest                                    # full suite; must pass with no Yandex account
pytest tests/test_scheduler.py::test_name # single test
ruff check . && ruff format --check .
mypy

yavolna --provider fake generate --dry-run --duration-hours 2   # offline end-to-end run
yavolna validate-config                   # config + credentials, no network
yavolna generate --dry-run --seed 42      # full selection, JSON export, no remote writes
```

`--provider fake` swaps in `providers/fake.py`, a deterministic synthetic library — use it for any manual check that would otherwise need a token. Global options (`--config`, `--log-level`, `--debug`, `--provider`) must come *before* the subcommand.

## Architecture

Pipeline, orchestrated by `services/generate_mix.py`: load config → auth → liked library → local history (SQLite) → optional remote history → cluster → familiar pool → seed groups → discovery candidates → scheduler → validate → publish → commit run.

Layer boundaries that matter more than the file names:

- **`providers/yandex_music.py` is the only module that may import `yandex_music`** or know its data shapes. Native objects never leak past it; everything else uses the `Track`/`Playlist` dataclasses in `library/models.py`. `providers/base.py` defines the interface; `providers/fake.py` implements it in memory.
- **`mixing/` is provider-neutral** and knows nothing about Yandex.
- **Cluster ids are opaque to the scheduler.** `clustering/` assigns them from genre metadata (with artist-majority back-fill); the scheduler works with any number of clusters and never references a cluster name.
- **SQLite is the anti-repetition memory** (`generation_runs`, `playlist_entries`, `track_state`, `managed_playlists`), independent of whether Yandex history is available.

## Invariants

- **Write ordering:** build → validate → replace remote playlist → *then* `Repository.commit_run` in one transaction. A failed upload must leave the previous playlist and the local history untouched.
- **Scheduler is not a shuffle:** score candidates (`mixing/scorer.py`), take a top window, weighted-random inside it. Relaxation is ordered — cluster → album → artist → cooldown → ratio deviation → stop early — and each step is logged and counted in `MixResult.relaxation_counts`. Hard filters (unavailable, duplicate) are never relaxed.
- **Randomness is injected**, never module-level `random`; `--seed` must reproduce a run exactly.
- **Duration, not track count**, is the user-facing target; missing durations fall back to `selection.fallback_track_duration_seconds` and the fallback is logged.
- **Secrets come from env/`.env` only.** `load_config` rejects credential-like keys in YAML; all logging goes through `logging.RedactingFilter`. Never add a log line that formats a raw provider request/header.
- **`playlist.keep_daily_playlists` is the only deletion path:** off by default, limited to playlists recorded in `managed_playlists`, never during `--dry-run`, and a failed delete is logged and skipped.
- Errors reaching the user are `YaVolnaError` subclasses with a `hint` and a distinct exit code; tracebacks appear only with `--debug`.

## Testing notes

- `tests/__init__.py` exists on purpose: the `yandex-music` distribution installs its own top-level `tests` package into site-packages, which shadows this one otherwise.
- Adapter tests use a `StubClient` (`tests/test_yandex_provider.py`) rather than the real library; keep them in sync with the methods the adapter actually calls (`users_likes_tracks`, `tracks`, `tracks_similar`, `users_playlists*`, `queues_list`, `rotor_station_tracks`).
- Ruff has `E501` disabled deliberately: the formatter owns line length and cannot split long SQL/help strings.
