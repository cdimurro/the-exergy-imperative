"""Reference-metadata assessment; never a closed physical-exergy certificate."""

from __future__ import annotations

import json
import math
from typing import Any, Mapping, Optional

REFERENCE_ASSESSMENT_SCHEMA_VERSION = "exergy-reference-assessment/1"
FULL_REFERENCE_FIELDS = ("T0_K", "P0_Pa", "composition")


def assess_exergy_reference(
    environment: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Assess an explicitly declared full-reference tuple without inventing it.

    This reporting check implements the missing-reference distinction from the
    saved-output audit. It does not decide numerical correctness, stream/storage
    completeness, direct-transfer service, or whether a thermal model needs P0
    and composition. Existing model-specific calculations remain unchanged.
    """
    if environment is not None and not isinstance(environment, Mapping):
        raise ValueError("environment must be a mapping or None")
    reference = {
        key: environment[key]
        for key in FULL_REFERENCE_FIELDS
        if environment is not None
        and key in environment
        and environment[key] is not None
    }
    for key in ("T0_K", "P0_Pa"):
        if key in reference:
            value = reference[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"{key} must be a positive finite number in its named unit"
                )
            try:
                valid = math.isfinite(value) and value > 0
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError(
                    f"{key} must be a positive finite number in its named unit"
                )
    if "composition" in reference:
        value = reference["composition"]
        if not (
            isinstance(value, str)
            and bool(value.strip())
            or isinstance(value, dict)
            and bool(value)
        ):
            raise ValueError(
                "composition must be a nonempty declaration string or JSON object"
            )
    try:
        # Independent copy; caller data and the assessment cannot mutate each other.
        reference = json.loads(json.dumps(reference, allow_nan=False))
    except (ValueError, TypeError) as error:
        raise ValueError(
            "reference metadata must be finite JSON-compatible data"
        ) from error
    missing = [key for key in FULL_REFERENCE_FIELDS if key not in reference]
    return {
        "schema_version": REFERENCE_ASSESSMENT_SCHEMA_VERSION,
        "reference_gate": "unresolved" if missing else "passed",
        "physical_exergy_status": "unresolved",
        "reason": (
            "declared_reference_environment_missing_or_incomplete"
            if missing
            else "reference_present_but_closed_carrier_account_not_tested"
        ),
        "reference_carried": reference,
        "missing_reference_fields": missing,
        "screening_allowed": True,
        "screening_qualifier": (
            "Full reference incomplete; screening only; not settled physical exergy."
            if missing
            else "Reference declared; closed carrier account untested; screening only."
        ),
        "assurance_scope": "REFERENCE_METADATA_ONLY",
        "physical_account_verified": False,
        "claim_permitted": False,
    }
