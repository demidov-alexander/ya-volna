# Yandex Music Daily Mix — Technical Specification

## 1. Overview

**Yandex Music Daily Mix** is a self-hosted, open-source utility that generates a large personalized playlist in Yandex Music on a recurring schedule.

The tool is designed for users whose liked library spans multiple genres and who want more variety than a typical recommendation radio provides. Instead of staying inside one musical style for a long stretch, the generated playlist intentionally alternates between different parts of the user's taste while balancing familiar and previously unheard tracks.

The project must be suitable for publishing as a public GitHub repository. No user-specific secrets, tokens, account identifiers, or private library data may be committed to the repository.

---

## 2. Goals

The application should:

1. Read a user's liked tracks from Yandex Music.
2. Optionally use recent listening history when the API/library allows it.
3. Build a long daily playlist, configurable by target duration or track count.
4. Mix multiple musical styles instead of clustering similar tracks together.
5. Include both:
   - familiar tracks already liked by the user;
   - discovery tracks not currently present in the user's liked library.
6. Allow the user to configure the familiar/discovery ratio.
7. Minimize undesirable repetition across:
   - tracks;
   - artists;
   - albums;
   - musical clusters/styles;
   - consecutive daily playlists.
8. Update or recreate the target playlist automatically on a schedule.
9. Run locally, on a NAS, Raspberry Pi, VPS, container host, or CI runner.
10. Keep all credentials outside the source repository.

---

## 3. Non-goals for MVP

The first version does **not** need to:

- reproduce Yandex Music's recommendation algorithm;
- train a custom neural network;
- perform audio waveform analysis;
- provide a graphical user interface;
- host a centralized cloud service storing users' credentials;
- guarantee compatibility with future Yandex Music API changes;
- synchronize playback state in real time.

The MVP should remain simple enough to install, inspect, modify, and self-host.

---

## 4. Important Platform Constraint

The project will rely on an **unofficial Yandex Music API client** or compatible reverse-engineered API interface.

Consequences:

- API behavior may change without notice.
- Authentication mechanisms may change.
- Some features such as history or recommendations may be unavailable for certain accounts or library versions.
- The application must fail gracefully and log actionable errors.
- All Yandex-specific access should be isolated behind an adapter layer so that API changes do not affect the entire codebase.

---

## 5. Security and Public Repository Requirements

The GitHub repository must contain **no secrets**.

### 5.1 Secrets must never be committed

The following must be provided at runtime only:

- Yandex Music authentication token;
- cookies, session identifiers, or equivalent credentials;
- optional account-specific IDs if required by the API;
- third-party API keys if future integrations are added.

### 5.2 Supported secret-loading methods

The application should support, in priority order:

1. environment variables;
2. a local `.env` file ignored by Git;
3. Docker secrets or CI secret stores;
4. optional OS secret managers in future versions.

Example:

```env
YANDEX_MUSIC_TOKEN=replace_me
```

### 5.3 Repository files

The public repository should include:

```text
.env.example
.gitignore
README.md
LICENSE
pyproject.toml
config.example.yaml
src/
tests/
docker/
.github/workflows/
```

`.env.example` must contain variable names only and dummy values.

Example:

```env
YANDEX_MUSIC_TOKEN=
```

### 5.4 Log hygiene

Logs must never print:

- authentication tokens;
- cookies;
- Authorization headers;
- full API request headers;
- other secrets.

Any diagnostic object containing credentials must be redacted before logging.

---

## 6. User Experience

A typical user flow should be:

```bash
git clone <repository-url>
cd yandex-daily-mix
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
cp config.example.yaml config.yaml
```

The user then adds their token to `.env`, adjusts `config.yaml`, and runs:

```bash
ydmix generate
```

The application should create or update a Yandex Music playlist such as:

```text
Daily Chaos
```

A dry-run mode should also be available:

```bash
ydmix generate --dry-run
```

Dry-run mode must perform selection and print/export the proposed result without modifying the user's Yandex Music account.

---

## 7. Configuration

Configuration should be split between:

