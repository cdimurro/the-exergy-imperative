# Reference declarations and unsettled exergy accounts

`assess_exergy_reference` checks the explicitly supplied full reference tuple.
It preserves partial declarations and never fills missing fields from defaults.

```python
from exergy_imperative import assess_exergy_reference

assessment = assess_exergy_reference({"T0_K": 283.15})
assert assessment["missing_reference_fields"] == ["P0_Pa", "composition"]
assert assessment["physical_exergy_status"] == "unresolved"
```

A declaration with positive finite `T0_K`, positive finite `P0_Pa`, and a
nonempty `composition` passes this metadata check. Its physical account still
remains unresolved. A reference declaration does not establish carrier validity,
all boundary streams, storage changes, entropy generation or matched delivered
service. Caller-authored success flags cannot change that status.

This is the full-reference reporting convention from the
[20-record saved-output audit](https://github.com/cdimurro/ARIA/blob/main/output/exergy-packet-corrections-20261009/README.md).
It is not a requirement that every thermal equation uses pressure or composition.
Existing model-specific calculations and fidelity classifications are unchanged.
The absence of those fields does not prove a T0-based thermal number wrong.

The API uses only the standard library, performs no I/O and accepts no physical
result as verified. Invalid supplied numbers or non-JSON metadata raise
`ValueError`. Results follow the packaged `exergy-reference-assessment/1` schema.
The regression tests use synthetic cases for the audit's 12 partial and eight
absent reference patterns; they are not new measurements or numerical validation
of those historical estimates.

This library update exposes a reporting check. It does not deploy that check
into Exergy Analyst or reopen the closed actuator, fabrication or meter campaigns.
