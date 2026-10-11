"""Frozen randomized blocks and append-only actual trial events for V3.2."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tscompbench.contracts import RunStatus
from tscompbench.ids import canonical_json_bytes, stable_id


class ScheduleError(ValueError):
    pass


@dataclass(frozen=True)
class ScheduleTrial:
    trial_id: str
    pair_id: str
    dataset_id: str
    method_id: str
    execution_job_id: str
    block_index: int
    round_index: int
    repetition_index: int
    sequence_index: int

    @property
    def job_id(self) -> str:
        return self.execution_job_id

    def to_document(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FrozenSchedule:
    run_set_id: str
    protocol_id: str
    seed: int
    blocks: int
    rounds_per_block: int
    max_retries: int
    dataset_methods: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    trials: tuple[ScheduleTrial, ...]

    @property
    def schedule_id(self) -> str:
        return stable_id("schedule-v32", self._identity())

    def _identity(self) -> dict[str, Any]:
        return {
            "schema_version": "tscb.schedule.v3.2",
            "run_set_id": self.run_set_id,
            "protocol_id": self.protocol_id,
            "seed": self.seed,
            "blocks": self.blocks,
            "rounds_per_block": self.rounds_per_block,
            "max_retries": self.max_retries,
            "randomization": "SHA256_KEYED_ORDER_V1",
            "dataset_methods": {
                dataset: dict(methods) for dataset, methods in self.dataset_methods
            },
            "trials": [trial.to_document() for trial in self.trials],
        }

    def to_document(self) -> dict[str, Any]:
        return {**self._identity(), "schedule_id": self.schedule_id}

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> FrozenSchedule:
        expected = {
            "schema_version",
            "run_set_id",
            "protocol_id",
            "seed",
            "blocks",
            "rounds_per_block",
            "max_retries",
            "randomization",
            "dataset_methods",
            "trials",
            "schedule_id",
        }
        if (
            not isinstance(document, Mapping)
            or set(document) != expected
            or document["schema_version"] != "tscb.schedule.v3.2"
        ):
            raise ScheduleError("invalid schedule schema/version/fields")
        schedule = build_schedule(
            run_set_id=document["run_set_id"],
            dataset_methods=document["dataset_methods"],
            protocol_id=document["protocol_id"],
            seed=document["seed"],
            blocks=document["blocks"],
            rounds_per_block=document["rounds_per_block"],
            max_retries=document["max_retries"],
        )
        if canonical_json_bytes(schedule.to_document()) != canonical_json_bytes(document):
            raise ScheduleError("schedule changed from its frozen seed, design or trial identities")
        return schedule


def build_schedule(
    *,
    run_set_id: str,
    dataset_methods: Mapping[str, Mapping[str, str]],
    protocol_id: str,
    seed: int,
    blocks: int = 1,
    rounds_per_block: int = 1,
    max_retries: int = 0,
) -> FrozenSchedule:
    if (
        not isinstance(run_set_id, str)
        or not run_set_id
        or not isinstance(protocol_id, str)
        or not protocol_id
    ):
        raise ScheduleError("run_set_id and protocol_id must be non-empty")
    for name, value, minimum in (
        ("seed", seed, 0),
        ("blocks", blocks, 1),
        ("rounds_per_block", rounds_per_block, 1),
        ("max_retries", max_retries, 0),
    ):
        if type(value) is not int or not minimum <= value <= 2**63 - 1:
            raise ScheduleError(f"{name} must be a finite integer >= {minimum}")
    if max_retries > 10 or blocks * rounds_per_block > 1_000_000:
        raise ScheduleError("schedule budget exceeds the finite supported bound")
    if not isinstance(dataset_methods, Mapping) or not dataset_methods:
        raise ScheduleError("schedule requires frozen dataset/method coverage")
    if any(not isinstance(dataset, str) or not dataset for dataset in dataset_methods):
        raise ScheduleError("dataset identities must be non-empty strings")
    normalized = []
    for dataset, methods in sorted(dataset_methods.items()):
        if (
            not isinstance(dataset, str)
            or not dataset
            or not isinstance(methods, Mapping)
            or not methods
        ):
            raise ScheduleError("each dataset requires non-empty method/job identities")
        if any(
            not isinstance(value, str) or not value for item in methods.items() for value in item
        ):
            raise ScheduleError("method and execution job identities must be non-empty strings")
        if len(set(methods.values())) != len(methods):
            raise ScheduleError("aliases of the same execution job cannot add schedule members")
        normalized.append((dataset, tuple(sorted(methods.items()))))
    if sum(len(methods) for _, methods in normalized) * blocks * rounds_per_block > 1_000_000:
        raise ScheduleError("schedule would exceed one million planned trials")
    design = {
        "run_set_id": run_set_id,
        "protocol_id": protocol_id,
        "seed": seed,
        "blocks": blocks,
        "rounds_per_block": rounds_per_block,
        "max_retries": max_retries,
        "dataset_methods": normalized,
    }
    design_id = stable_id("schedule-design-v32", design)
    trials = []
    for block in range(blocks):
        for round_index in range(rounds_per_block):
            for dataset, methods in normalized:
                pair_id = stable_id(
                    "schedule-pair-v32",
                    {
                        "design_id": design_id,
                        "dataset_id": dataset,
                        "block_index": block,
                        "round_index": round_index,
                    },
                )
                ordered = sorted(
                    methods,
                    key=lambda item: (
                        hashlib.sha256(
                            canonical_json_bytes(
                                {
                                    "seed": seed,
                                    "pair_id": pair_id,
                                    "method_id": item[0],
                                }
                            )
                        ).digest(),
                        item[0],
                    ),
                )
                for method, job in ordered:
                    trial_id = stable_id(
                        "scheduled-trial-v32",
                        {
                            "pair_id": pair_id,
                            "method_id": method,
                            "execution_job_id": job,
                        },
                    )
                    trials.append(
                        ScheduleTrial(
                            trial_id,
                            pair_id,
                            dataset,
                            method,
                            job,
                            block,
                            round_index,
                            block * rounds_per_block + round_index,
                            len(trials),
                        )
                    )
    return FrozenSchedule(
        run_set_id,
        protocol_id,
        seed,
        blocks,
        rounds_per_block,
        max_retries,
        tuple(normalized),
        tuple(trials),
    )


def write_frozen_schedule(path: Path, schedule: FrozenSchedule) -> None:
    payload = canonical_json_bytes(schedule.to_document()) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ScheduleError("existing frozen schedule differs; create a new RunSet") from None
        return
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _validated_events(
    events: Sequence[Mapping[str, Any]],
    schedule: FrozenSchedule,
) -> tuple[dict[str, Any], ...]:
    planned = {trial.trial_id: trial for trial in schedule.trials}
    attempts: dict[str, list[dict[str, Any]]] = {}
    terminal_statuses = {status.value for status in RunStatus if status != RunStatus.PLANNED}
    terminal_statuses.add("INCONCLUSIVE")
    expected_fields = {
        "schema_version",
        "schedule_id",
        "attempt_index",
        "attempt_id",
        "status",
        "started_ns",
        "finished_ns",
        "observation_ref",
        "recorded_ns",
        "event_index",
        *ScheduleTrial.__dataclass_fields__,
    }
    checked = []
    for event_index, event in enumerate(events):
        if not isinstance(event, Mapping) or set(event) != expected_fields:
            raise ScheduleError("actual trial event fields do not match the strict schema")
        if not isinstance(event.get("trial_id"), str):
            raise ScheduleError("actual trial identity must be a string")
        trial = planned.get(event["trial_id"])
        if (
            trial is None
            or event["schema_version"] != "tscb.actual-trial.v3.2"
            or event["schedule_id"] != schedule.schedule_id
            or any(event[key] != value for key, value in trial.to_document().items())
        ):
            raise ScheduleError("actual trial event does not belong to the frozen schedule")
        for key in (
            "attempt_index",
            "event_index",
            "started_ns",
            "finished_ns",
            "recorded_ns",
            "block_index",
            "round_index",
            "repetition_index",
            "sequence_index",
        ):
            if type(event[key]) is not int or not 0 <= event[key] <= 2**63 - 1:
                raise ScheduleError("event indices and times must be finite non-negative integers")
        own = attempts.setdefault(trial.trial_id, [])
        if (
            event["event_index"] != event_index
            or event["attempt_index"] != len(own)
            or event["attempt_index"] > schedule.max_retries
            or any(prior["status"] == "PASS" for prior in own)
            or event["attempt_id"]
            != stable_id(
                "trial-attempt-v32",
                {
                    "trial_id": trial.trial_id,
                    "attempt_index": event["attempt_index"],
                },
            )
        ):
            raise ScheduleError("event order, retry budget or attempt identity was changed")
        if (
            not isinstance(event["status"], str)
            or event["status"] not in terminal_statuses
            or event["finished_ns"] < event["started_ns"]
            or (
                event["observation_ref"] is not None
                and (not isinstance(event["observation_ref"], str) or not event["observation_ref"])
            )
        ):
            raise ScheduleError("actual event requires valid terminal outcome and boundaries")
        own.append(dict(event))
        checked.append(dict(event))
    return tuple(checked)


def _parse_event_lines(content: bytes) -> list[dict[str, Any]]:
    try:
        return [json.loads(line) for line in content.splitlines()]
    except ValueError as error:
        raise ScheduleError("actual trial journal contains malformed JSON") from error


def read_trial_events(path: Path, schedule: FrozenSchedule) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        return ()
    with path.open("rb") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        return _validated_events(_parse_event_lines(handle.read()), schedule)


def append_trial_event(
    path: Path,
    schedule: FrozenSchedule,
    *,
    trial_id: str,
    status: str,
    started_ns: int,
    finished_ns: int,
    observation_ref: str | None = None,
    attempt_index: int = 0,
) -> dict[str, Any]:
    planned = {trial.trial_id: trial for trial in schedule.trials}
    if trial_id not in planned or not isinstance(status, str) or not status:
        raise ScheduleError("actual event requires a planned trial and terminal status")
    if type(attempt_index) is not int or not 0 <= attempt_index <= schedule.max_retries:
        raise ScheduleError("retry exceeds frozen budget")
    if (
        any(type(value) is not int or value < 0 for value in (started_ns, finished_ns))
        or finished_ns < started_ns
    ):
        raise ScheduleError("actual trial time boundaries are invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        prior = _validated_events(_parse_event_lines(handle.read()), schedule)
        own = [event for event in prior if event.get("trial_id") == trial_id]
        if attempt_index != len(own) or any(event["status"] == "PASS" for event in own):
            raise ScheduleError("cannot replace terminal attempts or retry a successful trial")
        event = {
            "schema_version": "tscb.actual-trial.v3.2",
            "schedule_id": schedule.schedule_id,
            **planned[trial_id].to_document(),
            "attempt_index": attempt_index,
            "attempt_id": stable_id(
                "trial-attempt-v32", {"trial_id": trial_id, "attempt_index": attempt_index}
            ),
            "status": status,
            "started_ns": started_ns,
            "finished_ns": finished_ns,
            "observation_ref": observation_ref,
            "recorded_ns": time.time_ns(),
            "event_index": len(prior),
        }
        _validated_events([*prior, event], schedule)
        handle.seek(0, os.SEEK_END)
        handle.write(canonical_json_bytes(event) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    return event


def pending_trials(
    schedule: FrozenSchedule, events: Sequence[Mapping[str, Any]]
) -> tuple[ScheduleTrial, ...]:
    completed = set()
    for event in _validated_events(events, schedule):
        # Failures are terminal at the configured attempt budget; they stay in the
        # full schedule/denominator while genuinely missing slots remain pending.
        if event["status"] == "PASS" or event["attempt_index"] >= schedule.max_retries:
            completed.add(event["trial_id"])
    return tuple(trial for trial in schedule.trials if trial.trial_id not in completed)