- **secrets** in environment variables;
- **behavioral settings** in YAML/TOML.

Example `config.yaml`:

```yaml
playlist:
  name: "Daily Chaos"
  description: "Automatically generated mixed-style daily playlist"
  target_duration_hours: 48
  reuse_existing_playlist: true

mix:
  familiar_ratio: 0.65
  discovery_ratio: 0.35
  exploratory_ratio_within_discovery: 0.25

repetition:
  track_cooldown_days: 10
  favorite_track_cooldown_days: 4
  same_artist_gap_tracks: 20
  same_album_gap_tracks: 40
  same_cluster_gap_tracks: 3

history:
  local_retention_days: 180
  use_remote_listening_history: true

selection:
  minimum_liked_tracks: 20
  random_seed: null
  prefer_high_variety: true

exclusions:
  allowed_content_types: ["music"]
  blocked_genres: []
  blocked_clusters: []
  blocked_track_ids: []
  blocked_artist_ids: []

runtime:
  database_path: "data/ydmix.sqlite3"
  log_level: "INFO"
```

### 7.1 Ratio validation

The application must validate that:

```text
familiar_ratio + discovery_ratio = 1.0
```

Values should be accepted as decimals between `0.0` and `1.0`.

---

## 8. High-Level Architecture

Recommended modules:

```text
src/ydmix/
  cli.py
  config.py
  logging.py

  providers/
    base.py
    yandex_music.py

  library/
    models.py
    loader.py
    normalization.py

  recommendation/
    seeds.py
    discovery.py

  clustering/
    base.py
    metadata_clusterer.py

  mixing/
    candidate_pool.py
    scorer.py
    scheduler.py
    constraints.py

  persistence/
    db.py
    repository.py

  playlists/
    writer.py

  services/
    generate_mix.py
```

---

## 9. Provider Abstraction

Yandex Music integration should live behind an interface.

Example conceptual interface:

```python
class MusicProvider:
    def get_liked_tracks(self) -> list[Track]: ...
    def get_recent_history(self) -> list[PlaybackEvent]: ...
    def get_recommendations(self, seeds: list[Track]) -> list[Track]: ...
    def get_or_create_playlist(self, name: str) -> Playlist: ...
    def replace_playlist_tracks(self, playlist_id: str, tracks: list[Track]) -> None: ...
```

This separation makes it possible to:

- mock the provider in tests;
- isolate Yandex API changes;
- potentially support other music services later.

---

## 10. Internal Track Model

The application should normalize provider data into its own internal model.

Suggested fields:

```text
Track
- provider
- provider_track_id
- title
- artist_ids[]
- artist_names[]
- album_id
- album_title
- duration_seconds
- genres[]
- release_year
- liked
- explicit
- available
- content_type
- metadata
```

Optional runtime fields:

```text
- cluster_id
- familiarity_score
- discovery_score
- recency_penalty
- artist_penalty
- album_penalty
- final_score
```

The application must not depend directly on provider-native Python objects outside the provider adapter.

---

## 11. Familiar Track Pool

The familiar pool consists primarily of tracks already liked by the user.

### 11.1 Eligibility

A familiar track is eligible if:

- it is available for playback;
- it is not excluded by local configuration — by id, content type, genre or cluster
  (section 38);
- it is outside its cooldown period, unless cooldown relaxation is necessary to reach the requested playlist duration.

### 11.2 Familiarity weighting

For MVP, all liked tracks may be treated equally except for recency and repetition penalties.

Future versions may increase weight based on:

- repeated historical plays;
- how long the track has remained liked;
- manual favorite tiers;
- skip behavior if accessible.

---

## 12. Discovery Track Pool

Discovery tracks are tracks that are not currently present in the user's liked library.

The application should obtain discovery candidates by requesting recommendations from several different seed groups rather than one global seed set.

### 12.1 Seed groups

Example seed strategies:

- random liked tracks from different clusters;
- recently liked tracks;
- older liked tracks;
- underrepresented clusters;
- representative tracks from large clusters;
- intentionally diverse seeds.

### 12.2 Multi-source candidate generation

