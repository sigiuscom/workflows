#!/usr/bin/env python3
"""Validate Safety Net policy before its native Codex hook (CC Safety Net 2.3+)."""
import json
import os
import subprocess
import sys


def deny(reason):
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}


def check(payload, command, timeout=10):
    try:
        data = json.loads(payload)
        if (not isinstance(data, dict)
                or data.get("hook_event_name") != "PreToolUse"
                or not isinstance(data.get("tool_name"), str)
                or not isinstance(data.get("tool_input"), dict)):
            return deny("Safety Net received invalid hook input.")
        if data["tool_name"] == "Bash" and not isinstance(data["tool_input"].get("command"), str):
            return deny("Safety Net received invalid Bash input.")
        cwd = data.get("cwd")
        if not isinstance(cwd, str) or not os.path.isabs(cwd):
            return deny("Safety Net received an invalid project directory.")
        if not command:
            return deny("Safety Net executable is not configured.")
        verified = subprocess.run([*command, "rule", "verify"],
                                  capture_output=True, timeout=timeout, cwd=cwd)
        if verified.returncode:
            return deny("Safety Net rule configuration is invalid. Run its rule verify command and repair the reported configuration; protection remains enabled.")
        result = subprocess.run([*command, "hook", "--codex"], input=payload,
                                capture_output=True, timeout=timeout, cwd=cwd)
        if result.returncode:
            return deny("Safety Net could not complete command analysis. Check its installation before retrying.")
        if not result.stdout.strip():
            return None
        output = json.loads(result.stdout)
        if not isinstance(output, dict):
            return deny("Safety Net returned invalid hook output.")
        native = output.get("hookSpecificOutput")
        if (not isinstance(native, dict)
                or native.get("hookEventName") != "PreToolUse"
                or native.get("permissionDecision") not in ("allow", "deny", "ask")):
            return deny("Safety Net returned an unrecognized decision.")
        return output
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return deny("Safety Net validation failed or timed out. Check its installation and policy; protection remains enabled.")


def main():
    payload = sys.stdin.buffer.read(1024 * 1024 + 1)
    result = (deny("Safety Net hook input exceeds its size limit.")
              if len(payload) > 1024 * 1024 else check(payload, sys.argv[1:]))
    if result is not None:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
