import exergy_imperative as xi

result = xi.monte_carlo(
    lambda efficiency, energy_price: {
        "annual_savings": 10_000 * (1.0 - efficiency) * energy_price
    },
    {
        "efficiency": xi.DistributionSpec.triangular(0.78, 0.85, 0.92),
        "energy_price": xi.DistributionSpec.uniform(35, 70),
    },
    samples=5_000,
    seed=42,
)

print(result.to_dict())
