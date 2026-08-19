# Industrial data pilot: meter export to investment screen

This reproducible case shows the full product path: an ordinary meter export
gains an explicit energy-quality field, becomes an auditable process assessment,
and ends as a ranked business-case screen.

The bundled CSV is illustrative. It is not measured plant data and its results
are not a design, bid, guarantee, or investment approval. Replace it with site
records and confirm every boundary and assumption before making a decision.

## 1. Start with the records already available

[`industrial_pilot_meter_export.csv`](../examples/industrial_pilot_meter_export.csv)
contains quarterly energy, equipment, temperature, measured-efficiency, tariff,
and project-capital fields for steam, compressed air, and a furnace. There are
no proprietary values or hidden lookups in the file.

Use Exergy Factor for a quick one-record check. Use Quantity and Quality to add
the canonical field across the file:

```bash
quantity-quality clean industrial_pilot_meter_export.csv \
  --output industrial_pilot_quantity_quality.csv
```

The cleaner intentionally flags the example for review: a generic
`Energy (MWh)` header does not prove whether a row is fuel input, electricity,
or delivered heat. That boundary cannot be guessed safely. The assessment step
resolves it by assigning an explicit process template to each meter group.

## 2. Run the assessment and decision screen

From this repository:

```bash
python examples/industrial_data_pilot.py \
  --output-dir output/industrial-pilot
```

The script performs these inspectable steps:

1. Reads the source CSV without changing it.
2. Infers and retains a field mapping, including unit conversions.
3. Groups annual metered input energy by equipment.
4. Uses measured efficiency and temperature fields where supplied.
5. Calculates energy, exergy, emissions, and a template-based improvement
   screen without combining those ledgers.
6. Applies the capital cost and tariff declared in the input file.
7. Ranks opportunities by screening NPV and writes the audit trail, portfolio
   ranking, and an HTML report for the recommended first audit.

## 3. Reproducible result

With the bundled inputs, the recommended first detailed audit is compressed
air. The decision table is:

| Priority | Equipment | Input energy (MWh/y) | Exergy destroyed or lost (MWh_ex/y) | Screening energy savings (MWh/y) | Screening NPV (USD) | Payback (years) |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Compressed air | 3,500 | 2,975 | 700 | 431,587 | 2.34 |
| 2 | Steam system | 12,000 | 8,416 | 1,200 | 178,905 | 4.63 |
| 3 | Furnace | 8,000 | 3,359 | 1,200 | 128,905 | 5.56 |

The largest thermodynamic loss is not automatically the first investment. The
steam system destroys more exergy, but the compressed-air screen ranks first
because its declared electricity price and project cost produce the highest
NPV. That separation between physical loss and financial priority is the point
of the decision engine.

## 4. What must be replaced for a real pilot

The example uses provided annual meter totals, efficiencies, temperatures,
tariffs, and capital costs. It still uses bundled screening priors for the
improvement fraction and published environmental factors. Before investment
approval, replace at least:

- the illustrative meter export with a complete, quality-controlled site
  extract;
- ambiguous meter boundaries with a signed mapping and equipment list;
- screening improvement fractions with measured baselines or engineering
  estimates;
- flat tariffs with the applicable demand, time-of-use, and fuel-price model;
- preliminary capital cost with a scoped estimate or vendor bid; and
- generic emissions and pollutant factors with site, supplier, permit, or
  jurisdiction-specific data where available.

The output remains valuable before those refinements: it tells the team where
better data and a detailed audit are most likely to change a decision.
