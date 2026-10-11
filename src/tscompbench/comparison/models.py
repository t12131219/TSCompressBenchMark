from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import ClassVar

import numpy as np

from tscompbench.ids import canonical_json_bytes, stable_id

from .schema import SCHEMAS, ComparisonSpecError, validate_schema


def finite_decimal(value: str, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError) as error:
        raise ComparisonSpecError("invalid decimal string") from error
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ComparisonSpecError("decimal must be finite and nonnegative/positive")
    return result


def _unique(rows: list[dict], key: str) -> None:
    values = [row[key] for row in rows]
    if len(values) != len(set(values)):
        raise ComparisonSpecError(f"duplicate {key}")


def _fidelity(fidelity: dict) -> None:
    kind = fidelity["kind"]
    if kind == "FIXED_ERROR":
        if not fidelity["error_metric"] or not isinstance(fidelity["threshold"], str):
            raise ComparisonSpecError("fixed error requires a versioned metric and threshold")
        finite_decimal(fidelity["threshold"])
    elif fidelity["error_metric"] is not None or fidelity["threshold"] is not None:
        raise ComparisonSpecError("lossless/curve has no fixed-error threshold")
    if (kind == "QUALITY_CURVE") != bool(fidelity["quality_metrics"]):
        raise ComparisonSpecError("only quality curves require quality metrics")


def _selection(policy: dict) -> None:
    validation = policy["kind"] == "VALIDATION_SELECT"
    if validation != bool(policy["selection_dataset_ids"]) or validation != bool(
        policy["objective"]
    ):
        raise ComparisonSpecError("validation selection requires separate data and objective")


def _guarantee(config: dict) -> None:
    guarantee = config["guarantee"]
    expected = {
        "LOSSLESS": "LOSSLESS",
        "ERROR_BOUNDED_LOSSY": "PROVEN_BOUND",
        "UNBOUNDED_LOSSY": "UNBOUNDED",
        "RATE_CONTROLLED_LOSSY": "RATE_CONTROLLED",
    }[config["loss_mode"]]
    if guarantee["kind"] != expected:
        raise ComparisonSpecError("loss mode and guarantee type disagree")
    if expected == "LOSSLESS" and (
        not guarantee["original_domain_total"] or guarantee["unit"] != "BITWISE"
    ):
        raise ComparisonSpecError("lossless guarantee must preserve the complete original bits")
    if expected in {"UNBOUNDED", "RATE_CONTROLLED"} and guarantee["original_domain_total"]:
        raise ComparisonSpecError("unbounded/rate-controlled mode cannot claim a total bound")
    if expected == "PROVEN_BOUND":
        if not guarantee["metric"] or not isinstance(guarantee["threshold"], str):
            raise ComparisonSpecError("bound guarantee requires metric and threshold")
        finite_decimal(guarantee["threshold"])
    elif guarantee["metric"] is not None or guarantee["threshold"] is not None:
        raise ComparisonSpecError("unbounded/rate/lossless cannot claim a fixed bound")


@dataclass(frozen=True, slots=True)
class FrozenSpec:
    """Own canonical serialized state; callers never receive mutable identity data."""

    serialized: bytes
    domain: ClassVar[str]

    def __post_init__(self) -> None:
        try:
            document = json.loads(self.serialized)
        except (ValueError, UnicodeError) as error:
            raise ComparisonSpecError("invalid specification JSON") from error
        validate_schema(document, SCHEMAS[self.domain])
        self.validate_semantics(document)
        if canonical_json_bytes(document) != self.serialized:
            raise ComparisonSpecError("specification must use canonical JSON")

    @classmethod
    def from_document(cls, document: dict):
        try:
            serialized = canonical_json_bytes(document)
        except ValueError as error:
            raise ComparisonSpecError(f"invalid canonical specification: {error}") from error
        return cls(serialized)

    @classmethod
    def load(cls, path: Path):
        return cls.from_document(json.loads(path.read_text(encoding="utf-8")))

    def to_document(self) -> dict:
        return json.loads(self.serialized)

    @property
    def id(self) -> str:
        return stable_id(self.domain, self.to_document(), version="v3")

    def validate_semantics(self, document: dict) -> None:
        pass


