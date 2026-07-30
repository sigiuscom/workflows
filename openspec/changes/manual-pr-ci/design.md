# Design

## Chosen approach
Keep CI logic in `sigiuscom/workflows` reusable workflows and add thin caller workflows only where a repository lacks coverage. Extend Docker validation with a no-push amd64 Kaniko mode. Keep all merge decisions manual.

## Checks
- Node projects: install, lint, typecheck when configured, tests, and build.
- Python projects: install, Ruff, tests, and optional mypy.
- Docker projects: lint/test plus no-push `linux/amd64` Kaniko builds for declared Dockerfiles.
- GitOps projects: YAML lint, Helm lint/template where charts exist, Kustomize build where overlays exist, and secret scanning.
- Workflow repository: actionlint/YAML validation for reusable workflows.

## Safety
All reusable workflow refs in callers use immutable commits. Workflows have read-only contents permissions unless an existing release workflow explicitly needs writes. No workflow invokes `gh pr merge`, enables automerge, or deploys production from pull requests.

## Rollout
Implement reusable additions first, then caller workflows in batches. Validate YAML syntax and local command selection before pushing. Existing project-specific workflows remain unchanged unless they duplicate or conflict with the new checks.

## Excluded
`uchetika-cloud` is intentionally excluded from this rollout.
