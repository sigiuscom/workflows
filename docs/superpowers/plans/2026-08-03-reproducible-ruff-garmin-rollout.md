# Reproducible Ruff and Garmin Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin the reusable Ruff toolchain, unblock and merge Garmin PR #28, and safely deploy its verified release to Synology.

**Architecture:** Add a backward-compatible workflow input with a deterministic default, merge it independently, then repin Garmin to that immutable workflows commit. Treat production rollout as a separate gated operation with recorded rollback state and post-deploy health checks.

**Tech Stack:** GitHub Actions reusable workflows, YAML, Ruff, pytest, GitHub CLI, Docker Compose on Synology.

---

### Task 1: Pin Ruff in the reusable Python workflow

**Files:**
- Modify: `.github/workflows/python-app.yml`
- Modify: `README.md`
- Test: temporary shell/Python validation commands

- [ ] **Step 1: Establish the failing reproducibility check**

Run:

```bash
python - <<'PY'
from pathlib import Path
text = Path('.github/workflows/python-app.yml').read_text()
assert 'ruff-version:' in text
assert 'pip install "ruff==$RUFF_VERSION" pytest' in text
PY
```

Expected: FAIL because the workflow has neither the input nor a versioned install.

- [ ] **Step 2: Add the minimal workflow input and install pin**

Add under `workflow_call.inputs`:

```yaml
      ruff-version:
        description: Ruff version installed for linting
        type: string
        required: false
        default: '0.15.22'
```

Change the Install step environment and final command to:

```yaml
        env:
          INSTALL_CMD: ${{ inputs.install-cmd }}
          RUFF_VERSION: ${{ inputs.ruff-version }}
        run: |
          set -e
          if [ -n "$INSTALL_CMD" ]; then
            eval "$INSTALL_CMD"
          elif [ -f pyproject.toml ]; then
            pip install -e ".[dev]" 2>/dev/null || pip install -e .
          elif [ -f requirements.txt ]; then
            pip install -r requirements.txt
            [ -f requirements-dev.txt ] && pip install -r requirements-dev.txt || true
          fi
          pip install "ruff==$RUFF_VERSION" pytest
```

- [ ] **Step 3: Document the input**

Update the Python workflow section of `README.md` to state that `ruff-version` defaults to `0.15.22` and callers should override it only as an explicit lint-toolchain upgrade.

- [ ] **Step 4: Validate syntax and deterministic installation**

Run:

```bash
ruby -e 'require "yaml"; Dir[".github/workflows/*.yml"].each { |f| YAML.load_file(f, aliases: true) }'
python - <<'PY'
from pathlib import Path
text = Path('.github/workflows/python-app.yml').read_text()
assert 'ruff-version:' in text
assert "default: '0.15.22'" in text
assert 'RUFF_VERSION: ${{ inputs.ruff-version }}' in text
assert 'pip install "ruff==$RUFF_VERSION" pytest' in text
PY
python -m venv "$JCODE_SCRATCH_DIR/ruff-pin-check"
"$JCODE_SCRATCH_DIR/ruff-pin-check/bin/pip" install -q 'ruff==0.15.22'
"$JCODE_SCRATCH_DIR/ruff-pin-check/bin/ruff" --version
```

Expected: YAML parses and Ruff reports `ruff 0.15.22`.

- [ ] **Step 5: Validate against Garmin's exact PR head**

Run from the isolated Garmin checkout:

```bash
.venv/bin/pip install -q 'ruff==0.15.22'
.venv/bin/ruff check .
PYTHONPATH=. .venv/bin/pytest --tb=short -q
```

Expected: Ruff passes and pytest reports `10 passed`.

- [ ] **Step 6: Commit the workflow change**

```bash
git add .github/workflows/python-app.yml README.md docs/superpowers/
git commit -m "fix(python): pin default ruff version"
```

### Task 2: Review and merge the workflows PR

**Files:**
- No additional source changes expected

- [ ] **Step 1: Push the branch and open a PR**

```bash
git push -u origin fix/pin-python-tools
gh pr create --repo sigiuscom/workflows --base main --head fix/pin-python-tools --title 'fix(python): pin default ruff version' --body-file "$JCODE_SCRATCH_DIR/workflows-pr-body.md"
```

The body must describe the floating Ruff regression, backward-compatible input, Garmin baseline validation, and test commands.

- [ ] **Step 2: Capture immutable PR state**

```bash
gh pr view <PR_NUMBER> --repo sigiuscom/workflows --json headRefOid,baseRefOid,mergeable,mergeStateStatus,statusCheckRollup
```

