"""Validate the project-local, versioned M0 document contracts.

Structural validation precedes semantic/path/identity checks. References are
resolved only within a schema document; no filesystem or network retrieval.
"""
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.validators import extend
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable

from .assets import ContractError, content_id, load_json, local_file, require

_DRAFT = "https://json-schema.org/draft/2020-12/schema"
_NAMES = frozenset({"plugin", "suite", "experiment", "matrix", "required-capabilities", "case-catalog",
                    "native-inventory", "observation", "corpus", "lossless-stage-suite", "native-preflight-suite",
                    "corpus-feature-policy", "corpus-boundary-fixtures", "corpus-domain-intake",
                    "native-requirements", "native-admission-policy", "method-boundaries", "pbepla-cases", "measurement-policy", "comparison-contract", "resource-candidate-policy", "tv-composition-suite", "tv-ingress-suite", "tv-ingress-providers-suite", "typed-source", "source-loader-registry", "service-suite", "service-workloads", "service-recipe-bindings", "recipe", "qualification", "trace", "native-submission-policy", "stage-receipt", "m1-stage-receipt", "m2-stage-receipt", "m3-stage-receipt", "m4-stage-receipt"})


# Counts/ABI IDs are serialized integers, not integer-valued floating tokens.
_StrictValidator = extend(Draft202012Validator, type_checker=Draft202012Validator.TYPE_CHECKER.redefine(
    "integer", lambda _checker, instance: type(instance) is int))


@dataclass(frozen=True, slots=True)
class Contract:
    name: str
    document_id: str
    document: dict
    validator: Draft202012Validator

    def validate(self, value, location: str) -> None:
        try:
            self.validator.validate(value)
        except ValidationError as exc:
            trail = "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in exc.absolute_path)
            raise ContractError(f"{location}: violates {self.name} schema at /{trail}: {exc.message}") from exc
        except Unresolvable as exc:
            raise ContractError(f"{location}: unresolved schema reference (offline): {exc}") from exc


def load_contract(root: Path, name: str) -> Contract:
    require(name in _NAMES, f"unknown local schema: {name}")
    relative = f"schemas/{name}.schema.json"
    return compile_contract(name, load_json(local_file(root, relative)))


def compile_contract(name: str, doc: dict) -> Contract:
    """Compile a local contract, including a hash-verified run snapshot."""
    require(name in _NAMES, f"unknown local schema: {name}")
    require(isinstance(doc, dict) and doc.get("$schema") == _DRAFT, f"invalid schema dialect: {name}")
    try:
        Draft202012Validator.check_schema(doc)
    except SchemaError as exc:
        raise ContractError(f"invalid schema definition: {name}: {exc.message}") from exc
    return Contract(name, content_id(doc), doc, _StrictValidator(doc, registry=Registry()))
