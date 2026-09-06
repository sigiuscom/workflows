from pathlib import Path
import json
import os
import subprocess
import sys

import pytest

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


def test_scan_uses_cluster_server_and_bounded_timeout():
    workflow = document()
    inputs = workflow["on"]["workflow_call"]["inputs"]
    scan = workflow["jobs"]["scan"]

    assert inputs["trivy-server"]["default"] == "http://trivy-service.trivy-system:4954"
    assert inputs["trivy-timeout"]["default"] == "10m"
    assert scan["env"]["TRIVY_SERVER"] == "${{ inputs.trivy-server }}"
    assert scan["steps"][-1]["with"]["timeout"] == "${{ inputs.trivy-timeout }}"


@pytest.mark.parametrize("push", ["false", "true"])
def test_generated_job_and_secret_commands_respect_push_boundary(tmp_path, push):
    """Execute the production shell with a fake kubectl; never contact a cluster."""
    step = next(step for step in document()["jobs"]["build"]["steps"] if step.get("id") == "tags")
    fake = tmp_path / "kubectl"
    fake.write_text(f"#!{sys.executable}\n" + """
import json, os, pathlib, shutil, sys
args = sys.argv[1:]
root = pathlib.Path(os.environ["FIXTURE_DIR"])
with (root / "commands.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\\n")
if args[0] == "apply":
    shutil.copyfile(args[2], root / "job.yaml")
elif args[:2] == ["get", "pods"]:
    print("sha256:" + "a" * 64)
elif args[0] == "get" and "Complete" in args[-1]:
    print("True")
""")
    fake.chmod(0o755)
    # Only redirect absolute scratch/tool paths; execute all production decisions.
    script = step["run"].replace("/tmp/", str(tmp_path) + "/")
    # setup-python needs its Linux shared-library path when launching the fake kubectl.
    env = {key: os.environ[key] for key in ("PATH", "LD_LIBRARY_PATH") if key in os.environ}
    env["FIXTURE_DIR"] = str(tmp_path)
    env.update({key: "" for key in step["env"]})
    env.update({
        "INPUT_PUSH": push, "INPUT_CONTEXT": ".", "INPUT_IMAGE": "example.invalid/app",
        "INPUT_REGISTRY": "example.invalid", "INPUT_IMAGE_DOWNLOAD_RETRY": "3",
        "INPUT_KANIKO_MEMORY_LIMIT": "3Gi", "INPUT_KANIKO_CACHE": "true",
        "INPUT_KANIKO_CACHE_TTL": "168h", "GH_TOKEN": "synthetic-read-token",
        "GHCR_TOKEN": "synthetic-push-token", "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": "a" * 40, "GITHUB_REF_NAME": "test", "GITHUB_ACTOR": "tester",
        "GITHUB_SERVER_URL": "https://example.invalid", "GITHUB_REPOSITORY": "test/repo",
        "GITHUB_OUTPUT": str(tmp_path / "outputs"), "KANIKO_NAMESPACE": "test",
        "KANIKO_IMAGE": "example.invalid/kaniko",
    })
    subprocess.run(["bash", "-c", script], env=env, check=True, capture_output=True, text=True, timeout=10)
    commands = [json.loads(line) for line in (tmp_path / "commands.jsonl").read_text().splitlines()]
    created = [args for args in commands if args[:3] == ["create", "secret", "docker-registry"]]
    pod = yaml.safe_load((tmp_path / "job.yaml").read_text())["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert pod["automountServiceAccountToken"] is False
    if push == "true":
        assert len(created) == 1
        assert container["volumeMounts"] == [{"name": "docker-config", "mountPath": "/kaniko/.docker"}]
        assert pod["volumes"][0]["projected"]["sources"][0]["secret"]["name"] == created[0][3]
        assert "--no-push" not in container["args"]
        assert "--cache=true" in container["args"]
    else:
        assert not created
        assert not container.get("volumeMounts")
        assert not pod.get("volumes")
        assert "--no-push" in container["args"]
        assert "--cache=true" not in container["args"]
        assert "synthetic-push-token" not in (tmp_path / "job.yaml").read_text()
