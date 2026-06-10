# sigiuscom/workflows

Reusable GitHub Actions workflows for all `sigiuscom/*` repos.

## How to consume

Add a caller workflow in your repo (e.g. `.github/workflows/ci.yml`):

```yaml
name: CI
on:
  push:
    branches: [main, master]
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  gitleaks:
    uses: sigiuscom/workflows/.github/workflows/gitleaks.yml@main

  yamllint:
    uses: sigiuscom/workflows/.github/workflows/yamllint.yml@main
    with:
      paths: 'charts'

  helm:
    uses: sigiuscom/workflows/.github/workflows/helm-lint.yml@main
    with:
      charts-dir: 'charts'
```

## Catalog

| Workflow | Purpose |
|---|---|
| `gitleaks.yml` | Secret scanning across full git history |
| `yamllint.yml` | YAML lint with GitHub annotations |
| `helm-lint.yml` | `helm lint` + `helm template` + `kubeconform` for every chart |
| `terraform.yml` | `terraform fmt -check`, `init`, `validate`, optional `plan` |
| `node-app.yml` | bun/npm/pnpm install + lint + typecheck + test + build |
| `python-app.yml` | pip install + ruff + optional mypy + pytest |
| `docker-build.yml` | Kaniko image builds on AKS runners with optional push, Trivy scan, registry mirrors, and retry controls |

## Conventions

- All actions are pinned by commit SHA.
- All jobs set `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` (Node 20 deprecation in June 2026).
- All jobs run on `ubuntu-24.04`.
- Default permissions are `contents: read` (least privilege). Override per caller if needed.

## Adding a new reusable workflow

1. Create `.github/workflows/<name>.yml` with `on: workflow_call:`.
2. Pin every third-party action by SHA.
3. Document in the catalog above.

## Org settings prerequisite

GitHub org must allow reusable workflows from private repos:
`Settings -> Actions -> General -> Access` -> "Accessible from repositories in the 'sigiuscom' organization".
