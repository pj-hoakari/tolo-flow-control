from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

RESULTS = Path(__file__).resolve().parent / "results"

FLOW_C_30S = {"cont": 0.0, "p3": 0.55, "p5": 0.79, "p10": 1.72}
OCC_D_30S = {"cont": 0.0, "p3": 0.094, "p5": 0.16, "p10": 0.42}
FLOW_C_60S = {"cont": 0.0, "p3": 0.35, "p5": 0.50, "p10": 1.17, "tiny": 0.03}
OCC_D_60S = {"cont": 0.0, "p3": 0.068, "p5": 0.10, "p10": 0.28, "tiny": 0.005}


def write_outputs(name: str, payload: dict[str, Any], markdown: str) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (RESULTS / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(f"wrote {RESULTS / name}.json and .md", file=sys.stderr)