class TaskSpec(FrozenSpec):
    __slots__ = ()
    domain = "task-spec"

    def validate_semantics(self, document: dict) -> None:
        _fidelity(document["fidelity"])
        logical = document["logical_schema"]
        if len(logical["axes"]) != len(logical["shape"]):
            raise ComparisonSpecError("logical axes and shape disagree")
        if len(logical["units"]) != len(logical["channel_ids"]):
            raise ComparisonSpecError("ordered channel identities and units disagree")
        if len(logical["dtypes"]) not in {1, len(logical["channel_ids"])}:
            raise ComparisonSpecError("dtype vector must be homogeneous or channel aligned")
        for dtype in logical["dtypes"]:
            try:
                dt = np.dtype(dtype)
            except TypeError as error:
                raise ComparisonSpecError("invalid logical dtype") from error
            if dt.kind not in "biuf" or dt.itemsize not in {1, 2, 4, 8}:
                raise ComparisonSpecError("unsupported logical dtype")
        if (
            document["fidelity"]["kind"] == "LOSSLESS"
            and document["recovery"]["mode"] != "EXACT_GRID"
        ):
            raise ComparisonSpecError("lossless task requires exact original-grid recovery")


class ComparisonContract(FrozenSpec):
    __slots__ = ()
    domain = "comparison-contract"

    def validate_semantics(self, document: dict) -> None:
        _fidelity(document["fidelity"])
        _selection(document["selection_policy"])
        native = document["mode"] == "COMMON_NATIVE_API"
        if native != (document["cost_boundary"] == "NATIVE_COMPONENT"):
            raise ComparisonSpecError("native component and complete-object costs cannot mix")
        if native != (document["timing_boundary"] == "CORE_API"):
            raise ComparisonSpecError("complete-object comparison must include the pipeline")
        if native != (document["workload"] == "API_COMPONENT"):
            raise ComparisonSpecError("native/whole-object workload boundary mismatch")
        if (
            document["resources"]["isa_policy"] == "FIXED"
            and not document["resources"]["allowed_isa"]
        ):
            raise ComparisonSpecError("fixed ISA policy requires an explicit permitted set")
        if (
            document["fidelity"]["kind"] == "LOSSLESS"
            and document["recovery"]["mode"] != "EXACT_GRID"
        ):
            raise ComparisonSpecError("lossless contract requires exact recovery")


def method_id(definition: dict) -> str:
    document = {"schema_version": "tscb.method-definition.v1", **definition}
    validate_schema(document, SCHEMAS["method-definition"])
    # Names are display text. The reviewed semantic definition/variant governs
    # whether two implementations are the same method, never codec aliases.
    payload = {key: value for key, value in document.items() if key != "name"}
    return stable_id("method", payload, version="v3")


def implementation_id(definition: dict) -> str:
    document = {"schema_version": "tscb.implementation-definition.v1", **definition}
    validate_schema(document, SCHEMAS["implementation-definition"])
    return stable_id("implementation", document, version="v3")


