import json

import pytest

import exergy_imperative as xi
import exergy_imperative.datasets as datasets


def test_nasa_power_records_and_degree_days():
    payload = {
        "source": "NASA POWER",
        "values": {
            "T2M": {"20260101": 10.0, "20260102": 22.0},
            "RH2M": {"20260101": 55.0, "20260102": 60.0},
        },
    }
    records = xi.nasa_power_weather_records(payload)
    enriched = xi.add_weather_metrics(records, heating_base_c=18.0, cooling_base_c=20.0)
    assert enriched[0]["heating_degree_days_c_day"] == pytest.approx(8.0)
    assert enriched[0]["cooling_degree_days_c_day"] == 0.0
    assert enriched[1]["cooling_degree_days_c_day"] == pytest.approx(2.0)
    assert enriched[0]["relative_humidity_percent"] == pytest.approx(55.0)


def test_nasa_power_records_retain_requested_non_temperature_parameters():
    records = xi.nasa_power_weather_records(
        {
            "source": "NASA POWER",
            "values": {
                "RH2M": {"20260101": 55.0, "20260102": 60.0},
                "PRECTOTCORR": {"20260102": 2.5},
            },
        }
    )

    assert records == [
        {
            "date": "2026-01-01",
            "source": "NASA POWER",
            "relative_humidity_percent": 55.0,
        },
        {
            "date": "2026-01-02",
            "source": "NASA POWER",
            "relative_humidity_percent": 60.0,
            "precipitation_mm_day": 2.5,
        },
    ]


@pytest.mark.parametrize(
    ("unit", "raw_value", "expected"),
    [
        ("W m-2", 94.47, 2.26728),
        ("MJ/m^2/day", 8.16, 2.2666666667),
        ("kW-hr/m^2/day", 2.2673, 2.2673),
    ],
)
def test_nasa_power_solar_irradiance_is_converted_to_declared_unit(
    unit, raw_value, expected
):
    payload = {
        "source": "NASA POWER",
        "values": {
            "T2M": {"20260101": 10.0},
            "ALLSKY_SFC_SW_DWN": {"20260101": raw_value},
        },
        "parameter_metadata": {
            "ALLSKY_SFC_SW_DWN": {"units": unit},
        },
    }

    records = xi.nasa_power_weather_records(payload)

    assert records[0]["solar_irradiance_kwh_m2_day"] == pytest.approx(expected)


def test_nasa_power_solar_irradiance_requires_supported_unit_metadata():
    payload = {
        "values": {
            "T2M": {"20260101": 10.0},
            "ALLSKY_SFC_SW_DWN": {"20260101": 94.47},
        }
    }
    with pytest.raises(ValueError, match="unit metadata is required"):
        xi.nasa_power_weather_records(payload)

    payload["parameter_metadata"] = {"ALLSKY_SFC_SW_DWN": {"units": "BTU/ft2/day"}}
    with pytest.raises(ValueError, match="unsupported NASA POWER"):
        xi.nasa_power_weather_records(payload)


def test_fetch_nasa_power_weather_retains_parameter_metadata(monkeypatch, tmp_path):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {
                    "properties": {
                        "parameter": {
                            "T2M": {"20240101": 10.0},
                            "ALLSKY_SFC_SW_DWN": {"20240101": 106.57},
                        }
                    },
                    "parameters": {
                        "T2M": {"units": "C"},
                        "ALLSKY_SFC_SW_DWN": {"units": "W m-2"},
                    },
                    "header": {"fill_value": -999},
                }
            ).encode()

    monkeypatch.setattr(datasets, "urlopen", lambda *_args, **_kwargs: Response())

    result = xi.fetch_nasa_power_weather(
        39.74,
        -104.99,
        "20240101",
        "20240101",
        parameters=("T2M", "ALLSKY_SFC_SW_DWN"),
        cache_dir=tmp_path,
    )

    assert result["parameter_metadata"]["ALLSKY_SFC_SW_DWN"]["units"] == "W m-2"
    assert xi.nasa_power_weather_records(result)[0][
        "solar_irradiance_kwh_m2_day"
    ] == pytest.approx(2.55768)


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("20250231", "20250301", "valid calendar dates"),
        ("20250102", "20250101", "on or before"),
        (20250101, "20250102", "YYYYMMDD"),
    ],
)
def test_fetch_nasa_power_weather_rejects_invalid_date_ranges_locally(
    monkeypatch, start, end, message
):
    def unexpected_request(*_args, **_kwargs):
        raise AssertionError("invalid dates must not make a network request")

    monkeypatch.setattr(datasets, "urlopen", unexpected_request)

    with pytest.raises(ValueError, match=message):
        xi.fetch_nasa_power_weather(39.74, -104.99, start, end)


def test_monthly_climatology_and_anomalies():
    reference = [
        {"date": "2024-01-01", "temperature_c": 8.0},
        {"date": "2024-01-02", "temperature_c": 12.0},
        {"date": "2024-07-01", "temperature_c": 24.0},
        {"date": "2024-07-02", "temperature_c": 28.0},
    ]
    climate = xi.monthly_weather_climatology(
        reference, heating_base_c=18.0, cooling_base_c=20.0
    )
    assert climate.months[1].mean_temperature_c == pytest.approx(10.0)
    assert climate.months[7].mean_cooling_degree_days_c_day == pytest.approx(6.0)
    anomalies = xi.weather_anomalies(
        [{"date": "2026-01-01", "temperature_c": 13.0}], climate
    )
    assert anomalies[0]["temperature_anomaly_c"] == pytest.approx(3.0)