Example:

```text
Seed Set A: rock-oriented liked tracks
Seed Set B: electronic-oriented liked tracks
Seed Set C: melodic / calm liked tracks
Seed Set D: Russian-language rock
Seed Set E: unusual / sparse cluster
```

Each seed set requests recommendations independently.

The returned candidates are merged, normalized, deduplicated, and filtered.

### 12.3 Discovery exclusion rules

Discovery candidates should be excluded if:

- already liked;
- already selected in the current playlist;
- recently included in previous generated playlists;
- unavailable;
- excluded by local configuration, under the same rules as the familiar pool (section 38);
- artist repetition constraints make them unsuitable.

---

## 13. Musical Clustering

The main purpose of clustering is not perfect musicology. It is to prevent the playlist from getting stuck in one style.

### 13.1 MVP clustering

The MVP should use metadata available through the provider, such as:

- genres;
- artist metadata;
- albums;
- possibly recommendation context.

Tracks should be assigned to coarse clusters such as:

```text
rock
russian_rock
electronic
techno
dance
ambient_melodic
pop
metal
hiphop
other
```

The exact names are implementation details and should not be hardcoded into the scheduling algorithm.

### 13.2 Automatic cluster IDs

Internally, tracks should use generic `cluster_id` values.

The scheduler must work with any number of clusters.

### 13.3 Future clustering options

Later versions may add:

- external metadata providers;
- embeddings based on track/artist descriptions;
- Spotify-style audio features if a legal source is available;
- Last.fm tags;
- MusicBrainz metadata;
- local ML clustering.

Such integrations must be optional and must not be required for core operation.

---

## 14. Playlist Construction Algorithm

The scheduler is the core of the project.

A naive random shuffle is not sufficient.

The scheduler should construct the playlist incrementally.

### 14.1 Candidate state

For each position, the scheduler considers eligible candidates from both familiar and discovery pools.

### 14.2 Familiar/discovery quota

The scheduler should aim for the configured long-term ratio rather than enforcing it rigidly at every few tracks.

Example:

```text
65% familiar
35% discovery
```

For a 750-track playlist:

```text
~488 familiar
~262 discovery
```

Small deviations are acceptable if constraints make an exact ratio impossible.

### 14.3 Variety constraints

Default constraints:

```text
same artist: avoid within last 20 tracks
same album: avoid within last 40 tracks
same cluster: avoid within last 3 tracks
same track: never duplicate in same generated playlist
```

These should be configurable.

### 14.4 Candidate scoring

A conceptual score may be calculated as:

```text
score =
    base_weight
  + underrepresented_cluster_bonus
  + quota_need_bonus
  + discovery_or_familiar_need_bonus
  - track_recency_penalty
  - artist_recency_penalty
  - album_recency_penalty
  - cluster_recency_penalty
  - historical_playlist_recency_penalty
```

The exact numerical implementation can evolve independently from the public configuration interface.

### 14.5 Controlled randomness

Selection among high-scoring candidates should contain randomness so that two runs do not always produce the same ordering.

However, randomness should be constrained enough that low-quality candidates do not frequently outrank much better candidates.

Recommended approach:

1. calculate scores;
2. select a top candidate window;
3. perform weighted random choice within that window.

### 14.6 Constraint relaxation

If no candidate is available, constraints should relax progressively.

Example order:

1. relax cluster gap;
2. relax album gap;
3. relax artist gap;
4. relax historical track cooldown;
5. accept a small ratio deviation;
6. stop early only if no playable candidates remain.

Every relaxation should be logged at `DEBUG` or `INFO` level.

---

## 15. Target Playlist Length

The preferred user-facing setting is duration rather than track count.

Example:

```yaml
target_duration_hours: 48
```

The scheduler should continue selecting tracks until cumulative duration reaches or slightly exceeds the target.

A configurable overshoot allowance may be added later.

If duration metadata is unavailable for some tracks, the application may use an estimated duration, for example 240 seconds, while logging the fallback.

---

## 16. Historical Anti-Repetition Database

