# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `inspect-clusters` now lists the genres that ended up in the fallback cluster, so
  filling in `clustering.genre_map` stops being guesswork.

### Changed

- Default playlist name is now `YaVolna`, and the default
  `playlist.target_duration_hours` is 12 rather than 48. A 48 h target needs roughly
  4,000 liked tracks to fill without exhausting the familiar pool; 12 h is reachable for
  an ordinary library, and the setting is there for anyone who wants more.
- CI now tests Python 3.14 alongside 3.12 and 3.13, so the Docker base image can
  track the current Python release.

### Fixed

- `mix.exploratory_ratio_within_discovery` is now what its name says: a share of the
  discovery half, steered by a two-sided quota. It used to be a constant score bonus,
  which let the deliberately odd seed groups crowd out the taste-adjacent
  recommendations almost entirely (96% of discovery instead of the configured 25%).
- Genre codes are also looked up without their trailing `genre` suffix, because Yandex
  Music returns several in both forms (`phonkgenre`, `edmgenre`, `folkgenre`,
  `triphopgenre`). Added the codes observed in a real library: `edm`, `bass`,
  `rusestrada`, `gothicmetal`, `alternativemetal`, `eurofolk`, `smoothjazz`,
  `bollywood`, `foreignbard`, `folkrock`.
- The same recording liked twice under different provider ids no longer appears twice
  in one generated playlist: the duplicate guard now also compares normalized
  title/artist, not just the track id.

### Security

- Tracebacks printed by the interpreter (`--debug`, or a crash) now pass through the
  secret-redaction filter; previously only log records did.
- Warn when `.env` is readable by other users.

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

[Unreleased]: https://github.com/demidov-alexander/ya-volna/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/demidov-alexander/ya-volna/releases/tag/v0.1.0
