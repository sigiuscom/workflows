import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ADAPTER = Path(__file__).parents[1] / "agent-hooks" / "safety_net.py"
PAYLOAD = json.dumps({
    "hook_event_name": "PreToolUse", "tool_name": "Bash",
    "tool_input": {"command": "echo safe"}, "cwd": "/tmp",
}).encode()
FIXTURE = '''import json, os, pathlib, sys, time
if sys.argv[1:3] == ["rule", "verify"]:
    time.sleep(float(os.environ.get("FIXTURE_DELAY", "0")))
    if pathlib.Path("invalid-policy").exists():
        raise SystemExit(1)
    raise SystemExit(int(os.environ.get("FIXTURE_VERIFY_EXIT", "0")))
pathlib.Path(os.environ["FIXTURE_MARKER"]).write_bytes(sys.stdin.buffer.read())
print(os.environ.get("FIXTURE_OUTPUT", ""), end="")
raise SystemExit(int(os.environ.get("FIXTURE_HOOK_EXIT", "0")))
'''


class SafetyNetHookTests(unittest.TestCase):
    def setUp(self):
        if not ADAPTER.is_file():
            self.fail("Safety Net adapter is not implemented")
        spec = importlib.util.spec_from_file_location("safety_net", ADAPTER)
        self.adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.adapter)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fixture = self.root / "native.py"
        self.fixture.write_text(FIXTURE)
        self.marker = self.root / "called"
        self.command = [sys.executable, str(self.fixture)]
        self.env = patch.dict(os.environ, {"FIXTURE_MARKER": str(self.marker)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def assertDenied(self, result):
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_valid_policy_passes_original_input_to_native_hook(self):
        self.assertIsNone(self.adapter.check(PAYLOAD, self.command))
        self.assertEqual(self.marker.read_bytes(), PAYLOAD)

    def test_invalid_policy_blocks_before_native_hook(self):
        with patch.dict(os.environ, {"FIXTURE_VERIFY_EXIT": "1"}):
            self.assertDenied(self.adapter.check(PAYLOAD, self.command))
        self.assertFalse(self.marker.exists())

    def test_native_deny_is_preserved(self):
        deny = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "fixture"}}
        with patch.dict(os.environ, {"FIXTURE_OUTPUT": json.dumps(deny)}):
            self.assertEqual(self.adapter.check(PAYLOAD, self.command), deny)

    def test_native_crash_blocks(self):
        with patch.dict(os.environ, {"FIXTURE_HOOK_EXIT": "1"}):
            self.assertDenied(self.adapter.check(PAYLOAD, self.command))

    def test_verification_uses_payload_project_directory(self):
        (self.root / "invalid-policy").touch()
        payload = json.loads(PAYLOAD)
        payload["cwd"] = str(self.root)
        self.assertDenied(self.adapter.check(json.dumps(payload).encode(), self.command))
        self.assertFalse(self.marker.exists())

    def test_invalid_decision_type_returns_deny(self):
        for decision in [[], {}]:
            output = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision}}
            with self.subTest(decision=decision), patch.dict(os.environ, {"FIXTURE_OUTPUT": json.dumps(output)}):
                self.assertDenied(self.adapter.check(PAYLOAD, self.command))

    def test_malformed_native_output_blocks(self):
        for output in ["{", "[]", '"not an object"']:
            with self.subTest(output=output), patch.dict(os.environ, {"FIXTURE_OUTPUT": output}):
                self.assertDenied(self.adapter.check(PAYLOAD, self.command))

    def test_deadline_blocks(self):
        with patch.dict(os.environ, {"FIXTURE_DELAY": "2"}):
            self.assertDenied(self.adapter.check(PAYLOAD, self.command, timeout=0.05))
        self.assertFalse(self.marker.exists())

    def test_missing_native_binary_blocks(self):
        self.assertDenied(self.adapter.check(PAYLOAD, [str(self.root / "missing")]))

    def test_invalid_input_never_reaches_native_hook(self):
        for payload in [b"{", b"[]", b"{}"]:
            with self.subTest(payload=payload):
                self.assertDenied(self.adapter.check(payload, self.command))
        self.assertFalse(self.marker.exists())

    def test_cli_emits_native_deny_json_with_zero_exit(self):
        result = subprocess.run([sys.executable, str(ADAPTER), *self.command],
                                input=b"{", capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertDenied(json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
