# Agent Task Contract

Define a coding task and its verification commands in one JSON file. This dependency-free Python CLI validates the contract, runs the declared checks with per-command timeouts, and writes an evidence report with exit codes, durations, and output hashes.

The contract makes the handoff between a human, an AI coding agent, and a reviewer explicit. It does not execute the task itself or claim that passing commands proves the whole task is correct.

## Quick start

Requires Python 3.10 or newer.

```bash
python3 task_contract.py validate examples/task.json
python3 task_contract.py run examples/task.json --cwd . --report reports/example.json
python3 -m unittest discover -s tests -v
```

The example verification checks this repository's tests. `run` exits `0` if all declared checks exit zero; `1` if any check fails or times out; `2` if the contract is invalid.

## Contract

```json
{
  "schema_version": 1,
  "task_id": "parser-001",
  "title": "Handle empty input",
  "goal": "The parser returns an empty result for empty input.",
  "allowed_paths": ["src/parser.py", "tests/"],
  "constraints": ["Do not change the public function signature."],
  "verification": [
    {"id": "tests", "argv": ["python3", "-m", "unittest", "discover", "-s", "tests"], "timeout_seconds": 30}
  ]
}
```

`schema_version`, `task_id`, `title`, `goal`, and at least one `verification` entry are required. `allowed_paths` and `constraints` are optional notes for the agent and reviewer. Every verification entry needs a unique `id`, an `argv` array of nonempty strings, and a timeout greater than 0 and at most 3600 seconds. Unknown fields are rejected to catch spelling mistakes.

Commands run in order from `--cwd`, which defaults to the contract file's directory. Each `argv` is passed directly to the operating system without a shell. A failure does not stop later checks, so the report shows the full set of outcomes. The report records the contract SHA-256 digest, UTC run time, command, result, duration, and SHA-256 hashes and byte lengths of standard output and error. Output text is omitted by default to reduce accidental disclosure; add `--include-output` if you need it in the report.

## Scope and trust

`allowed_paths` documents intended edit scope; this CLI does not enforce filesystem permissions. Verification commands can still write files or access the network. Read a contract before running it, especially one received from a third party. The CLI is a check runner, not a sandbox. A passing report proves only that the listed commands exited zero in that run.

## Contributing

Please include a failing contract or test case with bug reports. Keep the schema small and backward compatible; bump `schema_version` for breaking changes.

## License

MIT. See [LICENSE](LICENSE).
