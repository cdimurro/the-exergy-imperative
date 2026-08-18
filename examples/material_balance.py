"""Close a production-separator material and constituent balance."""

import exergy_imperative as xi

result = xi.analyze_material_system(
    "production separator",
    components=[{"id": "separator", "kind": "reactor-separator"}],
    streams=[
        {
            "id": "wellstream",
            "mass": 100,
            "unit": "t",
            "target": "separator",
            "composition": {"oil": 0.45, "gas": 0.15, "water": 0.40},
        },
        {
            "id": "stabilized oil",
            "mass": 45,
            "unit": "t",
            "source": "separator",
            "material": "oil",
        },
        {
            "id": "gas",
            "mass": 15,
            "unit": "t",
            "source": "separator",
            "material": "gas",
        },
        {
            "id": "produced water",
            "mass": 40,
            "unit": "t",
            "source": "separator",
            "role": "loss",
            "material": "water",
        },
    ],
)

print(result.to_dict())
