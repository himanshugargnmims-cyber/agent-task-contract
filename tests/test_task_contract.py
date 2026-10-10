import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from task_contract import ContractError, load_contract, main, run_contract, validate_contract


def sample_contract(*checks: dict) -> dict:
    return {
        "schema_version": 1,
        "task_id": "demo",
        "title": "Run checks",
        "goal": "Prove command outcomes are recorded.",
        "verification": list(checks),
    }


class TaskContractTests(unittest.TestCase):
    def test_validation_accepts_well_formed_contract(self) -> None:
        contract = sample_contract({"id": "ok", "argv": [sys.executable, "-c", "print('ok')"], "timeout_seconds": 2})
        self.assertIs(validate_contract(contract), contract)

    def test_validation_rejects_unknown_field_and_duplicate_ids(self) -> None:
        check = {"id": "same", "argv": ["echo", "ok"], "timeout_seconds": 2}
        with self.assertRaisesRegex(ContractError, "duplicate verification id"):
            validate_contract(sample_contract(check, check))
        with self.assertRaisesRegex(ContractError, "unknown field"):
            validate_contract({**sample_contract(check), "surprise": True})

    def test_validation_rejects_shell_string(self) -> None:
        with self.assertRaisesRegex(ContractError, "array"):
            validate_contract(sample_contract({"id": "bad", "argv": "echo ok", "timeout_seconds": 2}))

    def test_report_records_success_failure_and_output_hash(self) -> None:
        contract = sample_contract(
            {"id": "pass", "argv": [sys.executable, "-c", "print('ok')"], "timeout_seconds": 2},
            {"id": "fail", "argv": [sys.executable, "-c", "import sys; sys.exit(7)"], "timeout_seconds": 2},
        )
        raw = json.dumps(contract).encode()
        report = run_contract(contract, raw, Path.cwd())
        self.assertEqual(report["summary"], {"total": 2, "passed": 1, "failed": 1})
        self.assertEqual(report["contract_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(report["verification"][0]["stdout_sha256"], hashlib.sha256(b"ok\n").hexdigest())
        self.assertEqual(report["verification"][1]["exit_code"], 7)
        self.assertNotIn("stdout", report["verification"][0])

    def test_timeout_is_a_failure(self) -> None:
        contract = sample_contract({"id": "slow", "argv": [sys.executable, "-c", "import time; time.sleep(1)"], "timeout_seconds": 0.05})
        report = run_contract(contract, json.dumps(contract).encode(), Path.cwd())
        self.assertEqual(report["verification"][0]["status"], "timeout")

    def test_cli_writes_report_with_optional_output(self) -> None:
        contract = sample_contract({"id": "ok", "argv": [sys.executable, "-c", "print('hello')"], "timeout_seconds": 2})
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "task.json"
            target = Path(directory) / "report.json"
            source.write_text(json.dumps(contract), encoding="utf-8")
            self.assertEqual(main(["validate", str(source)]), 0)
            self.assertEqual(main(["run", str(source), "--cwd", directory, "--report", str(target), "--include-output"]), 0)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["verification"][0]["stdout"], "hello\n")
            loaded, _ = load_contract(source)
            self.assertEqual(loaded["task_id"], "demo")


if __name__ == "__main__":
    unittest.main()