class GroupSpec(FrozenSpec):
    __slots__ = ()
    domain = "group-spec"

    def validate_semantics(self, document: dict) -> None:
        members = document["members"]
        _unique(members, "member_id")
        _unique(members, "codec_key")
        _unique(document["method_equivalence"], "class_id")
        coverage = [
            member
            for equivalence in document["method_equivalence"]
            for member in equivalence["members"]
        ]
        if len(coverage) != len(set(coverage)) or set(coverage) != {
            m["member_id"] for m in members
        }:
            raise ComparisonSpecError("method equivalence must partition all frozen members")
        by_member = {
            member: e["class_id"] for e in document["method_equivalence"] for member in e["members"]
        }
        by_method = {}
        for member in members:
            mid = method_id(member["method"])
            if member["implementation"]["method_id"] != mid:
                raise ComparisonSpecError("implementation is bound to a different method")
            implementation_id(member["implementation"])
            if mid in by_method and by_method[mid] != by_member[member["member_id"]]:
                raise ComparisonSpecError("same method/build/alias cannot increase method count")
            by_method[mid] = by_member[member["member_id"]]
        if not any(member["role"] == "CORE" for member in members):
            raise ComparisonSpecError("group must freeze at least one core member")
        if document["scope"] == "CORE_COMPARISON" and (
            document["minimum_distinct_methods"] < 2
            or document["minimum_independent_real_sources"] < 2
        ):
            raise ComparisonSpecError("core comparison requires two methods and real sources")


class CorpusSpec(FrozenSpec):
    __slots__ = ()
    domain = "corpus-spec"

    def validate_semantics(self, document: dict) -> None:
        datasets = document["datasets"]
        _unique(datasets, "dataset_id")
        by_id = {dataset["dataset_id"]: dataset for dataset in datasets}
        for dataset in datasets:
            finite_decimal(dataset["weight"], positive=True)
            if dataset["role"] == "CORE" and dataset["split"] not in {"TEST", "UNSPLIT"}:
                raise ComparisonSpecError("core evaluation data cannot be training/selection data")
            parents = dataset["parents"]
            _unique(parents, "dataset_id")
            if dataset["dataset_id"] in {p["dataset_id"] for p in parents}:
                raise ComparisonSpecError("dataset cannot derive from itself")
            if dataset["derivation"] == "ORIGINAL" and parents:
                raise ComparisonSpecError("original dataset cannot claim parent derivations")
            if dataset["derivation"] not in {"ORIGINAL", "SYNTHETIC"} and not parents:
                raise ComparisonSpecError("derived dataset must declare parent lineage")
            if dataset["source_kind"] == "REAL" and (
                dataset["derivation"] == "SYNTHETIC"
                or any(p["source_kind"] != "REAL" for p in parents)
            ):
                raise ComparisonSpecError(
                    "synthetic lineage cannot become an independent real source"
                )
            for parent in parents:
                if parent["dataset_id"] in by_id:
                    source = by_id[parent["dataset_id"]]
                    expected = {
                        "dataset_id": source["dataset_id"],
                        "source_kind": source["source_kind"],
                        **{
                            key: source["source"][key]
                            for key in ("family", "entity", "independence_unit")
                        },
                    }
                    if parent != expected:
                        raise ComparisonSpecError("parent provenance disagrees with frozen source")
        visiting, visited = set(), set()

        def visit(dataset_id: str) -> None:
            if dataset_id in visiting:
                raise ComparisonSpecError("cyclic source derivation chain")
            if dataset_id in visited or dataset_id not in by_id:
                return
            visiting.add(dataset_id)
            for parent in by_id[dataset_id]["parents"]:
                visit(parent["dataset_id"])
            visiting.remove(dataset_id)
            visited.add(dataset_id)

        for dataset_id in by_id:
            visit(dataset_id)

    def independent_real_source_groups(self) -> tuple[tuple[str, ...], ...]:
        datasets = self.to_document()["datasets"]
        by_id = {row["dataset_id"]: row for row in datasets}

        def ancestry(row: dict) -> set[tuple[str, str]]:
            source = row["source"]
            tokens = {(key, source[key]) for key in ("family", "entity", "independence_unit")}
            tokens.add(("dataset", row["dataset_id"]))
            for parent in row["parents"]:
                tokens.update(
                    (key, parent[key]) for key in ("family", "entity", "independence_unit")
                )
                tokens.add(("dataset", parent["dataset_id"]))
                if parent["dataset_id"] in by_id:
                    tokens.update(ancestry(by_id[parent["dataset_id"]]))
            return tokens

        groups: list[tuple[set[str], set[tuple[str, str]]]] = []
        for row in datasets:
            if row["role"] != "CORE" or row["source_kind"] != "REAL":
                continue
            ids, tokens = {row["dataset_id"]}, ancestry(row)
            disjoint = []
            for prior_ids, prior_tokens in groups:
                if tokens & prior_tokens:
                    ids.update(prior_ids)
                    tokens.update(prior_tokens)
                else:
                    disjoint.append((prior_ids, prior_tokens))
            disjoint.append((ids, tokens))
            groups = disjoint
        # A newly joined component can bridge earlier groups; close transitively.
        changed = True
        while changed:
            changed = False
            for left in range(len(groups)):
                for right in range(left + 1, len(groups)):
                    if groups[left][1] & groups[right][1]:
                        groups[left][0].update(groups[right][0])
                        groups[left][1].update(groups[right][1])
                        groups.pop(right)
                        changed = True
                        break
                if changed:
                    break
        return tuple(sorted(tuple(sorted(ids)) for ids, _ in groups))


