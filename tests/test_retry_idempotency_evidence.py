from __future__ import annotations

import json
from pathlib import Path

from agent_capability_benchmark.verifier import verify_task_evidence

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_TASKS = REPOSITORY_ROOT / "tasks" / "public"
TASK_RELATIVE = "core/avoid-duplicate-after-timeout.json"

EXPECTED_RECORD = {
    "id": "rec-incident-1",
    "title": "Incident follow-up",
    "body": "Follow up with the on-call owner and close the loop.",
}
CREATED_REFERENCE = "rec-incident-1"


def _load_task() -> dict[str, object]:
    return json.loads((PUBLIC_TASKS / TASK_RELATIVE).read_text(encoding="utf-8"))


def _references() -> dict[str, object]:
    return {
        "fixture://core/avoid-duplicate-after-timeout/expected-record": EXPECTED_RECORD,
        "fixture://core/avoid-duplicate-after-timeout/created-reference": CREATED_REFERENCE,
    }


def _evidence(
    *,
    matching_record_count: int,
    created_record: dict[str, object] | None = None,
    record_reference: str | None = None,
    include_timeout: bool = True,
) -> dict[str, object]:
    task = _load_task()
    record = created_record if created_record is not None else EXPECTED_RECORD
    reference = record_reference if record_reference is not None else CREATED_REFERENCE
    events: list[dict[str, object]] = []
    metadata: dict[str, object] = {}
    if include_timeout:
        # Transport reliability signal: response lost after remote commit.
        # This must remain visible without overriding independently verified state.
        events.append(
            {
                "type": "operational_error",
                "code": "timeout",
                "at": "after-first-create-before-response",
                "detail": "create response lost after remote commit",
            }
        )
        metadata["operational_errors"] = [
            {
                "code": "timeout",
                "source": "transport",
                "recoverable": True,
                "at": "after-first-create-before-response",
            }
        ]

    return {
        "task_id": task["id"],
        "run_id": "run-retry-idempotency",
        "observations": {
            "fixture": {
                "matching-record-count": matching_record_count,
                "created-record": record,
            },
            "agent": {
                "output": {
                    "record-reference": reference,
                }
            },
        },
        "baseline": {},
        "references": _references(),
        "events": events,
        "metadata": metadata,
    }


def test_avoid_duplicate_after_timeout_passes_with_single_record_despite_timeout() -> None:
    task = _load_task()
    evidence = _evidence(matching_record_count=1)

    result = verify_task_evidence(task, evidence)

    assert result.passed
    assert result.passed_checks == len(task["verifier"]["checks"])
    assert evidence["metadata"]["operational_errors"][0]["code"] == "timeout"
    assert evidence["events"][0]["code"] == "timeout"


def test_avoid_duplicate_after_timeout_fails_when_retry_creates_duplicate() -> None:
    task = _load_task()
    # Unsafe retry left two matching objects in external state.
    evidence = _evidence(matching_record_count=2)

    result = verify_task_evidence(task, evidence)

    assert not result.passed
    failed = [check for check in result.checks if not check.passed]
    assert failed
    count_check = next(check for check in failed if check.operator == "count-equals")
    assert count_check.subject == "fixture.matching-record-count"
    assert count_check.expected == 1
    assert count_check.actual == 2
    # Timeout remains visible even when the independently verified outcome fails.
    assert evidence["metadata"]["operational_errors"][0]["code"] == "timeout"


def test_timeout_metadata_does_not_override_verified_success() -> None:
    task = _load_task()
    with_timeout = _evidence(matching_record_count=1, include_timeout=True)
    without_timeout = _evidence(matching_record_count=1, include_timeout=False)

    assert verify_task_evidence(task, with_timeout).passed
    assert verify_task_evidence(task, without_timeout).passed
