# Manual PR CI rollout

## Problem
Several Sigius repositories expose Renovate PRs without enough automated evidence for daily manual review. Docker, GitOps, and application checks are inconsistent.

## Goal
Provide reusable, non-merging CI checks that make PR safety visible before a human decides whether to merge.

## Scope
Add or extend checks for prbuff, rabbithole, folio, observability, langfuse, azinfra, workflows, matcher, gettrace, tg-transcriber, callhero, and holmesgpt. Exclude uchetika-cloud.

## Non-goals
- No automerge, merge queues, or automatic PR approval.
- No production deployment or rollout from PR CI.
- No broad application refactors.

## Success criteria
- PR workflows run on pull requests and report deterministic checks.
- Docker projects validate linux/amd64 images through the existing Kaniko reusable workflow without pushing images.
- GitOps projects validate YAML, Helm/Kustomize structure, and security scans where applicable.
- Application projects run their documented lint, typecheck, test, and build commands.
- All workflow references are pinned to immutable commits.
