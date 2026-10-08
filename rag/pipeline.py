from common.ai_model import get_llm_model
from common.config import MODEL
from rag.cache import cached, llm_call_guard, log_usage
from rag.reranker import retrieve_reranked
from rag.retriever import Retrieved

# 최종 검색 구성: Hybrid(BM25 kiwi + Dense, RRF) 후보 15개 -> LLM Rerank -> 상위 k개
RETRIEVAL = {"mode": "kiwi", "multi_query": False}

SYSTEM_PROMPT = """당신은 대한민국 「인공지능 발전과 신뢰 기반 조성 등에 관한 기본법」을 쉽게 설명하는 도우미입니다.
반드시 아래 [참고 조문]에 있는 내용만 근거로 답하세요.
- 참고 조문에 답이 없으면 "제공된 조문에서는 확인할 수 없습니다."라고 답하세요.
- 일반 지식이나 추측으로 답하지 마세요.
- 답변 중 근거가 되는 조문은 '제N조'처럼 번호를 밝히세요.
- 법을 잘 모르는 사람도 이해할 수 있게 쉬운 말로 설명하세요."""


def build_context(docs: list[Retrieved]) -> str:
    return "\n\n".join(f"[{i}] {d.text}" for i, d in enumerate(docs, 1))


def answer_question(question: str, k: int = 5, refresh: bool = False) -> dict:
    docs = retrieve_reranked(question, k, **RETRIEVAL)
    human = f"[참고 조문]\n{build_context(docs)}\n\n[질문]\n{question}"

    def generate() -> str:
        llm_call_guard()
        resp = get_llm_model(max_tokens=1024).invoke([("system", SYSTEM_PROMPT), ("human", human)])
        log_usage("answer", resp)
        return resp.content

    answer = cached("answer", [SYSTEM_PROMPT, MODEL, human], generate, refresh=refresh)
    return {
        "answer": answer,
        "sources": [{"article": d.label, "content": d.text} for d in docs],
    }