@pytest.mark.parametrize("excluded_temperature", ["", "invalid", float("nan")])
def test_monthly_climatology_ignores_invalid_temperature_outside_reference_period(
    excluded_temperature,
):
    climate = xi.monthly_weather_climatology(
        [
            {"date": "1990-01-01", "temperature_c": excluded_temperature},
            {"date": "2020-01-01", "temperature_c": 10.0},
        ],
        reference_start="2020-01-01",
        reference_end="2020-12-31",
    )

    assert climate.months[1].observations == 1
    assert climate.months[1].mean_temperature_c == pytest.approx(10.0)


def test_weather_normalization_preserves_climatology_provenance():
    climate = xi.monthly_weather_climatology(
        [
            {"date": "1991-01-01", "temperature_c": 0},
            {"date": "2020-01-02", "temperature_c": 2},
        ],
        reference_start="1991-01-01",
        reference_end="2020-12-31",
        source="National meteorological service 1991-2020 normal",
    )
    result = xi.normalize_weather_performance(
        [
            {"date": "2026-01-01", "temperature_c": 0, "energy": 10},
            {"date": "2026-01-02", "temperature_c": 2, "energy": 8},
        ],
        value_field="energy",
        climatology=climate,
    )
    assert result.assumptions["normal_source"] == climate.source
    assert result.assumptions["normal_source_type"] == "monthly climatology"
    assert result.assumptions["normal_reference_start"] == "1991-01-01"
    assert result.assumptions["normal_reference_end"] == "2020-12-31"


def test_weather_normalization_recovers_heating_and_cooling_response():
    temperatures = [0.0, 5.0, 10.0, 18.0, 24.0, 30.0]
    rows = []
    for day, temperature in enumerate(temperatures, 1):
        hdd = max(18.0 - temperature, 0.0)
        cdd = max(temperature - 22.0, 0.0)
        rows.append(
            {
                "date": f"2026-01-{day:02d}",
                "temperature_c": temperature,
                "energy_mwh": 10.0 + 2.0 * hdd + 3.0 * cdd,
            }
        )
    result = xi.normalize_weather_performance(
        rows,
        value_field="energy_mwh",
        unit="MWh",
        heating_base_c=18.0,
        cooling_base_c=22.0,
        normal_heating_degree_days=30.0,
        normal_cooling_degree_days=5.0,
    )
    assert result.intercept_per_observation == pytest.approx(10.0)
    assert result.heating_sensitivity_per_degree_day == pytest.approx(2.0)
    assert result.cooling_sensitivity_per_degree_day == pytest.approx(3.0)
    assert result.normalized_total == pytest.approx(60.0 + 2 * 30 + 3 * 5)
    assert result.r_squared == pytest.approx(1.0)


def test_weather_normalization_requires_declared_normal_weather():
    with pytest.raises(ValueError, match="climatology"):
        xi.normalize_weather_performance(
            [
                {"date": "2026-01-01", "temperature_c": 0, "energy": 1},
                {"date": "2026-01-02", "temperature_c": 1, "energy": 2},
            ],
            value_field="energy",
        )


def test_weather_normalization_rejects_negative_prediction():
    with pytest.raises(ValueError, match="weather-normalized total is negative"):
        xi.normalize_weather_performance(
            [
                {"date": "2026-01-01", "temperature_c": 0, "energy": 10},
                {"date": "2026-01-02", "temperature_c": 10, "energy": 1},
            ],
            value_field="energy",
            heating_base_c=18.0,
            cooling_base_c=18.0,
            normal_heating_degree_days=0.0,
            normal_cooling_degree_days=0.0,
        )


def test_weather_normalization_rejects_climatology_base_conflicts():
    climatology = xi.monthly_weather_climatology(
        [
            {"date": "2024-01-01", "temperature_c": 0},
            {"date": "2024-01-02", "temperature_c": 2},
        ],
        heating_base_c=20.0,
        cooling_base_c=22.0,
    )
    rows = [
        {"date": "2026-01-01", "temperature_c": 0, "energy": 10},
        {"date": "2026-01-02", "temperature_c": 2, "energy": 8},
    ]

    with pytest.raises(ValueError, match="heating_base_c conflicts"):
        xi.normalize_weather_performance(
            rows,
            value_field="energy",
            climatology=climatology,
            heating_base_c=18.0,
        )
    with pytest.raises(ValueError, match="cooling_base_c conflicts"):
        xi.normalize_weather_performance(
            rows,
            value_field="energy",
            climatology=climatology,
            cooling_base_c=18.0,
        )

    derived = xi.normalize_weather_performance(
        rows, value_field="energy", climatology=climatology
    )
    assert derived.assumptions["heating_base_c"] == pytest.approx(20.0)
    assert derived.assumptions["cooling_base_c"] == pytest.approx(22.0)
