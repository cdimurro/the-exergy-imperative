# Environment, public-health impact screening, and economics

## Climate accounting

`assess_impacts()` creates a gas inventory and applies IPCC AR6 global warming
potentials at 20 and 100 years. This supports direct CO2, fossil and non-fossil
methane, N2O, selected HFCs, CF4, CFC-11, and custom factor packs. Refrigerant
leakage is supplied as gas mass.

Electricity uses a country/year aggregate lifecycle CO2e factor. Because the
underlying gas composition is not available, that aggregate is not re-weighted
between warming horizons. Combustion uses factor-by-gas values and therefore can
show the 20-year versus 100-year difference.

For inventories assembled from user data, `assess_ghg_boundaries()` keeps
combustion, process, fugitive, and purchased-energy emissions separate.
Allocated electricity-and-heat emissions are treated as a contextual view and
excluded from the combined total by default to avoid double counting.

```python
inventory = xi.assess_ghg_boundaries(
    combustion_gases_kg={"CO2": 100_000},
    fugitive_gases_kg={"CH4-fossil": 500},
    purchased_energy_co2e_kg=25_000,
    allocated_electricity_heat_co2e_kg=30_000,
)
```

## Methane venting, flaring, and recovery

`assess_methane_project()` compares four dispositions: `vented`, `flared`,
`oxidized`, and `recovered`. It reports remaining methane, methane converted to
CO2, recovered energy, both warming horizons, product revenue, and optional
project economics. Mass input is preferred. Volume input is supported with an
explicit methane-density assumption.

Set `methane_origin="fossil"` or `"biogenic"`. Biogenic methane uses the
bundled non-fossil methane GWP and reports physical oxidation CO2 without
counting that biogenic CO2 as fossil combustion emissions.

The default 98% flare destruction value is a screening assumption for a
properly operated flare, based on US EPA AP-42. Actual flare efficiency depends
on composition, loading, mixing, maintenance, wind, and operating conditions.
Omitted efficiencies are resolved from each selected disposition: 0% for
venting, 98% for flaring, and upper-bound 100% screens for oxidation and
recovery. Override the oxidation and recovery defaults for project decisions.

Primary references:

