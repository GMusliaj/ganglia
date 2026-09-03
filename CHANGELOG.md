# Changelog

Notable changes to Ganglia are recorded here. This project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added reproducible Python, JavaScript, and shell security checks with a
  pinned development environment and a read-only GitHub Actions workflow.

### Changed

- Renamed the project and its public interfaces to Ganglia.
- Replaced the previous bracket logo with a branching ganglion network and a
  symbol-only favicon asset.
- Refreshed the README canvas preview with the Ganglia identity and collection
  label.
- Reused Ganglia's repository-owned skill validator instead of copied Codex
  skill-creation scripts.

### Fixed

- Prevented the generic GitHub Actions `/home/runner` account from triggering
  the private-identity publication guard.

### Security

- Added fail-closed source scanning with Bandit, ShellCheck, and ESLint, plus
  live Python and npm dependency advisory checks.