The application should maintain a local SQLite database.

Purpose:

- remember which tracks were recently generated;
- avoid recreating the same daily playlist;
- maintain cooldown information even if Yandex listening history is incomplete;
- retain generation diagnostics.

Suggested tables:

```text
generation_runs
- id
- started_at
- finished_at
- status
- playlist_id
- target_duration_seconds
- actual_duration_seconds
- familiar_count
- discovery_count

playlist_entries
- run_id
- position
- provider_track_id
- cluster_id
- source_type
- selected_at

track_state
- provider_track_id
- last_generated_at
- generation_count
- last_seen_liked
```

Optional future tables:

```text
user_feedback
artist_state
cluster_state
```

---

## 17. Daily Regeneration Behavior

Default behavior:

1. locate an existing target playlist by a stable local reference or provider ID;
2. generate the full new track list locally;
3. validate the result;
4. replace playlist contents;
5. only after a successful remote update, commit the generation run to SQLite.

If the remote update fails, the previous playlist should remain intact whenever possible.

The writer should prefer transactional or revision-aware update mechanisms if supported by the provider.

---

## 18. Validation Before Publishing Playlist

The generator must validate:

- no duplicate track IDs;
- all tracks are playable where known;
- duration is reasonably close to target;
- familiar/discovery ratio is within tolerance;
- playlist is not empty;
- credentials are available;
- provider update limits are respected;
- no known maximum playlist size is exceeded.

Example ratio tolerance:

```yaml
ratio_tolerance: 0.05
```

---

## 19. CLI Specification

Suggested commands:

```bash
ydmix generate
ydmix generate --dry-run
ydmix generate --seed 42
ydmix inspect-library
ydmix inspect-clusters
ydmix validate-config
ydmix auth-check
ydmix history stats
```

### 19.1 `generate`

Creates or replaces the configured playlist.

### 19.2 `--dry-run`

Does not modify Yandex Music.

May export:

```text
data/dry-run-YYYY-MM-DD.json
```

### 19.3 `inspect-library`

Prints statistics such as:

```text
liked tracks: 3,842
artists: 1,106
albums: 1,934
clusters: 9
estimated library duration: ...
```

### 19.4 `inspect-clusters`

Shows cluster sizes and sample tracks to help diagnose poor metadata grouping.

---

## 20. Scheduling

Scheduling should be external to the core application.

The application only needs to provide a deterministic one-shot command:

```bash
ydmix generate
```

Users can schedule it with their platform of choice.

### 20.1 Cron

Example:

```cron
0 4 * * * cd /opt/yandex-daily-mix && .venv/bin/ydmix generate
```

### 20.2 systemd timer

Provide an example service/timer configuration in documentation.

### 20.3 Docker

Example:

```bash
docker run --rm \
  --env-file .env \
  -v ./config.yaml:/app/config.yaml:ro \
  -v ./data:/app/data \
  yandex-daily-mix generate
```

### 20.4 GitHub Actions

A sample workflow may be included, but it must be disabled by default or clearly documented as an optional deployment mode.

Secrets must be read from GitHub Actions Secrets.

No token may appear in workflow YAML.

---

## 21. Docker Requirements

The repository should include a minimal Docker image.

Requirements:

- non-root runtime user where practical;
- no secrets baked into image layers;
- persistent `/app/data` volume;
- config mounted read-only where practical;
- environment-variable authentication;
- health check not required for one-shot mode.

---

## 22. Testing Strategy

The test suite must not require a real Yandex account.

### 22.1 Unit tests

Test:

- config validation;
- ratio math;
- cooldown calculations;
- deduplication;
- candidate scoring;
- artist/album/cluster constraints;
- constraint relaxation;
- target duration handling.

### 22.2 Provider mock

Provide a fake in-memory provider implementing the same provider interface.

The fake provider should contain sample:

- liked tracks;
- recommended tracks;
- history;
- playlists.

### 22.3 Deterministic tests

Randomized scheduling must accept a seed.

Tests should use a fixed seed to guarantee reproducible results.

### 22.4 Optional integration tests

