import json
import re

from common.ai_model import get_llm_model
from common.config import MODEL
from rag.cache import cached, llm_call_guard, log_usage
from rag.retriever import COLLECTION, Retrieved, retrieve_hybrid, retrieve_multiquery

POOL = 15  # 재정렬할 후보 수 (1차 검색 Top-N)
MAX_CHARS = 400  # LLM에 보여줄 후보당 최대 글자 수 (크레딧 절약을 위해 600 -> 400)

SYSTEM = """당신은 법률 검색 결과를 재정렬하는 평가자입니다.
질문과 후보 조문들을 보고, 각 후보가 질문에 '직접' 답하는 근거를 담고 있는 정도를 0~10점으로 매기세요.
- 10: 질문에 대한 답이 그대로 들어 있음
- 5: 관련은 있으나 답의 일부이거나 간접적
- 0: 단어만 겹칠 뿐 질문과 무관
후보의 id와 점수만 JSON으로 출력하세요. 형식: {"scores": [{"id": 1, "score": 7}, ...]}"""


def _format(docs: list[Retrieved]) -> str:
    return "\n\n".join(f"[id={i}] {d.text[:MAX_CHARS]}" for i, d in enumerate(docs, 1))


def llm_scores(question: str, docs: list[Retrieved]) -> list[float]:
    key = [SYSTEM, MAX_CHARS, MODEL, question, [d.text[:MAX_CHARS] for d in docs]]
    return cached("rerank", key, lambda: _llm_scores(question, docs)) or []


def _llm_scores(question: str, docs: list[Retrieved]) -> list[float] | None:
    llm_call_guard()
    llm = get_llm_model(max_tokens=800)
    resp = llm.invoke([("system", SYSTEM), ("human", f"[질문]\n{question}\n\n[후보 조문]\n{_format(docs)}")])
    log_usage("rerank", resp)
    m = re.search(r"\{.*\}", resp.content, re.S)
    scores = [0.0] * len(docs)
    try:
        for s in json.loads(m.group(0))["scores"]:
            scores[int(s["id"]) - 1] = float(s["score"])
    except (AttributeError, KeyError, ValueError, IndexError, json.JSONDecodeError):
        return None  # 파싱 실패는 캐시하지 않고, 호출자는 1차 순서를 유지
    return scores


def rerank(question: str, docs: list[Retrieved]) -> list[Retrieved]:
    scores = llm_scores(question, docs)
    if not scores:
        return docs
    # 점수 내림차순, 동점은 1차 검색 순위 유지(sorted는 안정 정렬)
    order = sorted(range(len(docs)), key=lambda i: -scores[i])
    return [Retrieved(docs[i].text, scores[i], docs[i].metadata) for i in order]


def retrieve_reranked(
    query: str, k: int = 5, collection: str = COLLECTION, mode: str = "kiwi", pool: int = POOL, multi_query: bool = False
) -> list[Retrieved]:
    first_stage = retrieve_multiquery if multi_query else retrieve_hybrid
    candidates = first_stage(query, max(pool, k), collection, mode)
    return rerank(query, candidates)[:k]
