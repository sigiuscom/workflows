# AGENTS.md

Shared guidance for coding agents; `CLAUDE.md` links to this file.

## Что это

`sigiuscom/workflows` -- центральный репозиторий **reusable GitHub Actions workflows** для всех `sigiuscom/*` репо. Reusable entrypoints объявлены через `on: workflow_call:` и вызываются из caller-репозиториев по ссылке `sigiuscom/workflows/.github/workflows/<name>.yml@main`. Pool ARC-раннеров в AKS задаётся `runs-on` каждого job: существующая trusted orchestration использует `aks-self-hosted`, а Python self-CI tests запускают код PR на `aks-untrusted`; не переносить этот untrusted execution на trusted pool.  сборка образов идёт через Kaniko Job в namespace `ci-builds` (Docker daemon / DinD запрещён политикой AKS).

## Состав / структура

Все workflow в `.github/workflows/`:

| Workflow | Назначение |
|---|---|
| `docker-build.yml` | Kaniko-сборка образа на AKS-раннере, опциональный push, Trivy-скан, registry mirrors/maps, retry |
| `bump-version.yml` | Bump semver в `VERSION`-файле, commit + tag (`v`-prefix), push с retry; outputs `new-version`, `new-tag` |
| `python-app.yml` | pip install + ruff + опц. mypy + pytest |
| `node-app.yml` | bun/npm/pnpm install + lint + typecheck + test + build |
| `helm-lint.yml` | `helm lint` + `helm template` + `kubeconform` по каждому чарту |
| `terraform.yml` | `terraform fmt -check` + `init` + `validate` + опц. `plan` |
| `yamllint.yml` | YAML lint с GitHub annotations |
| `gitleaks.yml` | Сканирование секретов по всей git-истории |
| `opengrep.yml` | SAST (Opengrep, Semgrep-совместимые правила), SARIF |
| `nuclei.yml` | DAST по живым HTTP-эндпоинтам (Nuclei), SARIF/JSONL -- не в дефолтном push-CI, вызывать осознанно |

`renovate.json` -- конфиг Renovate для этого репо.

## Использование / команды

Вызов reusable docker-build из caller-репо (`.github/workflows/ci.yml`):

```yaml
jobs:
  docker:
    uses: sigiuscom/workflows/.github/workflows/docker-build.yml@main
    with:
      image: ghcr.io/sigiuscom/<service>   # full image без тега (required)
      push: true                            # default false
      context: '.'                          # default '.'
      dockerfile: ''                         # default {context}/Dockerfile
      platforms: 'linux/amd64'              # Kaniko поддерживает только amd64
      version: ${{ needs.bump.outputs.new-version }}  # generates :X.Y.Z :X.Y :X :latest
      ref: ${{ needs.bump.outputs.new-tag }}          # ref для checkout (после bump tag)
    secrets:
      GHCR_TOKEN: ${{ secrets.GHCR_TOKEN }}  # опц., fallback на GITHUB_TOKEN
```

Без `version` тегирует как `:<ref_name>` и `:<ref_name>-<short_sha>`. Inputs: `build-args`, `registry`, `registry-mirrors`, `registry-maps`, `insecure-registries`, `image-download-retry`, `trivy-scan`/`trivy-severity`/`trivy-ignore-unfixed` (Trivy-скан только при `push=true`).

Типовой пайплайн релиза (см. `garmin_watcher_bot/.github/workflows/shared-ci.yml`): `gitleaks` + `python` -> `bump-version` -> `docker-build` (с `version`/`ref` от bump).

Добавление нового reusable workflow:
1. Создать `.github/workflows/<name>.yml` с `on: workflow_call:`.
2. Запинить каждый third-party action по commit SHA.
3. Добавить в каталог README.

## Ключевые детали

- Все third-party actions запинены по commit SHA.
- Все джобы ставят `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: 'true'` (Node 20 deprecated, июнь 2026).
- Дефолтные permissions `contents: read` (least privilege); `docker-build` добавляет `packages: write`, `bump-version` -- `contents: write`.
- `docker-build` собирает Kaniko Job из runner-пода в `ci-builds`: создаёт временные Secret'ы, клонирует через `git://` контекст, ждёт Complete/Failed (до ~15 мин), стримит логи, чистит секреты. Только `linux/amd64`.
- **docker-registry Secret создаётся и монтируется только при `push: true`.** Это push-credential, а `push: false` -- валидация Dockerfile из PR, где каждый `RUN` -- код автора PR. Базовые образы публичные и идут через zot-mirror, так что build-only не нуждается в registry-auth. Egress самого namespace ограничен `ci-builds-egress` (azinfra `github-actions-runners/kaniko/networkpolicy.yaml`).
- GHCR push: `GHCR_TOKEN` если есть, иначе `GITHUB_TOKEN` (`secrets: inherit` / явный проброс из caller).
- Не-GHCR registry (например ACR): `REGISTRY_USERNAME` + `REGISTRY_PASSWORD`. Они перекрывают `github.actor`/`GHCR_TOKEN` и в push-секрете Kaniko, и в Trivy-скане. Не заданы -- поведение прежнее.
- Org-настройка обязательна: reusable workflows из private-репо должны быть разрешены на уровне организации `sigiuscom`.

## Связанное

- Operational hub (ARC runners, ci-builds, GHCR): `../CLAUDE.md`
- Связанные: `../infra/CLAUDE.md` (ARC runner scale sets, kaniko RBAC). `workflows` используется всеми `sigiuscom`-репо для сборки образов.
