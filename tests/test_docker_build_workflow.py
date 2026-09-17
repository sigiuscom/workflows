from pathlib import Path
import json
import os
import re
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
        "INPUT_BUILD_TIMEOUT_MINUTES": "45",
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


def run_build_failure_fixture(tmp_path, scenario):
    step = next(step for step in document()["jobs"]["build"]["steps"] if step.get("id") == "tags")
    fake = tmp_path / "kubectl"
    fake.write_text(f"#!{sys.executable}\n" + """
import json, os, pathlib, shutil, sys
args = sys.argv[1:]
root = pathlib.Path(os.environ["FIXTURE_DIR"])
with (root / "commands.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\\n")
if args[0] == "apply":
    count_file = root / "apply-count"
    count = int(count_file.read_text()) + 1 if count_file.exists() else 1
    count_file.write_text(str(count))
    shutil.copyfile(args[2], root / f"job-{count}.yaml")
elif args[0] == "get" and args[1].startswith("job/"):
    count = int((root / "apply-count").read_text())
    condition = args[-1]
    if os.environ["SCENARIO"] in {"permanent", "persistent"} or (
        os.environ["SCENARIO"] in {"transient", "http2-stream"} and count == 1
    ):
        print("True" if "Failed" in condition else "")
    else:
        print("True" if "Complete" in condition else "")
elif args[0] == "logs":
    count = int((root / "apply-count").read_text())
    if os.environ["SCENARIO"] == "persistent" or (
        os.environ["SCENARIO"] == "transient" and count == 1
    ):
        print("error pulling image: BLOB_UNKNOWN: blob is unknown to registry")
    elif os.environ["SCENARIO"] == "http2-stream" and count == 1:
        print(
            "failed to get filesystem from image: stream error: "
            "stream ID 11; INTERNAL_ERROR; received from peer"
        )
    elif os.environ["SCENARIO"] == "permanent":
        print("error building image: Dockerfile parse error")
elif args[:2] == ["get", "pods"]:
    print("sha256:" + "a" * 64)
""")
    fake.chmod(0o755)
    sleeper = tmp_path / "sleep"
    sleeper.write_text("#!/bin/sh\nexit 0\n")
    sleeper.chmod(0o755)
    script = step["run"].replace("/tmp/", str(tmp_path) + "/")
    env = {key: os.environ[key] for key in ("PATH", "LD_LIBRARY_PATH") if key in os.environ}
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    env["FIXTURE_DIR"] = str(tmp_path)
    env["SCENARIO"] = scenario
    env.update({key: "" for key in step["env"]})
    env.update({
        "INPUT_PUSH": "false", "INPUT_CONTEXT": ".", "INPUT_IMAGE": "example.invalid/app",
        "INPUT_REGISTRY": "example.invalid", "INPUT_IMAGE_DOWNLOAD_RETRY": "3",
        "INPUT_KANIKO_MEMORY_LIMIT": "3Gi", "INPUT_KANIKO_CACHE": "true",
        "INPUT_BUILD_TIMEOUT_MINUTES": "45",
        "INPUT_KANIKO_CACHE_TTL": "168h", "GH_TOKEN": "synthetic-read-token",
        "GHCR_TOKEN": "", "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": "a" * 40, "GITHUB_REF_NAME": "test", "GITHUB_ACTOR": "tester",
        "GITHUB_SERVER_URL": "https://example.invalid", "GITHUB_REPOSITORY": "test/repo",
        "GITHUB_OUTPUT": str(tmp_path / "outputs"), "KANIKO_NAMESPACE": "test",
        "KANIKO_IMAGE": "example.invalid/kaniko",
    })
    return subprocess.run(
        ["bash", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_transient_registry_failure_retries_with_fresh_job(tmp_path):
    result = run_build_failure_fixture(tmp_path, "transient")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "apply-count").read_text() == "2"
    first = yaml.safe_load((tmp_path / "job-1.yaml").read_text())
    second = yaml.safe_load((tmp_path / "job-2.yaml").read_text())
    assert first["metadata"]["name"] != second["metadata"]["name"]
    assert first["spec"]["backoffLimit"] == second["spec"]["backoffLimit"] == 0
    assert first["spec"]["template"]["spec"]["containers"][0]["args"] == (
        second["spec"]["template"]["spec"]["containers"][0]["args"]
    )
    for job in (first, second):
        pod = job["spec"]["template"]["spec"]
        assert not pod.get("volumes")
        assert not pod["containers"][0].get("volumeMounts")


def test_transient_http2_stream_failure_retries_with_fresh_job(tmp_path):
    result = run_build_failure_fixture(tmp_path, "http2-stream")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "apply-count").read_text() == "2"


