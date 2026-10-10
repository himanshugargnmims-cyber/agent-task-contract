"""Validate a JSON task contract and run its declared verification commands."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    """Raised when a contract is invalid."""


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a nonempty string")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ContractError(f"{label} must be an array of nonempty strings")
    return value


def validate_contract(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ContractError("contract must be a JSON object")
    allowed = {"schema_version", "task_id", "title", "goal", "allowed_paths", "constraints", "verification"}
    unknown = set(data) - allowed
    if unknown:
        raise ContractError(f"unknown field(s): {', '.join(sorted(unknown))}")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ContractError("schema_version must be 1")
    for key in ("task_id", "title", "goal"):
        _nonempty_string(data.get(key), key)
    _string_list(data.get("allowed_paths", []), "allowed_paths")
    _string_list(data.get("constraints", []), "constraints")
    checks = data.get("verification")
    if not isinstance(checks, list) or not checks:
        raise ContractError("verification must be a nonempty array")
    seen: set[str] = set()
    for index, check in enumerate(checks):
        label = f"verification[{index}]"
        if not isinstance(check, dict):
            raise ContractError(f"{label} must be an object")
        extra = set(check) - {"id", "argv", "timeout_seconds"}
        if extra:
            raise ContractError(f"{label} has unknown field(s): {', '.join(sorted(extra))}")
        check_id = _nonempty_string(check.get("id"), f"{label}.id")
        if check_id in seen:
            raise ContractError(f"duplicate verification id: {check_id}")
        seen.add(check_id)
        if not _string_list(check.get("argv"), f"{label}.argv"):
            raise ContractError(f"{label}.argv cannot be empty")
        timeout = check.get("timeout_seconds")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise ContractError(f"{label}.timeout_seconds must be greater than 0 and at most 3600")
    return data


def load_contract(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read contract {path}: {exc}") from exc
    return validate_contract(data), raw


def _bytes(value: bytes | str | None) -> bytes:
    if value is None:
        return b""
    return value.encode("utf-8", errors="replace") if isinstance(value, str) else value


def _output_metadata(output: bytes, name: str, include_output: bool) -> dict[str, Any]:
    details: dict[str, Any] = {
        f"{name}_bytes": len(output),
        f"{name}_sha256": hashlib.sha256(output).hexdigest(),
    }
    if include_output:
        details[name] = output.decode("utf-8", errors="replace")
    return details


def run_contract(
    contract: dict[str, Any],
    raw: bytes,
    cwd: Path,
    include_output: bool = False,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for check in contract["verification"]:
        started = time.monotonic()
        stdout = b""
        stderr = b""
        exit_code: int | None = None
        try:
            process = subprocess.run(
                check["argv"],
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=check["timeout_seconds"],
                check=False,
            )
            stdout, stderr = process.stdout, process.stderr
            exit_code = process.returncode
            status = "passed" if exit_code == 0 else "failed"
        except subprocess.TimeoutExpired as exc:
            stdout, stderr = _bytes(exc.stdout), _bytes(exc.stderr)
            status = "timeout"
        except OSError as exc:
            stderr = str(exc).encode("utf-8", errors="replace")
            status = "spawn_error"
        result: dict[str, Any] = {
            "id": check["id"],
            "argv": check["argv"],
            "timeout_seconds": check["timeout_seconds"],
            "status": status,
            "exit_code": exit_code,
            "duration_seconds": round(time.monotonic() - started, 3),
        }
        result.update(_output_metadata(stdout, "stdout", include_output))
        result.update(_output_metadata(stderr, "stderr", include_output))
        results.append(result)
    passed = sum(item["status"] == "passed" for item in results)
    return {
        "report_schema_version": 1,
        "task_id": contract["task_id"],
        "contract_sha256": hashlib.sha256(raw).hexdigest(),
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "cwd": str(cwd.resolve()),
        "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed},
        "verification": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate", help="validate a contract without running commands")
    validate_parser.add_argument("contract", type=Path)
    run_parser = subparsers.add_parser("run", help="run the verification commands")
    run_parser.add_argument("contract", type=Path)
    run_parser.add_argument("--cwd", type=Path, help="command working directory (default: contract directory)")
    run_parser.add_argument("--report", type=Path, help="JSON report path")
    run_parser.add_argument("--include-output", action="store_true", help="include command output in report")
    args = parser.parse_args(argv)
    try:
        contract, raw = load_contract(args.contract)
    except ContractError as exc:
        print(f"Contract error: {exc}", file=sys.stderr)
        return 2
    if args.command == "validate":
        print(f"Valid contract: {contract['task_id']} ({len(contract['verification'])} checks)")
        return 0
    cwd = args.cwd or args.contract.resolve().parent
    if not cwd.is_dir():
        print(f"Working directory is not a directory: {cwd}", file=sys.stderr)
        return 2
    report = run_contract(contract, raw, cwd, include_output=args.include_output)
    for item in report["verification"]:
        print(f"{item['id']}: {item['status']} ({item['duration_seconds']}s)")
    summary = report["summary"]
    print(f"Passed {summary['passed']}/{summary['total']} checks")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Report: {args.report}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