Real-account integration tests may exist but must:

- be opt-in;
- require environment secrets;
- never run on pull requests from forks;
- preferably operate on a clearly named test playlist.

---

## 23. Error Handling

Errors should be categorized.

Suggested exception hierarchy:

```text
YDMixError
  ConfigurationError
  AuthenticationError
  ProviderError
  RecommendationError
  PlaylistWriteError
  DatabaseError
```

User-facing CLI errors should be concise and actionable.

Example:

```text
Authentication failed. Check YANDEX_MUSIC_TOKEN and run `ydmix auth-check`.
```

Stack traces should be hidden by default and enabled with a debug flag.

---

## 24. Logging

Default logs should include:

- library size;
- number of clusters;
- candidate counts;
- discovery/familiar target counts;
- actual selected counts;
- generated duration;
- relaxed constraints;
- playlist update result;
- total runtime.

Sensitive data must be redacted.

Optional machine-readable JSON logs may be added later.

---

## 25. GitHub Repository Quality Requirements

The initial public release should contain:

### Required

- `README.md`
- installation guide;
- authentication guide;
- configuration reference;
- security warning about unofficial API usage;
- `.env.example`;
- `config.example.yaml`;
- license;
- unit tests;
- basic CI;
- Dockerfile;
- sample cron instructions.

### Recommended

- `CONTRIBUTING.md`;
- `SECURITY.md`;
- `CHANGELOG.md`;
- issue templates;
- Dependabot/Renovate configuration;
- pre-commit hooks;
- formatter and linter configuration.

---

## 26. Recommended Python Stack

Suggested baseline:

```text
Python 3.12+
Typer or Click          CLI
Pydantic                configuration validation
PyYAML or TOML          non-secret configuration
python-dotenv           local .env support
SQLAlchemy or sqlite3   persistence
unofficial yandex-music client
pytest                  tests
ruff                    lint/format
mypy or pyright         optional static typing
```

A lightweight implementation using standard-library `sqlite3` is acceptable for MVP.

---

## 27. MVP Algorithm

A practical first implementation can work as follows.

### Step 1 — Load configuration

Load behavioral config and runtime secrets.

### Step 2 — Authenticate

Initialize the Yandex Music provider and verify the account.

### Step 3 — Load liked library

Fetch all liked tracks and normalize them.

### Step 4 — Load local history

Read recent generated tracks from SQLite.

### Step 5 — Optionally load provider history

Use remote listening history if supported.

### Step 6 — Assign clusters

Use available genres/metadata to assign coarse cluster IDs.

### Step 7 — Build familiar candidates

Apply availability and cooldown filters to liked tracks.

### Step 8 — Generate discovery seeds

Select several diverse seed groups from liked tracks.

### Step 9 — Fetch discovery candidates

Request recommendations separately for each seed group.

### Step 10 — Normalize and deduplicate

Remove liked tracks from discovery and deduplicate candidates.

### Step 11 — Construct playlist

Repeatedly choose a candidate using:

- target familiar/discovery ratio;
- cluster diversity;
- artist spacing;
- album spacing;
- historical cooldown;
- controlled randomness.

Continue until target duration is reached.

### Step 12 — Validate

Validate size, duration, ratios, duplication, and availability.

### Step 13 — Write playlist

Replace the contents of the configured Yandex Music playlist.

### Step 14 — Persist generation history

Store the generated sequence locally.

---

## 28. Pseudocode for Scheduler

```python
while total_duration < target_duration:
    desired_source = quota_controller.next_source()

    candidates = pools[desired_source]
    candidates = apply_hard_filters(candidates, state)

    if not candidates:
        candidates = relax_constraints(pools[desired_source], state)

    if not candidates:
        other_source = opposite(desired_source)
        candidates = relax_constraints(pools[other_source], state)

    if not candidates:
        break

    scored = [score(track, state) for track in candidates]
    chosen = weighted_choice(top_window(scored))

    playlist.append(chosen)
    state.observe(chosen)
    total_duration += chosen.duration_seconds
```

---

## 29. Example Default Policy

