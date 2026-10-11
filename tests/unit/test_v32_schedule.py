from __future__ import annotations

import copy
import json
from collections import defaultdict

import pytest

from tscompbench.execution.schedule import (
    FrozenSchedule,
    ScheduleError,
    append_trial_event,
    build_schedule,
    pending_trials,
    read_trial_events,
    write_frozen_schedule,
)
from tscompbench.ids import canonical_json_bytes


def schedule(seed=101, **kwargs):
    return build_schedule(
        run_set_id="run",
        protocol_id="protocol",
        seed=seed,
        blocks=4,
        rounds_per_block=2,
        dataset_methods={
            "source-a": {
                "method-a-parameter-1": "job-a-1",
                "method-a-parameter-2": "job-a-2",
                "method-b": "job-b",
            },
            "source-b": {"method-a": "job-a-source-b", "method-b": "job-b-source-b"},
        },
        **kwargs,
    )


def test_schedule_is_reproducible_randomized_interleaving_preserving_all_variants():
    frozen = schedule()
    assert frozen.to_document() == schedule().to_document()
    assert FrozenSchedule.from_document(frozen.to_document()) == frozen
    assert canonical_json_bytes(frozen.to_document())
    assert [t.method_id for t in frozen.trials] != [t.method_id for t in schedule(202).trials]
    pairs = defaultdict(list)
    for trial in frozen.trials:
        pairs[trial.pair_id].append(trial)
    assert len(pairs) == 16
    for pair in pairs.values():
        assert len({t.job_id for t in pair}) == (3 if pair[0].dataset_id == "source-a" else 2)
        assert len({t.repetition_index for t in pair}) == 1
        assert sorted(t.sequence_index for t in pair) == list(
            range(pair[0].sequence_index, pair[0].sequence_index + len(pair))
        )
    a_orders = [
        tuple(t.method_id for t in pair)
        for pair in pairs.values()
        if pair[0].dataset_id == "source-a"
    ]
    assert len(set(a_orders)) > 1
    assert len({t.trial_id for t in frozen.trials}) == 40


def test_schedule_cannot_change_on_resume(tmp_path):
    frozen = schedule()
    path = tmp_path / "schedule.json"
    write_frozen_schedule(path, frozen)
    write_frozen_schedule(path, schedule())
    with pytest.raises(ScheduleError):
        write_frozen_schedule(path, schedule(202))
    for key, value in (("seed", 202), ("schedule_id", "forged"), ("randomization", "sorted")):
        document = frozen.to_document() | {key: value}
        with pytest.raises(ScheduleError):
            FrozenSchedule.from_document(document)
    document = copy.deepcopy(frozen.to_document())
    document["trials"].reverse()
    with pytest.raises(ScheduleError):
        FrozenSchedule.from_document(document)


def test_failure_retry_and_missing_slots_preserve_denominator(tmp_path):
    frozen = schedule(max_retries=1)
    journal = tmp_path / "actual.jsonl"
    first, second, *_ = frozen.trials
    event = append_trial_event(
        journal, frozen, trial_id=first.trial_id, status="TIMEOUT", started_ns=10, finished_ns=20
    )
    assert event["event_index"] == 0
    events = read_trial_events(journal, frozen)
    assert pending_trials(frozen, events) == frozen.trials
    retried = append_trial_event(
        journal,
        frozen,
        trial_id=first.trial_id,
        status="CORRECTNESS_FAIL",
        started_ns=30,
        finished_ns=40,
        attempt_index=1,
    )
    assert retried["attempt_id"] != event["attempt_id"]
    append_trial_event(
        journal,
        frozen,
        trial_id=second.trial_id,
        status="PASS",
        started_ns=50,
        finished_ns=60,
        observation_ref="raw-2",
    )
    events = read_trial_events(journal, frozen)
    assert len(events) == 3
    assert len(frozen.trials) == 40
    assert pending_trials(frozen, events) == frozen.trials[2:]
    for trial_id, attempt in ((first.trial_id, 2), (second.trial_id, 1)):
        with pytest.raises(ScheduleError):
            append_trial_event(
                journal,
                frozen,
                trial_id=trial_id,
                status="PASS",
                started_ns=70,
                finished_ns=80,
                attempt_index=attempt,
            )


def test_actual_journal_cannot_forge_or_reorder_attempts(tmp_path):
    frozen = schedule()
    journal = tmp_path / "actual.jsonl"
    event = append_trial_event(
        journal,
        frozen,
        trial_id=frozen.trials[0].trial_id,
        status="PASS",
        started_ns=10,
        finished_ns=20,
    )
    for mutation in (
        {"event_index": 1},
        {"pair_id": "forged"},
        {"attempt_index": True},
        {"status": "PLANNED"},
        {"status": {}},
        {"trial_id": []},
        {"started_ns": 21},
    ):
        forged = event | mutation
        journal.write_text(json.dumps(forged) + "\n")
        with pytest.raises(ScheduleError):
            read_trial_events(journal, frozen)
    journal.write_text(json.dumps(event) + "\n" + json.dumps(event) + "\n")
    with pytest.raises(ScheduleError):
        read_trial_events(journal, frozen)
    journal.write_text('{"unfinished":')
    with pytest.raises(ScheduleError):
        read_trial_events(journal, frozen)


@pytest.mark.parametrize(
    "methods",
    [
        {},
        {"d": {}},
        {"d": {"a": "same-job", "b": "same-job"}},
        {"d": {"a": ""}},
        {None: {"a": "j"}, "d": {"a": "j2"}},
    ],
)
def test_invalid_coverage_and_job_aliases_are_rejected(methods):
    with pytest.raises(ScheduleError):
        build_schedule(run_set_id="r", protocol_id="p", seed=0, dataset_methods=methods)


def test_schedule_rejects_unbounded_and_boolean_budgets():
    for kwargs in (
        {"blocks": 0},
        {"seed": True},
        {"max_retries": 11},
        {"rounds_per_block": 1_000_001},
    ):
        with pytest.raises(ScheduleError):
            build_schedule(
                **(
                    {
                        "run_set_id": "r",
                        "protocol_id": "p",
                        "seed": 0,
                        "dataset_methods": {"d": {"m": "j"}},
                    }
                    | kwargs
                )
            )
