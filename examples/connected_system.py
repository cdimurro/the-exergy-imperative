"""Compose an arbitrary process from explicit energy and exergy flows."""

import exergy_imperative as xi

components = [
    {"id": "supply", "kind": "source"},
    {"id": "converter", "kind": "converter"},
    {"id": "load", "kind": "sink"},
]

flows = [
    {
        "id": "resource",
        "energy": 100,
        "target": "supply",
        "exergy_factor": 1,
    },
    {
        "id": "converter feed",
        "energy": 100,
        "source": "supply",
        "target": "converter",
        "exergy_factor": 1,
    },
    {
        "id": "useful transfer",
        "energy": 40,
        "source": "converter",
        "target": "load",
        "exergy_factor": 1,
    },
    {
        "id": "waste heat",
        "energy": 60,
        "exergy": 10,
        "source": "converter",
        "role": "loss",
    },
    {
        "id": "useful service",
        "energy": 40,
        "source": "load",
        "exergy_factor": 1,
    },
]

result = xi.analyze_system("example plant", components=components, flows=flows)
print(result.to_dict())