Recommended defaults for the first public version:

```yaml
playlist:
  target_duration_hours: 48

mix:
  familiar_ratio: 0.65
  discovery_ratio: 0.35

repetition:
  track_cooldown_days: 10
  favorite_track_cooldown_days: 4
  same_artist_gap_tracks: 20
  same_album_gap_tracks: 40
  same_cluster_gap_tracks: 3
```

These are defaults only. The repository should encourage users to tune them.

---

## 30. Future Enhancements

Potential later features:

1. **Feedback learning**
   - increase weight when a discovered track becomes liked;
   - reduce weight for repeatedly skipped tracks if skip data is available.

2. **Advanced clustering**
   - embeddings;
   - richer genre taxonomies;
   - external metadata.

3. **Time-of-day playlists**
   - morning / daytime / evening profiles.

4. **Multiple playlist profiles**
   - `daily-chaos`;
   - `work-focus`;
   - `high-energy`;
   - `deep-discovery`.

5. **Adaptive familiar/discovery ratio**
   - increase discovery when users frequently like new recommendations;
   - decrease it when discovery tracks are often rejected.

6. **Web dashboard**
   - inspect clusters;
   - preview daily mix;
   - tune constraints;
   - review historical statistics.

7. **Multiple provider support**
   - retain provider-neutral mixing core.

8. **Playlist continuity mode**
   - avoid placing tracks similar to the final tracks of yesterday's playlist at the beginning of today's playlist.

---

## 31. Privacy Model

The preferred architecture is entirely self-hosted.

The project maintainers should receive no user library data by default.

User data should remain on the user's machine except for communication directly with the music provider.

Local SQLite files should be ignored by Git.

Example `.gitignore` entries:

```gitignore
.env
config.yaml
data/
*.sqlite
*.sqlite3
__pycache__/
.venv/
```

---

## 32. Licensing

The repository should use a clear open-source license.

MIT or Apache-2.0 are reasonable defaults for a permissive community utility.

Before publishing, verify compatibility with the license of the selected unofficial Yandex Music client library.

---

## 33. Definition of Done for MVP

The MVP is complete when a new user can:

1. clone the public repository;
2. install dependencies;
3. provide their own Yandex Music credential without editing source code;
4. validate authentication;
5. run a dry generation;
6. generate a playlist in their own account;
7. configure familiar/discovery ratio;
8. configure playlist duration;
9. configure artist/album/cluster cooldowns;
10. run the generator repeatedly without receiving nearly identical playlists;
11. schedule the same one-shot command externally;
12. run all unit tests without access to Yandex Music.

---

## 34. Suggested Initial Release Scope

For `v0.1.0`, keep the implementation intentionally small:

- one Yandex Music account;
- one generated playlist profile;
- liked tracks as the familiar library;
- provider recommendations as discovery;
- metadata-based coarse clustering;
- SQLite generation history;
- configurable familiar/discovery ratio;
- track/artist/album/cluster anti-repeat rules;
- duration-based playlist target;
- CLI;
- Docker support;
- cron/systemd documentation;
- provider mock and tests.

Everything else should be deferred until real-world usage shows where the recommendation quality needs improvement.

---

## 35. Design Principle

The project should treat Yandex Music as two things:

1. a music catalog and playback destination;
2. a source of recommendation candidates.

The application itself owns the final sequencing policy.

That distinction is central to the project:

> **The provider suggests candidates; Yandex Daily Mix decides what plays next.**


---

## 36. Playlist Rotation Modes

*Added during implementation of v0.1.0; extends sections 7 and 17.*

Section 17 assumes a single target playlist whose contents are replaced on every run. Some
users want the opposite: a dated playlist per day, kept as an archive. The application
therefore exposes a rotation mode.

```yaml
playlist:
  mode: "replace"                       # replace | daily_new
  daily_name_template: "{name} {date}"  # daily_new only; {date} is required
  date_format: "%Y-%m-%d"
  keep_daily_playlists: 0               # daily_new only; 0 disables clean-up
```

### 36.1 `replace`

