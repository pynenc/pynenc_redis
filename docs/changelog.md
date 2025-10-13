# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.4] - 2024-10-02

### Added

- PR validation workflow to ensure PR descriptions meet quality standards for automated release notes
- Validates conventional commit format and appropriate labels for Release Drafter categorization
- Automatic label assignment based on PR title via Release Drafter autolabeler
- Made PR labels mandatory for proper release notes categorization
- Release Drafter now runs on PR events to enable automatic labeling

## [0.1.0] - 2025-09-05

### Initial commit

Moving Redis backend from pynenc to a new repository for this plugging.
Adapt it to the plugging system
Move specific tests and reuse pynenc_tests module
Create new pluggin specific docs