class MethodConfigMap(FrozenSpec):
    __slots__ = ()
    domain = "method-config-map"

    def validate_semantics(self, document: dict) -> None:
        _selection(document["selection_policy"])
        _unique(document["members"], "member_id")
        for member in document["members"]:
            _unique(member["configs"], "config_key")
            if len(member["configs"]) > document["selection_policy"]["max_configs_per_method"]:
                raise ComparisonSpecError("method exceeds predeclared parameter-selection budget")
            if (
                document["selection_policy"]["kind"] == "FROZEN_DEFAULT"
                and len(member["configs"]) != 1
            ):
                raise ComparisonSpecError("frozen default requires one configuration per method")
            for config in member["configs"]:
                _guarantee(config)


class ExpectedOutcomeMatrix(FrozenSpec):
    __slots__ = ()
    domain = "expected-outcome-matrix"

    def validate_semantics(self, document: dict) -> None:
        keys = [(e["dataset_id"], e["member_id"], e["config_key"]) for e in document["entries"]]
        if len(keys) != len(set(keys)):
            raise ComparisonSpecError("duplicate expected-outcome matrix cell")
        for entry in document["entries"]:
            expectation = entry["expected"]
            if expectation["outcome"] == "REJECT" and expectation["origin"] not in {
                "SOURCE_DOMAIN",
                "TASK",
            }:
                raise ComparisonSpecError(
                    "missing adapters/environment are blocked, not correct source rejections"
                )


class ExecutionJob(FrozenSpec):
    __slots__ = ()
    domain = "execution-job"

    def validate_semantics(self, document: dict) -> None:
        _guarantee(document)


def admit_fidelity(fidelity: dict, config: dict) -> None:
    """Empirical curve membership never grants fixed-bound ranking eligibility."""
    _guarantee(config)
    guarantee = config["guarantee"]
    if fidelity["kind"] == "LOSSLESS" and config["loss_mode"] != "LOSSLESS":
        raise ComparisonSpecError("lossy configuration cannot enter the lossless ranking")
    if fidelity["kind"] == "QUALITY_CURVE" and config["loss_mode"] == "LOSSLESS":
        raise ComparisonSpecError(
            "lossless reference must be disclosed separately from lossy curve ranking"
        )
    if fidelity["kind"] == "FIXED_ERROR" and (
        guarantee["kind"] != "PROVEN_BOUND"
        or not guarantee["original_domain_total"]
        or guarantee["metric"] != fidelity["error_metric"]
        or guarantee["unit"] != fidelity["unit"]
        or finite_decimal(guarantee["threshold"]) > finite_decimal(fidelity["threshold"])
    ):
        raise ComparisonSpecError(
            "fixed-error ranking requires the total original-domain guarantee"
        )
