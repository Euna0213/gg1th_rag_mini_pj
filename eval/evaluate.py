"""Golden set 기반 검색 평가: Hit@K, Recall@K, MRR.

사용: uv run python -m eval.evaluate [--name dense] [--k 5]
조(條) 단위로 평가한다. 한 조가 여러 청크(항)로 나뉘어도 같은 조는 하나로 보고,
처음 등장한 순위를 그 조의 순위로 쓴다.
"""
import argparse
import json
from functools import partial
from pathlib import Path

from rag.reranker import retrieve_reranked
from rag.retriever import retrieve, retrieve_bm25, retrieve_hybrid, retrieve_multiquery

ROOT = Path(__file__).resolve().parent
GOLDEN = ROOT / "golden_set.jsonl"
KS = (1, 3, 5)
FETCH = 10  # 평가용으로 가져오는 청크 수 (조 단위로 중복 제거 후 순위 계산)


def load_golden() -> list[dict]:
    return [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()]


def ranked_articles(retrieve_fn, question: str) -> list[str]:
    seen, order = set(), []
    for d in retrieve_fn(question, FETCH):
        a = d.metadata["article"]
        if a not in seen:
            seen.add(a)
            order.append(a)
    return order


def evaluate(retrieve_fn=retrieve, name: str = "dense") -> dict:
    rows = []
    for item in load_golden():
        gold = item["gold_articles"]
        if not gold:  # 범위 밖 질문은 검색 지표에서 제외
            continue
        ranked = ranked_articles(retrieve_fn, item["question"])
        first = next((i for i, a in enumerate(ranked, 1) if a in gold), None)
        row = {
            "id": item["id"],
            "question": item["question"],
            "type": item["type"],
            "gold": gold,
            "top": ranked[:5],
            "rr": 1 / first if first else 0.0,
        }
        for k in KS:
            top = set(ranked[:k])
            row[f"hit@{k}"] = int(bool(top & set(gold)))
            row[f"recall@{k}"] = len(top & set(gold)) / len(gold)
        rows.append(row)

    n = len(rows)
    summary = {"method": name, "n": n, "MRR": round(sum(r["rr"] for r in rows) / n, 3)}
    for k in KS:
        summary[f"Hit@{k}"] = round(sum(r[f"hit@{k}"] for r in rows) / n, 3)
        summary[f"Recall@{k}"] = round(sum(r[f"recall@{k}"] for r in rows) / n, 3)
    return {"summary": summary, "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="dense")
    ap.add_argument("--method", default="dense", choices=["dense", "bm25", "hybrid", "rerank"])
    ap.add_argument("--multi-query", action="store_true", help="hybrid/rerank의 1차 검색에 Multi Query 적용")
    ap.add_argument("--tokenizer", default="kiwi", choices=["kiwi", "bigram"])
    ap.add_argument("--collection", default=None, help="비교할 Qdrant 컬렉션 (기본: baseline)")
    args = ap.parse_args()

    kw = {"collection": args.collection} if args.collection else {}
    if args.method == "dense":
        fn = partial(retrieve, **kw)
    elif args.method == "bm25":
        fn = partial(retrieve_bm25, mode=args.tokenizer, **kw)
    elif args.method == "hybrid":
        first = retrieve_multiquery if args.multi_query else retrieve_hybrid
        fn = partial(first, mode=args.tokenizer, **kw)
    else:
        fn = partial(retrieve_reranked, mode=args.tokenizer, multi_query=args.multi_query, **kw)
    res = evaluate(fn, name=args.name)
    out = ROOT / "results" / f"{args.name}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(res["summary"], ensure_ascii=False))
    print("\nTop-5 안에 정답이 없는 질문:")
    for r in res["rows"]:
        if not r["hit@5"]:
            print(f" - [{r['id']}] {r['question']} | 정답 {r['gold']} | 검색 {r['top']}")
    print("\nTop-1이 아닌 질문(순위 낮음):")
    for r in res["rows"]:
        if r["hit@5"] and not r["hit@1"]:
            print(f" - [{r['id']}] {r['question']} | 정답 {r['gold']} | 검색 {r['top']}")
    print("\n저장:", out)


if __name__ == "__main__":
    main()
