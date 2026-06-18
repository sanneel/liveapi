# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Tag a release once its changes are on `main` and the deploy has passed
`deploy/deploy.sh` (which now gates on `scripts/phase_b_health.py`). Roll back
with the DB snapshot + `git reset` commands printed by that script.

## [Unreleased]

## [1.1.0] - 2026-06-18

### Added
- **Parser drift canary** (`app/parser/drift_canary.py`): each campaign-monitor
  cycle probes a live jugabet listing URL and classifies the result as
  `ok` / `drifted` / `unreachable` / `no_events`. A `drifted` result (the page
  still advertises events but the extractor returns 0 — i.e. jugabet changed
  their embedded JSON shape) flips `/health` to degraded and fires a Telegram
  alert on the ok↔drifted transition. Configurable via `PARSER_CANARY_ENABLED`
  / `PARSER_CANARY_URL`; covered by `scripts/test_drift_canary.py` in CI.
- Deep post-deploy verification is now a **hard gate** in `deploy/deploy.sh`:
  after the service health check it runs `scripts/phase_b_health.py` and aborts
  the deploy (with rollback guidance) on a real failure. The admin-override
  check is skipped unless `PHASE_B_USERNAME`/`PHASE_B_PASSWORD` are exported.
- `/health` now reports live match volume (`matches.active`, `matches.inactive`,
  `matches.total`) alongside the existing per-feed freshness and degraded-state
  detection.
- Advisory security scanning in CI: a non-blocking `security` job runs
  `pip-audit` and `bandit`, plus a Dependabot config for pip, GitHub Actions,
  and npm.
- `CHANGELOG.md` (this file).

## [1.0.0] - 2026-06-18

First tagged release: the verified-good baseline.

### Added
- GitHub Actions CI (`.github/workflows/ci.yml`): compile check, the standalone
  parser/deactivation regression tests, and a from-scratch Alembic migration.
- Handoff-grade `README.md` with an architecture diagram, operations quick
  reference, and an honest project-status section.

### Changed
- `scripts/auto_deploy.sh` is off by default (`AUTODEPLOY_ENABLED=1` required)
  with a `/health` gate after restart — continuous deploy-on-`main` is for
  staging, not production.
- `DEPLOY.md` clarifies the reverse-proxy story (reference config uses Caddy;
  production runs nginx) and drops stale 2FA instructions (2FA was removed from
  the user-facing auth flow).
- `app/middleware/security.py` CSP comment corrected: Tailwind is served from
  the local bundle, not a CDN; remaining CDN allowances are for
  Alpine/htmx/lucide (unpkg) and SortableJS (jsdelivr).

### Fixed
- `.env.example` `MATCH_DEACTIVATE_AFTER_HOURS` corrected `6` → `12` to match
  the code and docs.

### Security
- `scripts/wipe_matches.py` is now safe by default: it previews row counts and
  requires `--yes` to delete.

[Unreleased]: https://github.com/sanneel/liveapi/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/sanneel/liveapi/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/sanneel/liveapi/releases/tag/v1.0.0
