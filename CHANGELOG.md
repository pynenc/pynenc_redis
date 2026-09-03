# Changelog

## 0.4.0 - 2026-08-31

### Added

- Named broker queues with native float priorities and FIFO ordering for equal priorities.
- Runner heartbeat metadata for consumed queues.

### Breaking

- Broker queues now use a new sorted-set storage shape. Existing pre-0.4
  broker keys are not migrated; clear or recreate broker data before upgrading.

### Changed

- Requires Pynenc 0.4.0 and Python 3.12 or newer.
