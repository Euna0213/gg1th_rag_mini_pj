"""저장된 답변 평가 결과에서 한 질문의 답변과 정답 조문 원문을 나란히 보여준다 (API·크레딧 사용 없음).

사용: uv run python scripts/show_answer.py q18
"""
import json
import sys
from pathlib import Path

from qdrant_client import QdrantClient

ROOT = Path(__file__).resolve().parent.parent
qid = sys.argv[1] if len(sys.argv) > 1 else "q18"

rows = {r["id"]: r for r in json.loads((ROOT / "eval/results/answers.json").read_text(encoding="utf-8"))["rows"]}
gold = {g["id"]: g for g in map(json.loads, (ROOT / "eval/golden_set.jsonl").read_text(encoding="utf-8").splitlines())}
row, g = rows[qid], gold[qid]

points, _ = QdrantClient(url="http://localhost:6333").scroll("ai_basic_law", limit=1000, with_payload=True, with_vectors=False)

print(f"질문: {row['question']}   (정답 조문: {', '.join(g['gold_articles']) or '없음'})")
print(f"판정자 점수: {row.get('judge')}\n")
print("=" * 30, "답변", "=" * 30)
print(row["answer"])
for art in g["gold_articles"]:
    print("\n" + "=" * 30, f"원문 {art}", "=" * 30)
    for p in points:
        if p.payload["article"] == art:
            print(p.payload["text"].split("\n", 1)[-1])
