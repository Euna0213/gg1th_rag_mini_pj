"""답변 품질 평가: 정답성 · 근거 충실성 · 환각.

크레딧을 아끼기 위한 설계
  1) 규칙 검사(무료): 범위 밖 질문의 거절 여부, 답변이 인용한 '제N조'가 실제 검색 결과(sources)에 있는지
  2) LLM 판정(유료, 질문당 1회): 정답성·근거 충실성·환각을 한 번의 호출로 JSON 채점
  - 모든 호출은 디스크 캐시를 거치므로 같은 평가를 다시 돌려도 추가 비용이 없다.
  - --no-judge : 규칙 검사만 (판정 호출 0회)   --limit N : 앞의 N문항만
  - RAG_MAX_LLM_CALLS=N : 이 프로세스의 LLM 호출 상한

사용: uv run python -m eval.evaluate_answers [--limit 5] [--no-judge]
"""
import argparse
import json
import re
from pathlib import Path

from common.ai_model import get_llm_model
from common.config import MODEL
from common.qdrant import get_qdrant_client
from rag.cache import cached, llm_call_guard, log_usage
from rag.pipeline import answer_question
from rag.vectorstore import COLLECTION

from eval.evaluate import load_golden

OUT = Path(__file__).resolve().parent / "results" / "answers.json"
CITE = re.compile(r"제\d+조(?:의\d+)?")
REFUSAL = "확인할 수 없"
GOLD_CHARS = 500
SRC_CHARS = 350

JUDGE_PROMPT = """법률 QA 답변을 채점하세요. [정답 조문]은 이 질문의 정답이 들어 있는 조문, [제공된 근거]는 답변이 참고한 조문입니다.
각 항목을 0~2점으로 채점합니다.
- correct: 2=정답 조문의 내용과 일치, 1=일부만 맞거나 불완전, 0=틀렸거나 '확인할 수 없다'고만 답함
- faithful: 2=답변의 모든 주장이 [제공된 근거]에 있음, 1=일부 주장이 근거에 없음, 0=대부분 근거에 없음
- hallucination: 근거에 없는 사실·조항·수치를 지어냈으면 1, 아니면 0
설명 없이 JSON 한 줄만 출력: {"correct": 0, "faithful": 0, "hallucination": 0}"""


def gold_texts() -> dict[str, str]:
    """정답 조문 본문 (Qdrant 조회, 크레딧 소모 없음)."""
    points, _ = get_qdrant_client().scroll(COLLECTION, limit=1000, with_payload=True, with_vectors=False)
    by_article: dict[str, list[str]] = {}
    for p in points:
        by_article.setdefault(p.payload["article"], []).append(p.payload["text"])
    return {a: "\n".join(t) for a, t in by_article.items()}


def judge(question: str, answer: str, gold: str, sources: list[dict]) -> dict | None:
    src = "\n".join(f"- {s['content'][:SRC_CHARS]}" for s in sources)
    human = f"[질문]\n{question}\n\n[정답 조문]\n{gold[:GOLD_CHARS]}\n\n[제공된 근거]\n{src}\n\n[답변]\n{answer}"

    def call():
        llm_call_guard()
        try:
            resp = get_llm_model(max_tokens=600).invoke([("system", JUDGE_PROMPT), ("human", human)])
        except Exception as e:  # 출력 한도 초과(400)는 이 질문만 건너뛴다. 크레딧 소진(402) 등은 그대로 중단.
            if "max_tokens" in str(e):
                return None
            raise
        log_usage("judge", resp)
        m = re.search(r"\{.*\}", resp.content, re.S)
        try:
            d = json.loads(m.group(0))
            return {k: int(d[k]) for k in ("correct", "faithful", "hallucination")}
        except (AttributeError, KeyError, ValueError, json.JSONDecodeError):
            return None

    return cached("judge", [JUDGE_PROMPT, MODEL, human], call)


def citation_check(answer: str, sources: list[dict]) -> tuple[int, int]:
    """답변이 인용한 '제N조' 중 sources(제목 또는 본문)에서 확인되는 것의 (개수, 전체)."""
    cited = set(CITE.findall(answer))
    haystack = " ".join(s["article"] + " " + s["content"] for s in sources)
    ok = sum(1 for c in cited if c in haystack)
    return ok, len(cited)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-judge", action="store_true")
    args = ap.parse_args()

    items = load_golden()
    if args.limit:
        items = items[: args.limit]
    golds = {} if args.no_judge else gold_texts()

    rows = []
    for item in items:
        res = answer_question(item["question"])
        answer, sources = res["answer"], res["sources"]
        ok, total = citation_check(answer, sources)
        row = {
            "id": item["id"],
            "question": item["question"],
            "type": item["type"],
            "cite_ok": ok,
            "cite_total": total,
            "refused": REFUSAL in answer,
            "sources_top": [m.group(0) for src in sources if (m := CITE.match(src["article"]))],
            "answer": answer,
        }
        if item["gold_articles"]:  # 추가 비용 없는 부산물: 이 구성에서도 정답 조문이 검색되었나
            row["retrieval_hit"] = any(a in row["sources_top"] for a in item["gold_articles"])
        if not item["gold_articles"]:
            row["pass"] = row["refused"]  # 범위 밖: 거절해야 통과
        elif not args.no_judge:
            gold = "\n".join(golds.get(a, "") for a in item["gold_articles"])
            row["judge"] = judge(item["question"], answer, gold, sources)
        rows.append(row)
        print(f"[{item['id']}] cite {ok}/{total} refused={row['refused']} judge={row.get('judge')}")

    scored = [r for r in rows if r.get("judge")]
    n = len(scored)
    summary = {
        "n_judged": n,
        "correct_avg(0-2)": round(sum(r["judge"]["correct"] for r in scored) / n, 2) if n else None,
        "faithful_avg(0-2)": round(sum(r["judge"]["faithful"] for r in scored) / n, 2) if n else None,
        "hallucination_rate": round(sum(r["judge"]["hallucination"] for r in scored) / n, 3) if n else None,
        "citation_valid": f"{sum(r['cite_ok'] for r in rows)}/{sum(r['cite_total'] for r in rows)}",
        "retrieval_hit@5(이 구성)": f"{sum(r['retrieval_hit'] for r in rows if 'retrieval_hit' in r)}/{sum('retrieval_hit' in r for r in rows)}",
        "out_of_scope_refused": [r["pass"] for r in rows if "pass" in r],
    }
    OUT.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    print("저장:", OUT)


if __name__ == "__main__":
    main()
