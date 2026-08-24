# Contributing

Thanks for looking at YaVolna. This is a small self-hosted utility; the bar for changes is
"does it keep working without my account?".

## Ground rules

- **Never commit secrets.** No tokens, cookies, account ids, playlist ids, or exports of a
  real library — not in code, tests, fixtures, issues or logs. `.env`, `config.yaml` and
  `data/` are gitignored; keep it that way.
- **Tests must run without a Yandex account.** Use the in-memory `FakeMusicProvider`, or a
  stub client for adapter tests. No network calls in the suite.
- **Randomized behaviour must be seedable.** Anything that draws from `random` takes an
  injected `random.Random` so tests stay reproducible.
- **Keep provider details behind the adapter.** Only `providers/yandex_music.py` may
  import `yandex_music` or know its data shapes. Everything else works on the internal
  `Track`/`Playlist` model.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install     # optional but recommended
```

## Checks

```bash
pytest
pytest tests/test_scheduler.py::test_same_seed_reproduces_the_playlist   # one test
ruff check . && ruff format --check .
mypy
yavolna --provider fake generate --dry-run --duration-hours 2            # offline e2e
```

CI runs the same commands on Python 3.12 and 3.13, plus a Docker build.

## Layout

```
src/yavolna/
  cli.py             Typer commands
  config.py          Pydantic config + secret loading
  logging.py         logging with secret redaction
  providers/         base interface, Yandex adapter, in-memory fake
  library/           internal model, loader, normalization
  clustering/        genre -> coarse cluster assignment
  recommendation/    seed groups, discovery candidates
  mixing/            candidate pools, scoring, scheduler, constraints
  persistence/       SQLite schema and queries
  playlists/         validation and publishing
  services/          the generation pipeline
```

`yandex_daily_mix_spec.md` is the design document; section numbers referenced in
docstrings point at it. If a change deviates from the spec on purpose, update the spec in
the same pull request.

## Pull requests

- One topic per PR, with a short description of the behaviour change.
- Add or adjust tests for anything that changes selection behaviour.
- Update `README.md`, `README.ru.md` and `config.example.yaml` when you add a config key.
- Add a `CHANGELOG.md` entry under "Unreleased".

## Reporting problems

Include the command you ran, the relevant log lines (with `--debug` if useful), your
Python version, and the parts of `config.yaml` that matter. **Redact anything private** —
logs are scrubbed of tokens, but playlist and track ids are still your data.