def test_permanent_build_failure_is_not_retried(tmp_path):
    result = run_build_failure_fixture(tmp_path, "permanent")

    assert result.returncode != 0
    assert (tmp_path / "apply-count").read_text() == "1"
    assert "non-transient build failure; not retrying" in result.stderr


def test_persistent_transient_failure_stops_after_three_jobs(tmp_path):
    result = run_build_failure_fixture(tmp_path, "persistent")

    assert result.returncode != 0
    assert (tmp_path / "apply-count").read_text() == "3"
    assert "transient build failure persisted for 3 attempts" in result.stderr


def test_build_wait_window_is_an_input_not_a_magic_number():
    """A 900s hardcoded window failed builds that were going to succeed.

    A runner-sized image takes about 8 minutes on a quiet cluster and close to 19
    when several builds snapshot at once, so the budget has to be adjustable per
    caller rather than a constant someone has to find in a shell loop.
    """
    workflow = document()
    spec = workflow["on"]["workflow_call"]["inputs"]["build-timeout-minutes"]
    assert spec["type"] == "number"
    assert int(spec["default"]) >= 30
    assert "every build attempt" in spec["description"]

    text = WORKFLOW.read_text()
    assert "INPUT_BUILD_TIMEOUT_MINUTES: ${{ inputs.build-timeout-minutes }}" in text
    assert "seq 1 180" not in text


def _build_step_script() -> str:
    workflow = document()
    for step in workflow["jobs"]["build"]["steps"]:
        if "budget_end_ts" in (step.get("run") or ""):
            return step["run"]
    raise AssertionError("no build step drives the wait loop")


