from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location(
    "industrial_data_pilot", ROOT / "examples" / "industrial_data_pilot.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_industrial_data_pilot_is_reproducible_and_explicitly_screening(tmp_path):
    audit, decision = MODULE.build_pilot()
    assert len(audit["records"]) == 12
    assert decision["schema_version"] == "industrial_data_pilot_v1"
    assert len(decision["opportunities"]) == 3
    assert (
        decision["recommended_first_audit"] == decision["opportunities"][0]["equipment"]
    )
    assert all(item["screening_only"] for item in decision["opportunities"])
    assert all(
        item["annual_input_energy_mwh"] > 0 for item in decision["opportunities"]
    )
    assert all(item["npv_usd"] is not None for item in decision["opportunities"])

    MODULE.write_outputs(audit, decision, tmp_path)
    assert (tmp_path / "ingestion-audit.json").exists()
    assert (tmp_path / "portfolio-ranking.json").exists()
    assert (tmp_path / "recommended-project.html").exists()
