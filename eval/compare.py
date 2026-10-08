"""eval/results/*.json 의 요약을 한 표로 비교한다. 사용: uv run python -m eval.compare"""
import json
from pathlib import Path

ORDER = ["Hit@1", "Hit@3", "Hit@5", "Recall@5", "MRR"]
rows = [json.loads(p.read_text(encoding="utf-8"))["summary"] for p in sorted((Path(__file__).parent / "results").glob("*.json"))]
rows.sort(key=lambda r: -r["MRR"])
print("| method | " + " | ".join(ORDER) + " |")
print("|---|" + "---|" * len(ORDER))
for r in rows:
    print(f"| {r['method']} | " + " | ".join(f"{r[k]:.3f}" for k in ORDER) + " |")
