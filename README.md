# YaVolna

**Your own daily mix for Yandex Music** — a self-hosted CLI that builds one long playlist
(12 hours by default, tune it to taste) from your liked library plus fresh
recommendations, deliberately alternating between musical styles instead of sitting in one
genre for an hour.

The provider suggests candidates; **YaVolna decides what plays next.**

```
$ yavolna generate
library:           638 liked tracks
candidate pools:   familiar 638, discovery 563
selected:          195 tracks (12.0 h of 12.0 h target)
mix:               familiar 127 (65%), discovery 68 (35%)
clusters used:     12
playlist:          'YaVolna' (id=1023)
url:               https://music.yandex.ru/users/you/playlists/1023
runtime:           24.2s
```

## Contents

- [What it does](#what-it-does)
- [Requirements](#requirements)
- [Installation](#installation)
- [Authentication](#authentication)
- [First run](#first-run)
- [Playlist modes: one playlist or one per day](#playlist-modes-one-playlist-or-one-per-day)
- [Configuration reference](#configuration-reference)
- [Commands](#commands)
- [Scheduling](#scheduling)
- [Docker](#docker)
- [How the mixing works](#how-the-mixing-works)
- [Privacy and security](#privacy-and-security)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [License](#license)

## What it does

- reads **all your liked tracks** and treats them as the "familiar" half of the playlist;
- asks Yandex Music for recommendations from **several different seed groups** (one per
  musical cluster, plus recent likes, old likes, the underrepresented long tail and an
  intentionally diverse group) so the "discovery" half does not collapse into one style;
- groups everything into coarse **style clusters** from genre metadata;
- builds the playlist **position by position**, scoring every candidate and keeping the
  same artist, album and cluster apart by configurable gaps;
- remembers what it generated before in a local **SQLite** database, so consecutive days
  do not look alike;
- validates the result and only then replaces the playlist in your account.

Everything runs on your machine. There is no server, no account of ours, and no telemetry.

## Requirements

- Python 3.12+
- a Yandex Music account (a subscription is needed for most tracks to be playable)
- roughly 5 MB of disk for the local history database

## Installation

```bash
git clone https://github.com/demidov-alexander/ya-volna.git
cd ya-volna
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .

cp .env.example .env               # secrets go here
cp config.example.yaml config.yaml # behaviour goes here
```

Both `.env` and `config.yaml` are gitignored.

## Authentication

> **Important:** YaVolna talks to Yandex Music through an **unofficial, reverse-engineered
> API** ([yandex-music](https://github.com/MarshalX/yandex-music-api)). There is no public
> official API. A Yandex Music token grants full access to your music account — treat it
> like a password, and be aware that using unofficial clients may conflict with the
> service's terms of use. You do this at your own risk.

You need an OAuth token in `YANDEX_MUSIC_TOKEN`.

Yandex does not let you register your own OAuth application for Yandex Music, so every
client — this one included — authorises through the client id of the official Yandex Music
application. The value below is the one documented by the upstream library in
[Token obtainment methods](https://ym.marshal.dev/en/main/token.html); YaVolna does not
invent or ship a client id of its own.

**1. Browser (no extra tools).** Open this URL while logged into your Yandex account:

```
https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d
```

After confirming, the browser is redirected to a URL that contains
`#access_token=<YOUR_TOKEN>&…`. Copy the value of `access_token`.

**2. Community helpers.** The `yandex-music-api`
[documentation](https://ym.marshal.dev/en/main/token.html) also lists third-party
extractors (websites, an Android app, browser extensions) that read the token from an
already logged-in session, and the library itself supports an OAuth device flow. Use
whichever you trust; the resulting token is the same.

Put it in `.env`:

```env
YANDEX_MUSIC_TOKEN=y0_your_token_here
```

Then verify:

```bash
yavolna auth-check
# authenticated:  Your Name, uid=123456789, subscription: yes
```

Secrets are read from environment variables first, then from `.env`. They are never read
from `config.yaml` — YaVolna refuses to start if it finds credential-like keys there. Logs
are passed through a redaction filter so tokens, cookies and `Authorization` headers never
reach the output.

## First run

Always start with a dry run — it performs the whole selection and writes a JSON export
without touching your account:

```bash
yavolna generate --dry-run
cat data/dry-run-$(date +%F).json | head -40
```

Inspect what YaVolna thinks your library looks like:

```bash
yavolna inspect-library
yavolna inspect-clusters
```

When the proposed mix looks reasonable, generate for real:

```bash
yavolna generate
```

Runs are reproducible with a seed:

```bash
yavolna generate --seed 42 --dry-run
```

No Yandex account handy? A built-in offline provider generates a synthetic library so you
can see the whole pipeline work:

```bash
yavolna --provider fake generate --dry-run
```

## Playlist modes: one playlist or one per day

`playlist.mode` decides how the target playlist is managed across runs.

| Mode | Behaviour | Good for |
| --- | --- | --- |
| `replace` (default) | One playlist, e.g. `YaVolna`. Every run replaces its contents. | A stable link/shortcut you always open. |
| `daily_new` | A new playlist per day, e.g. `YaVolna 2026-08-24`. A second run on the same day replaces that day's playlist. | Keeping an archive of past days. |

```yaml
playlist:
  mode: "daily_new"
  daily_name_template: "{name} {date}"   # {name} and {date} are the only placeholders
  date_format: "%Y-%m-%d"
  keep_daily_playlists: 7                # 0 = never delete anything
```

`keep_daily_playlists` is the only setting that ever deletes a playlist. It is **0 by
default**, and when enabled it only removes playlists that YaVolna itself created and
tracked in its local database — playlists you made by hand are never touched. Deletion
also never happens during `--dry-run`.

You can override the mode per run without editing the config:

```bash
yavolna generate --mode daily_new
yavolna generate --mode replace
```

## Configuration reference

`config.yaml` holds behaviour only; see `config.example.yaml` for the annotated version.

### `playlist`

| Key | Default | Meaning |
| --- | --- | --- |
| `name` | `YaVolna` | Playlist title (base title in `daily_new` mode). |
| `description` | … | Description set when the playlist is created. |
| `target_duration_hours` | `12` | Target length. Selection stops when reached or slightly exceeded. |
| `mode` | `replace` | `replace` or `daily_new`, see above. |
| `reuse_existing_playlist` | `true` | Reuse a playlist that already has this title instead of creating another one. |
| `daily_name_template` | `{name} {date}` | Title template for `daily_new`. Must contain `{date}`. |
| `date_format` | `%Y-%m-%d` | `strftime` format for `{date}`. |
| `keep_daily_playlists` | `0` | Keep this many generated daily playlists; `0` disables clean-up. |
| `visibility` | `private` | `private` or `public`, used at creation time. |

### `mix`

| Key | Default | Meaning |
| --- | --- | --- |
| `familiar_ratio` | `0.65` | Share of liked tracks. |
| `discovery_ratio` | `0.35` | Share of not-yet-liked tracks. Must sum to `1.0` with the above. |
| `exploratory_ratio_within_discovery` | `0.25` | Extra weight for candidates from the deliberately odd seed groups. |

### `repetition`

| Key | Default | Meaning |
| --- | --- | --- |
| `track_cooldown_days` | `10` | Days before a previously generated track may return. |
| `favorite_track_cooldown_days` | `4` | Shorter cooldown for liked tracks. |
| `same_artist_gap_tracks` | `20` | Minimum distance between two tracks by the same artist. |
| `same_album_gap_tracks` | `40` | Same, per album. |
| `same_cluster_gap_tracks` | `3` | Same, per style cluster — this is what keeps styles alternating. |

### `history`, `selection`, `discovery`

| Key | Default | Meaning |
| --- | --- | --- |
| `history.local_retention_days` | `180` | How long local generation history is kept. |
| `history.use_remote_listening_history` | `true` | Use Yandex playback queues as an extra cooldown hint when available. |
| `selection.minimum_liked_tracks` | `20` | Refuse to run with a tiny library. |
| `selection.random_seed` | `null` | Fixed seed for reproducible runs. |
| `selection.prefer_high_variety` | `true` | Push small clusters above their library share. |
| `selection.fallback_track_duration_seconds` | `240` | Assumed length when metadata has none (logged). |
| `selection.max_candidates_per_step` | `400` | Upper bound of candidates scored per position. |
| `discovery.seed_groups_max` | `8` | How many independent recommendation requests to make. |
| `discovery.seeds_per_group` | `4` | Seed tracks per group. |
| `discovery.max_candidates_per_seed` | `20` | Candidates requested per seed. |
| `discovery.use_personal_wave` | `true` | Also pull from "My Wave" when available. |

### `clustering`, `exclusions`, `validation`, `runtime`

| Key | Default | Meaning |
| --- | --- | --- |
| `clustering.fallback_cluster` | `other` | Cluster for tracks with unusable genre metadata. |
| `clustering.genre_map` | `{}` | Extend/override the built-in genre → cluster mapping. |
| `exclusions.blocked_track_ids` | `[]` | Never select these tracks. |
| `exclusions.blocked_artist_ids` | `[]` | Never select these artists. |
| `exclusions.allowed_content_types` | `["music"]` | Content types allowed in; podcasts and audiobooks are out by default. `[]` disables the check. |
| `exclusions.blocked_genres` | `[]` | Provider genre codes that are never selected. |
| `exclusions.blocked_clusters` | `[]` | Style clusters that are never selected. |
| `validation.ratio_tolerance` | `0.05` | Allowed deviation from the familiar/discovery ratio. |
| `validation.duration_tolerance` | `0.15` | Allowed deviation from the target duration. |
| `validation.max_playlist_tracks` | `10000` | Hard cap on playlist size. |
| `runtime.database_path` | `data/yavolna.sqlite3` | Local history database. |
| `runtime.log_level` | `INFO` | `DEBUG`…`CRITICAL`. |
| `runtime.dry_run_export_dir` | `data` | Where `--dry-run` writes its JSON. |

### Excluding categories

Liked children's podcasts, an audiobook, a genre you never want in the background —
all of it is filtered out before selection, in the liked library and in the
recommendations alike.

```yaml
exclusions:
  allowed_content_types: ["music"]   # the default: no podcasts, no audiobooks
  blocked_genres: ["forchildren"]    # provider genre codes
  blocked_clusters: ["dance"]        # YaVolna's own style clusters
```

Three different questions, on purpose:

- **content type** is what the track *is* — Yandex Music marks podcast episodes and
  audiobook chapters as non-music, and the default keeps them out of a music playlist.
  Set `allowed_content_types: []` to switch the check off, or list a type to let it in;
- **genre** is what the provider says the track is. `yavolna inspect-library` prints the
  genre codes present in your library, which is where the names for this list come from;
- **cluster** is how YaVolna grouped the track. `yavolna inspect-clusters` prints them.

`yavolna validate-config` shows the exclusions in force, and every run logs how many
tracks each rule dropped.

## Commands

```bash
yavolna generate                     # create or replace the playlist
yavolna generate --dry-run           # select and export, change nothing remotely
yavolna generate --seed 42           # reproducible run
yavolna generate --duration-hours 12 # override the target length
yavolna generate --mode daily_new    # override the playlist mode
yavolna inspect-library              # library statistics
yavolna inspect-clusters             # cluster sizes and sample tracks
yavolna validate-config              # config + credential check, no network
yavolna auth-check                   # verify the token against the account
yavolna history stats                # local generation history
```

Global options: `--config <path>`, `--log-level <level>`, `--debug` (tracebacks on),
`--provider yandex|fake`.

Exit codes: `2` configuration, `3` authentication, `4` provider, `5` recommendations,
`6` playlist write, `7` database, `8` validation.

## Scheduling

YaVolna is a deterministic one-shot command; scheduling belongs to your platform.

**cron**

```cron
0 4 * * * cd /opt/ya-volna && .venv/bin/yavolna generate >> /var/log/yavolna.log 2>&1
```

**systemd timer** — see [`docs/systemd`](docs/systemd) for a ready service + timer pair:

```bash
sudo cp docs/systemd/yavolna.* /etc/systemd/system/
sudo systemctl enable --now yavolna.timer
```

Adjust `User`, the paths, and `ProtectHome` for a checkout outside `/opt`.

**WSL** — both cron and systemd timers only fire while the WSL instance is running, and
WSL does not start on its own. A systemd timer with `Persistent=true` (as shipped) catches
up on a missed run once WSL comes back, which cron does not; that makes the timer the
better choice there. For a run that happens whether or not you opened a terminal, drive it
from Windows Task Scheduler instead:

```
wsl.exe -d <distro> --cd /path/to/ya-volna -e .venv/bin/yavolna generate
```

**GitHub Actions** — a disabled-by-default workflow lives in
[`.github/workflows/daily-mix.yml.example`](.github/workflows/daily-mix.yml.example). It
is intentionally not active: running it means storing your token in GitHub Actions Secrets
and keeping the SQLite history in a cache/artifact, which weakens both privacy and the
anti-repetition logic. Prefer cron or a container on your own machine.

## Docker

```bash
docker build -t ya-volna -f docker/Dockerfile .

docker run --rm \
  --env-file .env \
  -v "$PWD/config.yaml:/app/config.yaml:ro" \
  -v "$PWD/data:/app/data" \
  ya-volna generate
```

The image runs as a non-root user, bakes in no secrets, and keeps state in the
`/app/data` volume.

## How the mixing works

1. **Load** liked tracks, normalize them into an internal model, drop duplicates and
   blocked items.
2. **Cluster** them from genre metadata into coarse styles (`rock`, `russian_rock`,
   `electronic`, `techno`, `pop`, `metal`, `hiphop`, `ambient_melodic`, …). Tracks without
   genres inherit the dominant cluster of their artist.
3. **Seed** several independent recommendation requests — per cluster, recent likes, old
   likes, the smallest clusters, and a deliberately diverse group.
4. **Filter** discovery candidates: already liked, same song under another id,
   unavailable, blocked, or recently generated ones are dropped.
5. **Schedule** position by position. Each candidate gets a score built from a base
   weight, an underrepresented-cluster bonus, a quota-need bonus, and penalties for track,
   artist, album and cluster recency. The top-scoring window then goes through a weighted
   random draw, so two runs never look identical.
6. **Relax** constraints only when nothing is selectable, and always in this order:
   cluster gap → album gap → artist gap → track cooldown → ratio deviation → stop early.
   Every relaxation is logged.
7. **Validate** duplicates, availability, duration, ratio and size.
8. **Publish**, then record the run locally — in that order, so a failed upload leaves
   yesterday's playlist intact.

## Privacy and security

- Your library never leaves your machine except in requests to Yandex Music itself.
- The token lives in the environment or `.env`, never in `config.yaml`, never in the repo.
- `.gitignore` covers `.env`, `config.yaml`, `data/` and all SQLite files.
- Logs are scrubbed of tokens, cookies and `Authorization` headers.
- The only destructive operation is `keep_daily_playlists`, which is off by default and
  limited to playlists YaVolna created.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| `Authentication failed` / exit code 3 | Re-issue the token and run `yavolna auth-check`. Tokens expire and are invalidated by password changes. |
| `The provider returned no liked tracks` | The token may belong to a different account than you expect — check `yavolna auth-check`. |
| Playlist much shorter than the target | The candidate pool ran out; the log says `stopped early`. Lower `target_duration_hours`, or loosen `repetition.*` gaps and cooldowns. A library of N liked tracks can fill roughly `N × 3.7 min × familiar_ratio⁻¹` of playlist before it has to repeat. |
| `familiar/discovery ratio deviates` | Discovery returned too few candidates. Raise `discovery.seed_groups_max`, or widen `validation.ratio_tolerance`. |
| Most tracks land in `other` | Genre metadata is thin for your library. Add mappings under `clustering.genre_map`; `yavolna inspect-clusters` shows what genres arrived. |
| Yandex Music request failed (exit 4) | The unofficial API changed or is rate-limiting. Retry later, then rerun with `--debug`. |

## Development

```bash
pip install -e ".[dev]"
pytest                     # full suite, no Yandex account needed
pytest tests/test_scheduler.py::test_same_seed_reproduces_the_playlist
ruff check . && ruff format --check .
mypy
```

The suite runs entirely against an in-memory fake provider, and randomized scheduling is
seeded, so results are reproducible. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). YaVolna is not affiliated with or endorsed by Yandex.