def test_an_exhausted_budget_stops_before_starting_an_attempt():
    """set -u plus a loop that never runs killed the step before it could reap.

    The counted version could produce an empty loop and leave $complete unset; the
    clock-based one can start with no time left. Either way the step has to reach
    its own diagnostics rather than dying on an unbound variable.
    """
    script = _build_step_script()
    guard = [
        line.strip()
        for line in script.splitlines()
        if line.strip().startswith(("remaining=", 'if [ "$remaining" -lt'))
    ]
    assert guard, "nothing checks the remaining budget before an attempt"

    program = (
        "set -euo pipefail\n"
        "budget_end_ts=$(( $(date +%s) - 1 ))\n"
        "min_attempt_seconds=60\n"
        "build_attempt=1\n"
        + "\n".join(guard)
        + '\n  echo REFUSED\n  exit 0\nfi\necho STARTED\n'
    )
    result = subprocess.run(["bash", "-c", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "REFUSED" in result.stdout, result.stdout


def test_a_job_we_stop_waiting_for_is_deleted():
    """The expiry path used to return without deleting the Job.

    Kaniko kept running and kept snapshotting against the disk the next build
    needed, so one slow wave produced the next one. This asserts the reaping is
    reachable, not merely present: removing what sets the flag used to leave the
    block as dead code with the suite still green.
    """
    script = _build_step_script()
    assert "timed_out=1" in script, "nothing arms the reaping block"

    arming = script.split("timed_out=1", 1)[0]
    assert arming.rstrip().endswith("then"), "timed_out is set outside a condition"

    reaping = script.split('if [ "$timed_out" -eq 1 ]; then', 1)[1].split("fi", 1)[0]
    assert "kubectl delete job" in reaping
    assert "--ignore-not-found" in reaping
    assert "exit 1" in reaping


def _simulate(script: str, budget: int, attempt_seconds: int) -> dict:
    """Run the step's real bound arithmetic for a budget and a per-attempt duration."""
    lines = [
        line.strip()
        for line in script.splitlines()
        if line.strip().startswith(("budget_seconds=", "budget_end_ts=",
                                    "min_attempt_seconds=", "remaining=",
                                    "attempt_end_ts=", "build_backstop_seconds="))
    ]
    assert lines, "the build step no longer derives its bounds"
    # lines[:3] run under the real clock, lines[3:] under the stub. A fourth
    # pre-loop assignment would silently move an in-loop binding into the wrong
    # half and simulate something else entirely.
    assert lines[2].startswith("min_attempt_seconds="), (
        "the pre-loop bounds moved; update the split in _simulate"
    )
    program = (
        f"INPUT_BUILD_TIMEOUT_MINUTES={budget}\n"
        + "\n".join(lines[:3])
        + f"\nnow_offset={attempt_seconds}\n"
        + "date() { echo $(( $(command date +%s) + now_offset )); }\n"
        + "\n".join(lines[3:])
        + '\necho "$budget_seconds $remaining $build_backstop_seconds"\n'
    )
    result = subprocess.run(["bash", "-c", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    budget_seconds, remaining, backstop = (int(v) for v in result.stdout.split())
    return {"budget": budget_seconds, "remaining": remaining, "backstop": backstop}


def test_each_bound_fires_before_the_one_behind_it():
    """Three bounds guard this build and only the innermost can explain itself.

    If the Job deadline fires first the build reports DeadlineExceeded, which reads
    as a broken Dockerfile; if GitHub's job timeout fires first nothing reports at
    all. The wait is measured against the clock, so this ordering holds at any
    budget -- a counted loop would have drifted past the backstop as the iteration
    count grew, because each pass also pays two API round trips.
    """
    workflow = document()
    budget = int(workflow["on"]["workflow_call"]["inputs"]["build-timeout-minutes"]["default"])
    script = _build_step_script()

    for candidate in (budget, 6, 90, 165):
        bounds = _simulate(script, candidate, attempt_seconds=0)
        job_timeout = candidate * 60
        assert bounds["remaining"] < bounds["backstop"] < job_timeout, (candidate, bounds)

    text = WORKFLOW.read_text()
    assert "activeDeadlineSeconds: ${build_backstop_seconds}" in text
    assert 'while [ "$(date +%s)" -lt "$attempt_end_ts" ]; do' in text
    assert "seq 1" not in text
    assert (
        workflow["jobs"]["build"]["timeout-minutes"]
        == "${{ inputs.build-timeout-minutes }}"
    )


def test_a_later_attempt_gets_what_is_left_rather_than_a_fresh_window():
    """The retry exists for BLOB_UNKNOWN, which happens on push at the end of a build.

    Budgeting one attempt would leave that retry unreachable in the one case it was
    written for, and three fresh windows would outlive the job timeout with nothing
    but GitHub's own cancellation to show for it.
    """
    script = _build_step_script()
    budget = 45
    early = _simulate(script, budget, attempt_seconds=0)
    late = _simulate(script, budget, attempt_seconds=1500)

    assert late["remaining"] < early["remaining"]
    assert late["backstop"] < early["backstop"]
    assert late["remaining"] + 1500 <= early["budget"] + 5

    text = WORKFLOW.read_text()
    assert 'remaining="$(( budget_end_ts - $(date +%s) ))"' in text
    assert 'if [ "$remaining" -lt "$min_attempt_seconds" ]; then' in text


def test_the_smallest_accepted_budget_still_leaves_a_window():
    """Validation and arithmetic have to agree, or the floor produces an empty wait."""
    text = WORKFLOW.read_text()
    floor = int(re.search(r'\[ "\$timeout" -lt (\d+) \]', text).group(1))
    script = _build_step_script()
    bounds = _simulate(script, floor, attempt_seconds=0)
    assert bounds["budget"] > 0
    assert bounds["remaining"] >= 60, "the floor must still allow one attempt to start"


def test_a_nearly_spent_budget_refuses_the_next_attempt():
    """A threshold of zero would start an attempt with seconds left to spend.

    It would time out immediately, reap, and exit -- noise where a refusal with the
    remaining time is the useful message. Pinning the structure of the guard does
    not pin its magnitude, so this exercises it firing.
    """
    script = _build_step_script()
    threshold = int(
        re.search(r"min_attempt_seconds=(\d+)", script).group(1)
    )
    assert threshold >= 30, "a threshold this small starts attempts that cannot finish"

    nearly_spent = _simulate(script, 45, attempt_seconds=(45 - 5) * 60 - 10)
    assert nearly_spent["remaining"] < threshold, nearly_spent


def test_a_padded_budget_is_read_as_decimal():
    """045 passes the digit check; without 10# the arithmetic would read it as octal."""
    script = _build_step_script()
    assert _simulate(script, 45, 0)["budget"] == _simulate(script, "045", 0)["budget"]


def test_builds_are_spread_across_nodes_rather_than_queued():
    """Disk is what saturates, and seven snapshots on one node is how it saturated.

    A concurrency cap would fix contention by making builds wait, which is the
    thing being removed. Spreading keeps every build starting immediately.
    """
    text = WORKFLOW.read_text()
    assert "topologySpreadConstraints" in text
    assert "topologyKey: kubernetes.io/hostname" in text
    assert "whenUnsatisfiable: ScheduleAnyway" in text
    assert "app.kubernetes.io/component: kaniko-build" in text
