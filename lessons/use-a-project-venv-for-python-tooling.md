---
type: lesson
title: Use a project virtual environment for Python tooling
description: Repository validation should use an ignored project venv with pinned dependencies instead of silently degrading under system Python.
tags: [workflow]
date: 2026-08-28
---

# Use a project virtual environment for Python tooling

## Active

Run non-trivial repository Python tooling through a repository-owned, ignored
virtual environment. Keep its development dependencies pinned in a tracked
requirements file and provide an idempotent bootstrap command that creates or
refreshes the environment.

Verification should require that interpreter and fail with a clear setup
instruction when it or a required import is missing. Do not fall back to system
Python or convert a missing validation dependency into a warning that silently
skips the check. Dependency installation belongs in setup; routine verification
should consume the prepared environment without resolving packages itself.

Before pinning a dependency, confirm that the selected release supports the
repository's Python versions and platforms. Prefer a published wheel when an
otherwise unnecessary source build would make setup fragile.

## Source

Observed while repairing a repository gate whose official validator was being
skipped because system Python lacked its YAML dependency. Creating a project
venv, pinning the dependency, and requiring that interpreter made the validator
execute successfully and reproducibly.
