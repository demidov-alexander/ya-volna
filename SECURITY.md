# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub's **Report a vulnerability** button
on the Security tab of this repository, rather than opening a public issue.

Include what you found, how to reproduce it, and what an attacker could achieve. A first
response should be expected within a few days; this is a hobby project maintained in spare
time, so please allow reasonable time for a fix before disclosing publicly.

## Scope

In scope:

- credential handling — anything that could write a token, cookie or session id into logs,
  exports, the SQLite database, or the repository;
- the dry-run guarantee — anything that lets `--dry-run` modify a remote account;
- unintended destructive behaviour — deleting or overwriting playlists other than the
  configured target, or deleting playlists YaVolna did not create;
- dependency issues with a practical impact on the above.

Out of scope:

- the fact that the underlying Yandex Music API is unofficial and may change or break;
- risks inherent to holding a long-lived account token on your own machine;
- the terms-of-service implications of using an unofficial client.

## What YaVolna does to protect your credentials

- Secrets are read only from environment variables or a gitignored `.env`, never from
  `config.yaml`; the loader refuses to start if credential-like keys appear in YAML.
- All log output passes through a redaction filter covering known secret values plus
  `Authorization`, `OAuth`, `token`, `cookie` and `session_id` patterns.
- The provider library's own logger is capped at WARNING so it cannot echo request
  headers.
- No user data is sent anywhere except to Yandex Music itself. There is no telemetry.
- The only deletion path (`playlist.keep_daily_playlists`) is disabled by default and
  limited to playlists recorded as created by YaVolna in the local database.

## If you think your token leaked

Revoke it at <https://oauth.yandex.ru/client/my> (or change your account password, which
invalidates issued tokens), then issue a new one and update `.env`.
