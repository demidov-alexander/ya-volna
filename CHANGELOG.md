# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-08-24

First public release: the MVP described in `yandex_daily_mix_spec.md`, verified end to end
against a real Yandex Music account.

### Added

- `yavolna generate` — builds a duration-targeted playlist from liked tracks plus
  provider recommendations, with `--dry-run`, `--seed`, `--duration-hours` and `--mode`.
  Defaults to a 12-hour playlist named `YaVolna`.
- Familiar/discovery mixing with a configurable long-term ratio, and a configurable
  exploratory share within the discovery half.
- Coarse style clustering from genre metadata, with artist-based back-fill, a
  user-extensible genre map, and tolerance for the `…genre` suffix Yandex Music adds to
  some codes.
- Multi-source discovery: independent recommendation requests per cluster, recent likes,
  old likes, the underrepresented long tail, a deliberately diverse group, and "My Wave".
- Incremental scheduler with candidate scoring, a top-window weighted random draw, and an
  ordered constraint-relaxation ladder (cluster → album → artist → cooldown → ratio).
- Anti-repetition memory in local SQLite: generation runs, playlist entries, track state.
  Duplicates are caught by provider id and by normalized title/artist, so one recording
  liked twice cannot appear twice in a playlist.
- Two playlist modes: `replace` (one playlist, contents replaced) and `daily_new` (a dated
  playlist per day), with opt-in clean-up of old daily playlists that YaVolna created.
- Pre-publish validation of duplicates, availability, duration, ratio and size. The local
  history is committed only after the remote update succeeds.
- `inspect-library`, `inspect-clusters` (including the genres that fell into the fallback
  cluster), `validate-config`, `auth-check`, `history stats`.
- Provider abstraction with a Yandex Music adapter and an in-memory fake provider
  (`--provider fake`) that runs the whole pipeline offline.
- Secret handling via environment variables and `.env`: credential-like keys are rejected
  in YAML, log records and interpreter tracebacks pass through a redaction filter, and a
  world-readable `.env` is reported.
- Docker image, systemd unit examples, cron documentation, CI on Python 3.12–3.14, and a
  test suite that needs no Yandex account.

[Unreleased]: https://github.com/demidov-alexander/ya-volna/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/demidov-alexander/ya-volna/releases/tag/v0.1.0
