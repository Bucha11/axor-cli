# Changelog

## 0.3.0 — 2026-04-29

### Added
- `ConfigCorruptError` raised when `~/.axor/config.toml` exists but cannot
  be parsed. The previous behaviour silently returned `{}` and let the
  next save **overwrite the broken file**, dropping any other adapter's
  saved key. Refusing to write preserves user data; the user is told to
  fix or delete the file.

### Fixed
- TOML escaping made spec-compliant. The old version only escaped `\` and
  `"`; pasting an API key that contained a newline (or any control byte)
  produced a file that crashed the next `tomllib.load()`. Now handles
  `\n`, `\r`, `\t`, `\b`, `\f`, plus a `\uXXXX` fallback for any other
  control char.

### Changed
- Model registry refreshed: `claude-sonnet-4-6`, `claude-opus-4-7`,
  `claude-haiku-4-5`. Default is `claude-sonnet-4-6`.

### Constraints
- Pin bump: `axor-core>=0.4.0,<0.5` (was `>=0.3.0`).

## 0.2.0 — 2026-04-24

### Added
- `axor-telemetry` integration. New `/telemetry` slash command:
  `status` / `on [--remote]` / `off` / `preview` / `consent`.
- One-time stderr opt-in banner. Marker file
  `~/.axor/.telemetry_notice_shown` suppresses subsequent prints;
  `AXOR_NO_BANNER=1` suppresses on-demand.
- `build_session` wires a `TelemetryPipeline` into `GovernedSession`.
- Optional `[telemetry]` extra: `pip install axor-cli[telemetry]`.
- 11 new bridge tests + smoke-test fix (44 total).

## 0.1.0 — 2026-04-14

Initial release of the `axor` CLI shell.
