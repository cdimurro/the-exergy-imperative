# Environment, health screening, and economics

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

This is a hazard screen only. Emissions at a stack are not the same as ambient
concentration or inhaled dose. A defensible health-impact assessment normally
needs stack characteristics, meteorology, atmospheric chemistry, spatially
resolved population, baseline incidence, concentration-response functions, and
an explicit valuation method. The library therefore does not provide universal
health damage factors.

Users may supply `damage_costs_per_kg` when they have factors applicable to the
pollutant, source, place, population, year, and currency. These values remain
identified as user supplied. Declare `currency` alongside those factors; when
health benefits feed project economics, it must match the economics currency
unless an explicit annual health-benefit value replaces the derived amount.

Primary references:

- [US EPA particulate matter basics](https://www.epa.gov/pm-pollution/particulate-matter-pm-basics)
- [US EPA nitrogen dioxide basics](https://www.epa.gov/no2-pollution/basic-information-about-no2)
- [US EPA combustion-product health effects](https://www.epa.gov/indoor-air-quality-iaq/sources-combustion-products)
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
