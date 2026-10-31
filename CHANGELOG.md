# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.1] - 2026-10-15

### Added

- Within the same run, each distinct Docker image reference is checked for pulling only once, even if more worker services use the same image.
- Added `pyright` checking.

### Changed

- Generic code improvements.

## [1.0.0] - 2026-10-14

### Added

- Initial implementation, with connection to the Telemetry API, Docker image-updating, and YAML configuration. Fully containerised and made available through `systemd`.

### Changed

- Pinned Python to version 3.14.

### Fixed

- Duplicate `SUCCESS` reporting from both the orchestrator and the actual service that resulted in an invalid state transition.
- The algorithm that is checking whether a newer version of a worker service's Docker image exists and the request to eventually download it.
