# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-08-24

First public release: the MVP described in `yandex_daily_mix_spec.md`.

### Added

- `yavolna generate` — builds a duration-targeted playlist from liked tracks plus
  provider recommendations, with `--dry-run`, `--seed`, `--duration-hours` and `--mode`.
- Familiar/discovery mixing with a configurable long-term ratio.
- Coarse style clustering from genre metadata, with artist-based back-fill and a
  user-extensible genre map.
- Multi-source discovery: independent recommendation requests per cluster, recent likes,
  old likes, the underrepresented long tail, a deliberately diverse group, and "My Wave".
- Incremental scheduler with candidate scoring, a top-window weighted random draw, and an
  ordered constraint-relaxation ladder (cluster → album → artist → cooldown → ratio).
- Anti-repetition memory in local SQLite: generation runs, playlist entries, track state.
- Two playlist modes: `replace` (one playlist, contents replaced) and `daily_new` (a dated
  playlist per day), with opt-in clean-up of old daily playlists that YaVolna created.
- Pre-publish validation of duplicates, availability, duration, ratio and size.
- `inspect-library`, `inspect-clusters`, `validate-config`, `auth-check`, `history stats`.
- Provider abstraction with a Yandex Music adapter and an in-memory fake provider
  (`--provider fake`) that runs the whole pipeline offline.
- Secret handling via environment variables and `.env`, with log redaction.
- Docker image, systemd unit examples, cron documentation, CI, and a test suite that needs
  no Yandex account.

[Unreleased]: https://github.com/OWNER/ya-volna/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OWNER/ya-volna/releases/tag/v0.1.0
