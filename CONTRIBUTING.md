# Contributing

## Setup

You need Python 3.11 or newer, [uv](https://docs.astral.sh/uv/) and a running Docker Engine for
the integration tests.

    uv sync
    uv run anchorage

## Checks

Every change has to pass the same checks as CI:

    uv run ruff check .
    uv run ruff format --check .
    uv run mypy
    uv run pytest -q -W error

The tests run with Qt's offscreen platform, so no display is needed. Integration tests talk to
a real daemon and are skipped by default:

    uv run pytest -m integration

## Packages

`packaging/build.sh <arch|deb|rpm|universal|all>` builds packages in Docker containers and
installs each one in a fresh container of its target distribution. Run the target you touched
when you change anything under `packaging/`.

## Commits and pull requests

Write commit subjects in the imperative mood ("Add a settings dialog"), keep each commit to
one change, and add or update tests with behaviour changes. Pull requests run CI and the
package builds; a pull request is merged once both are green and the change has been reviewed.