Default, and the behaviour described in section 17: one playlist identified by a stable
local reference (or, failing that, by title), whose contents are replaced.

### 36.2 `daily_new`

The target playlist title is rendered from `daily_name_template` for the run's date. A
second run on the same day resolves to the same playlist and replaces its contents, so the
mode never produces duplicates for one day.

### 36.3 Clean-up constraints

`keep_daily_playlists` is the only setting in the project that deletes anything, and it is
bound by three rules:

1. it is `0` (disabled) by default;
2. only playlists recorded in the local `managed_playlists` table — that is, playlists the
   application itself created — may be deleted; playlists created by the user are never
   touched;
3. deletion never happens during a dry run, and a failed deletion is logged and skipped
   rather than aborting the run.

### 36.4 Local reference

The anti-repetition database gains a `managed_playlists` table keyed by
`(provider, playlist_id)` and carrying a `date_key` (empty in `replace` mode, the rendered
date in `daily_new`). It is the primary way a run finds its target playlist, ahead of any
title lookup, so renaming the playlist in the Yandex Music app does not cause a duplicate.

### 36.5 CLI

`--mode replace|daily_new` overrides the configured mode for a single run.

---

## 37. Default Policy Deviations

*Recorded during implementation of v0.1.0. The reasoning here matters more than the
numbers: defaults should work for an ordinary library, not an ideal one.*

Two documented defaults were changed:

| Setting | Spec | Implementation | Why |
| --- | --- | --- | --- |
| `playlist.name` | `Daily Chaos` (section 6) | `YaVolna` | The playlist is named after the tool, so a user seeing it in their account knows what produced it. `Daily Chaos` remains a fine choice and is still just a config value. |
| `playlist.target_duration_hours` | `48` (sections 7 and 29) | `12` | A 48 h target at a 0.65 familiar ratio needs about 31 h of liked music — roughly 500 liked tracks purely for the familiar half, and far more before the anti-repetition cooldowns stop biting on consecutive days. Measured against a 638-track library, a 48 h target exhausts the pool and stops early; 12 h fills exactly and leaves headroom for the next day. |

The 48 h figure is not wrong, it just presumes a large library. Sections 15 and 29 are
otherwise unchanged, and both values remain plain configuration.

---

## 38. Category Exclusions

*Added in 0.1.1, from user feedback: a liked library is not necessarily all music, and
not all of it belongs in a background playlist.*

Exclusions answer four independent questions, and each is configured separately under
`exclusions`:

| Rule | Question | Source of the value |
| --- | --- | --- |
| `blocked_track_ids`, `blocked_artist_ids` | Which specific items? | Provider ids. |
| `allowed_content_types` | What is this, at all? | Provider content type: `music`, `podcast`, `audiobook`, … |
| `blocked_genres` | What does the provider call it? | Provider genre codes, listed by `inspect-library`. |
| `blocked_clusters` | Where did YaVolna put it? | Cluster ids, listed by `inspect-clusters`. |

Rules:

- **The same filter guards both pools.** A category the user excluded must not return
  through recommendations, so the filter runs over the liked library and over the
  discovery candidates.
- **Exclusions are hard filters.** They are never relaxed to reach the target duration;
  a run stops short instead (section 14.6).
- **Content types are an allow-list**, defaulting to `["music"]`. Providers invent new
  non-music types over time — podcast episodes, audiobook chapters, articles — and an
  allow-list keeps them out without an update. An empty list disables the check.
- **Genre matching is normalized** the same way clustering normalizes it, including the
  `…genre` suffix Yandex Music adds to some codes, so `forchildren` and `forchildrengenre`
  are one rule.
- **Cluster rules run after clustering**, and the clusterer must not see already-excluded
  tracks: their genres would otherwise skew the artist-majority back-fill.
- **Every rule reports what it dropped**, per reason, in the run log.

The default excludes podcasts and audiobooks. This is a deliberate deviation from
"select from liked tracks": a liked children's podcast is a liked item, but a 12-hour
music mix is not where it belongs. Users who disagree set `allowed_content_types: []`.
