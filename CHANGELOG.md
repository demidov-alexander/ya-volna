# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-08-27

Category exclusions, from user feedback: a liked library is not necessarily all music.
Liked children's podcasts, an audiobook, a genre that has no place in the background — all
of it can now be kept out of the playlist.

### Added

- Three exclusion rules, each answering a different question about a track:
  `exclusions.allowed_content_types` (what it is), `exclusions.blocked_genres` (what the
  provider calls it) and `exclusions.blocked_clusters` (how YaVolna grouped it).
- All exclusions — the new rules and the existing `blocked_track_ids` / `blocked_artist_ids`
  — now apply to the liked library and to the recommendations alike, so an excluded
  category cannot come back through discovery. They are hard filters: never relaxed to
  reach the target duration.
- `Track.content_type`: the Yandex adapter reads the track `type` and the album
  `meta_type`, so podcast episodes and audiobook chapters are recognised as non-music.
- `inspect-library` lists the genre codes present in the library, and `validate-config`
  reports the exclusions in force.
- Spec section 38 documents the rules; `--provider fake` now includes a few podcast
  episodes so the whole thing can be tried offline.

### Changed

- Liked podcasts and audiobooks are no longer selected: `exclusions.allowed_content_types`
  defaults to `["music"]`. Set it to `[]` to restore the previous behaviour.

### How to use it

Everything lives under `exclusions` in `config.yaml`:

```yaml
exclusions:
  # What the track is. Podcasts and audiobooks are out by default;
  # [] disables the check, ["music", "podcast"] lets podcasts back in.
  allowed_content_types: ["music"]

  # What the provider calls it — genre codes, as printed by inspect-library.
  blocked_genres:
    - forchildren
    - podcasts

  # How YaVolna grouped it — cluster ids, as printed by inspect-clusters.
  blocked_clusters:
    - dance
```

Where the names come from:

| Command | Shows |
| --- | --- |
| `yavolna inspect-library` | The genre codes present in your library, with track counts — the names for `blocked_genres`. |
| `yavolna inspect-clusters` | Cluster sizes and sample tracks — the names for `blocked_clusters`. |
| `yavolna validate-config` | The exclusions currently in force. |

Every run reports what each rule dropped, by reason:

```text
Liked library: 240 tracks (12 excluded [content_type=12], 0 duplicates removed), 10 clusters
```

Check the result without touching Yandex Music with `yavolna generate --dry-run`. If a
podcast still turns up, the provider typed it as music: find its genre code with
`inspect-library` and add that to `blocked_genres`.

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

[Unreleased]: https://github.com/demidov-alexander/ya-volna/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/demidov-alexander/ya-volna/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/demidov-alexander/ya-volna/releases/tag/v0.1.0
