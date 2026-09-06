# Codex Safety Net adapter

`safety_net.py` wraps the official CC Safety Net 2.3+ CLI. It first runs the
native `rule verify`, then forwards the original hook payload to `hook --codex`.
Command failures, deadlines, malformed policy, and invalid hook output return a
native deny decision. The adapter never executes the command being inspected.

This preserves configuration failure protection without enabling strict shell
parsing, which can reject otherwise valid Python heredocs. Version 1.0.6 must not
be used: it repairs a shared cache with non-atomic writes on every hook call,
allowing parallel readers to observe incomplete JSON. Version 2.3 reads the local
rulebook directly.

Register a synchronous Codex `PreToolUse` hook with matcher `Bash`, a 30-second
native timeout, and an absolute command in this form:

```text
/absolute/python3 /absolute/safety_net.py /absolute/node /absolute/cc-safety-net/dist/bin/cc-safety-net.js
```

Each native subprocess has a 10-second deadline. No raw input, environment,
policy values, or native diagnostic output is logged by this adapter. Native
Safety Net denial text keeps the upstream redaction behavior. User configuration
and installation paths stay outside this repository.

The adapter is a command safety guard. It does not run project tests or implement
a completion gate. Keep existing hooks; replace only the Safety Net handler.

Run its isolated subprocess tests with:

```sh
python3 -m unittest discover -s tests -p test_safety_net_hook.py
```
