from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "docker-build.yml"


def document() -> dict:
    loader = type("Loader", (yaml.SafeLoader,), {})
    loader.add_constructor("tag:yaml.org,2002:bool", lambda loader, node: loader.construct_scalar(node))
    return yaml.load(WORKFLOW.read_text(), Loader=loader)


def test_reusable_workflow_publishes_immutable_image_outputs():
    workflow = document()
    outputs = workflow["on"]["workflow_call"]["outputs"]
    assert outputs["image-tag"]["value"] == "${{ jobs.build.outputs.image-tag }}"
    assert outputs["image-digest"]["value"] == "${{ jobs.build.outputs.image-digest }}"
    assert outputs["image-ref"]["value"] == "${{ jobs.build.outputs.image-ref }}"


def test_build_job_enables_bounded_remote_cache():
    text = WORKFLOW.read_text()
    assert "kaniko-cache" in text
    assert "kaniko-cache-ttl" in text
    assert 'add_arg "--cache=true"' in text
    assert 'add_arg "--cache-repo=${INPUT_IMAGE}-cache"' in text
    assert 'add_arg "--cache-ttl=${INPUT_KANIKO_CACHE_TTL}"' in text


def test_build_only_path_still_has_no_registry_secret_mount():
    text = WORKFLOW.read_text()
    assert 'if [ "$INPUT_PUSH" = "true" ]; then' in text
    assert "docker_mount_file" in text
    assert 'if [ "$INPUT_PUSH" != "true" ]; then' in text
    assert 'add_arg "--no-push"' in text


def test_default_primary_tag_contains_short_commit():
    text = WORKFLOW.read_text()
    immutable = 'echo "${INPUT_IMAGE}:${ref_name}-${short_sha}" >> "$tags_file"'
    moving = 'echo "${INPUT_IMAGE}:${ref_name}" >> "$tags_file"'
    assert text.index(immutable) < text.index(moving)


def test_scan_uses_digest_reference():
    workflow = document()
    build_outputs = workflow["jobs"]["build"]["outputs"]
    assert build_outputs["image-digest"]
    assert build_outputs["image-ref"]
    scan = workflow["jobs"]["scan"]
    serialized = yaml.safe_dump(scan)
    assert "needs.build.outputs.image-ref" in serialized