- [IPCC AR6 WGI Chapter 7](https://www.ipcc.ch/report/ar6/wg1/chapter/chapter-7/)
- [IPCC 2006 Guidelines, stationary combustion](https://www.ipcc-nggip.iges.or.jp/public/2006gl/pdf/2_Volume2/V2_2_Ch2_Stationary_Combustion.pdf)
- [Ember Yearly Electricity Data](https://ember-energy.org/data/yearly-electricity-data/)
- [Our World in Data energy repository](https://github.com/owid/energy-data)

## Air pollution and health

Fuel profiles can estimate SO2, NOx, PM2.5, PM10, CO, VOC, and other available
pollutants as bounded mass inventories. Results attach compact profiles of
well-established health concerns and exposure routes.

Those pollutant outputs are inventories with health context. Emissions at a
stack are not the same as ambient concentration or inhaled dose. They are never
reported as exposure, attributable cases, diagnoses, or individual risk.

For a more useful screening result when site data are absent,
`estimate_health_benefits()` packages the U.S. EPA's Third Edition regional
benefits-per-kWh (BPK) values. EPA derived these values with AVERT 4.3 and
COBRA 5.1. They monetize modeled PM2.5- and ozone-related outdoor-air public
health benefits from SO2, NOx, primary PM2.5, and VOC reductions for:

- 14 AVERT grid regions in the contiguous United States; and
- uniform and peak energy efficiency, utility and distributed PV, utility and
  distributed PV-plus-storage, and onshore and offshore wind where published.

```python
health = xi.estimate_health_benefits(
    region="Rocky Mountains",
    project_type="Uniform EE",
    energy=1_000,
    unit="MWh",
)

health.benefit_rate.to_dict()
# {'value': 2.265, 'unit': '2023 USD cents/kWh',
#  'low': 1.8, 'high': 2.73, 'confidence': 'screening range'}

health.monetized_benefit.to_dict()
# {'value': 22650.0, 'unit': '2023 USD/year',
#  'low': 18000.0, 'high': 27300.0, 'confidence': 'screening range'}
```

The central value is only the arithmetic midpoint for convenient comparison;
it is not an additional EPA estimate. Retain the low/high range in reporting.
`energy` is the annual intervention quantity. If it is omitted, the result is
normalized to one intervention MWh/year.
Users can replace both BPK bounds with `low_cents_per_kwh` and
`high_cents_per_kwh`; the output then labels the factor as user provided.

The packaged values use 2023 electricity, emissions, population,
baseline-incidence, income, and valuation inputs; 2023 USD; and a 2% discount
rate. EPA suggests using them for analysis years 2018-2028. Benefits associated
with emissions changes in a source region include modeled benefits outside that
region, so the values cannot locate neighborhood impacts. Alaska, Hawaii,
Puerto Rico, other U.S. territories, indoor air, climate benefits, and health
pathways outside COBRA 5.1 are excluded. For local or decision-grade work, run
an appropriately configured AVERT/COBRA, BenMAP, dispersion, or comparable
exposure analysis with current site and population data.

Users may supply `damage_costs_per_kg` when they have factors applicable to the
pollutant, source, place, population, year, and currency. These values remain
identified as user supplied. Declare `currency` alongside those factors; when
health benefits feed project economics, it must match the economics currency
unless an explicit annual health-benefit value replaces the derived amount.

Primary references:

- [US EPA particulate matter basics](https://www.epa.gov/pm-pollution/particulate-matter-pm-basics)
- [US EPA nitrogen dioxide basics](https://www.epa.gov/no2-pollution/basic-information-about-no2)
- [US EPA combustion-product health effects](https://www.epa.gov/indoor-air-quality-iaq/sources-combustion-products)
- [US EPA BPK values and appropriate use](https://www.epa.gov/statelocalenergy/estimating-health-benefits-kilowatt-hour-energy-efficiency-and-renewable-energy)
- [US EPA BPK Third Edition technical report](https://www.epa.gov/system/files/documents/2024-12/bpk_report_third_edition.pdf)
- [EMEP/EEA air pollutant emission inventory guidebook](https://www.eea.europa.eu/en/analysis/publications/emep-eea-guidebook-2023)

## Economic calculations

`evaluate_economics()` produces a complete annual cash-flow series and reports:

- net present value and internal rate of return;
- simple and discounted payback;
- benefit-cost ratio and capital recovery factor;
- levelized cost per saved MWh of energy and exergy;
- marginal abatement cost per tonne CO2e;
- annual energy, maintenance, carbon, health-externality, and other benefits.

Energy-price escalation and residual value are supported. Carbon and health
externalities are kept visible rather than folded silently into energy savings.
The project currency is a label; exchange rates and inflation are not inferred.
Use cash flows on a consistent real or nominal basis.

The IRR helper returns `None` when there is no robust unique root. NPV should
remain the primary comparison for mutually exclusive projects.

Explicit annual energy and carbon price sequences can replace constant-price
escalation. `TechnologyCostScenario` evaluates entirely user-supplied CAPEX,
fixed and variable OPEX, fuel use, output, degradation, emissions, price paths,
revenue, and residual value. Its generic levelized-cost result can represent
useful heat, electricity, hydrogen, cooling, product output, or another declared
denominator.

`compare_technology_cost_scenarios()` ranks comparable cases by levelized cost.
`stranded_asset_value()` and `stranded_cost_sensitivity()` calculate
straight-line undepreciated value and net stranded cost across early-retirement
years. The library does not ship proprietary technology cost or policy scenario
values.

## Scenario and uncertainty support

`compare_scenarios()` puts energy, useful exergy, exergy destruction, CO2e,
pollutants, and economics into a common comparison. `monte_carlo()` propagates
fixed, uniform, triangular, or normal input distributions with a reproducible
seed and Spearman rank sensitivity. `one_at_a_time_sensitivity()` provides a
simple audit table. `expected_value_of_perfect_information()` estimates the
maximum rational value of resolving uncertainty before a decision.
