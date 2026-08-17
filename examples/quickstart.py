import exergy_imperative as xi

screening = xi.assess(
    technology="natural-gas boiler",
    service="space heating",
    energy=1_000,
    unit="MWh",
    location="Denver, US",
)

print(screening.summary())
print()

refined = screening.refine(
    efficiency=0.93,
    source_temperature="65 C",
    return_temperature="45 C",
    ambient_temperature="5 C",
)

print(refined.summary())
