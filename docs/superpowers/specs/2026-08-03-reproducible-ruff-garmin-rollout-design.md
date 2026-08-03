# Reproducible Ruff and Garmin Rollout Design

## Goal

Restore `garmin-watcher#28` without weakening lint enforcement, then deploy the resulting release to Synology with immutable verification.

## Design

The reusable `python-app` workflow will expose an optional `ruff-version` input whose default is the last known-green Garmin version, `0.15.22`. The install step will pass the input through an environment variable and install `ruff==$RUFF_VERSION` alongside pytest. This makes the default toolchain reproducible while allowing callers to opt into later Ruff releases deliberately.

The workflows change will be reviewed and merged independently. `garmin-watcher#28` will then be refreshed to the exact merged workflows commit rather than `main`. Its exact head must be `MERGEABLE/CLEAN` with all relevant checks green before merge. The successor default-branch run must complete successfully and publish a new immutable image tag.

Deployment is a separate production gate. Before mutation, record the current container image, compose configuration, status, and logs without exposing environment values. Update only the Garmin image reference using the host's existing deployment mechanism. Verify the expected immutable image, container readiness, no restart loop, and successful scheduler startup. If verification fails, restore the recorded prior image through the same mechanism.

## Scope

- Pin Ruff in `.github/workflows/python-app.yml`.
- Document the new workflow input.
- Merge the workflows PR only after validation.
- Refresh, validate, and merge `garmin-watcher#28`.
- Verify successor CI and the published image.
- Deploy that release to the existing Synology Garmin container.

## Non-goals

- Fix or suppress the 32 findings introduced by Ruff 0.16.1.
- Change Garmin application code, secrets, session data, schedules, volumes, or network settings.
- Modify unrelated reusable workflows or production services.

## Validation

- Parse all workflow YAML and inspect the rendered input/install expression.
- Confirm a clean temporary Python environment installs Ruff `0.15.22` and passes the Garmin lint baseline and tests.
- Require immutable exact-head SHA, `MERGEABLE/CLEAN`, and green relevant checks for both PRs.
- Require green successor CI and identify the published image tag/digest before deployment.
- Confirm the deployed container uses the intended image, remains running without new restarts, and emits healthy startup/scheduler logs.