Expected: the captured head equals the reviewed local commit, `MERGEABLE/CLEAN`, and every relevant check is successful.

- [ ] **Step 3: Squash merge and verify successor CI**

```bash
gh pr merge <PR_NUMBER> --repo sigiuscom/workflows --squash --delete-branch --match-head-commit <EXACT_HEAD_SHA>
gh run list --repo sigiuscom/workflows --branch main --limit 10
```

Expected: merged commit exists on `main`; all workflows triggered for that commit complete successfully.

### Task 3: Refresh and merge Garmin PR #28

**Files:**
- Modify on PR branch: `.github/workflows/shared-ci.yml`
- Modify on PR branch: `.github/workflows/ci.yml` if it references the same old digest

- [ ] **Step 1: Update only reusable-workflow digests**

Replace the old workflows SHA with the exact merged workflows commit in every existing `sigiuscom/workflows/.github/workflows/...@<sha>` reference. Do not change application code or other dependencies.

- [ ] **Step 2: Validate the refreshed branch locally**

```bash
git diff --check
git diff --stat origin/main...HEAD
ruff check .
PYTHONPATH=. pytest --tb=short -q
```

Expected: diff contains only intended workflow pins, Ruff passes with `0.15.22`, and pytest reports `10 passed`.

- [ ] **Step 3: Push and require exact-head green CI**

```bash
git push origin HEAD:<RENOVATE_BRANCH>
gh pr view 28 --repo sigiuscom/garmin-watcher --json headRefOid,baseRefOid,mergeable,mergeStateStatus,statusCheckRollup
```

Expected: `MERGEABLE/CLEAN`; gitleaks, Python CI, Semgrep, release bump, and Docker build checks are successful as applicable to a PR.

- [ ] **Step 4: Squash merge immutable head**

```bash
gh pr merge 28 --repo sigiuscom/garmin-watcher --squash --delete-branch --match-head-commit <EXACT_HEAD_SHA>
```

Expected: GitHub accepts the exact reviewed head and returns the merged commit.

- [ ] **Step 5: Verify successor release pipeline**

```bash
gh run list --repo sigiuscom/garmin-watcher --branch main --limit 10
gh run view <RUN_ID> --repo sigiuscom/garmin-watcher --json headSha,status,conclusion,jobs
```

Expected: successor run targets the merge commit, completes successfully, creates the next version tag, and publishes `ghcr.io/sigiuscom/garmin-watcher:<VERSION>`.

### Task 4: Deploy the verified Garmin release to Synology

**Files:**
- Modify on Synology: only the existing Garmin Compose image reference, using its current deployment mechanism

- [ ] **Step 1: Capture non-secret rollback state**

Run read-only commands to record container image ID, configured image reference, restart count, compose project labels, mounts, and recent startup logs. Do not print environment variables or secret file contents.

Expected: current known state includes `ghcr.io/sigiuscom/garmin-watcher:0.1.2` and a usable compose project/config path.

- [ ] **Step 2: Pull and inspect the verified release**

```bash
ssh syn '/usr/local/bin/docker pull ghcr.io/sigiuscom/garmin-watcher:<VERSION>'
ssh syn '/usr/local/bin/docker image inspect ghcr.io/sigiuscom/garmin-watcher:<VERSION> --format "{{json .RepoDigests}}"'
```

Expected: pull succeeds and the digest matches the image produced by successor CI or GHCR metadata.

- [ ] **Step 3: Update only the image reference and recreate Garmin**

Use the discovered compose command and project path to change the Garmin service image to `ghcr.io/sigiuscom/garmin-watcher:<VERSION>`, then recreate only that service. Preserve environment, volumes, networks, restart policy, and all other services.

- [ ] **Step 4: Verify production health**

```bash
ssh syn '/usr/local/bin/docker inspect garmin-watcher --format "image={{.Config.Image}} status={{.State.Status}} running={{.State.Running}} restarts={{.RestartCount}}"'
ssh syn '/usr/local/bin/docker logs --since 10m garmin-watcher 2>&1 | tail -100'
```

Expected: exact new image reference, running status, no restart growth, no traceback/authentication failure, and scheduler/bot startup evidence.

- [ ] **Step 5: Roll back on failed health checks**

If any expected health condition fails, restore `ghcr.io/sigiuscom/garmin-watcher:0.1.2` through the same compose mechanism, recreate only Garmin, and repeat the status/log checks. Report the failed release without altering secrets or session data.
