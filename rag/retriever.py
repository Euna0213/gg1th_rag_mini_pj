import re
from dataclasses import dataclass
from functools import lru_cache

from rank_bm25 import BM25Okapi

from common.ai_model import get_llm_model
from common.config import MODEL
from rag.cache import cached, llm_call_guard, log_usage
from common.qdrant import get_qdrant_client
from rag.vectorstore import COLLECTION, search_dense


@dataclass
class Retrieved:
    text: str
    score: float
    metadata: dict

    @property
    def label(self) -> str:
        m = self.metadata
        label = f"{m['article']}({m['article_title']})"
        return f"{label} {m['paragraph']}" if m.get("paragraph") else label


def retrieve(query: str, k: int = 5, collection: str = COLLECTION) -> list[Retrieved]:
    """baseline: Dense Retrieval (질문 임베딩 -> Qdrant 코사인 유사도 Top-K)."""
    hits = search_dense(query, k, collection)
    return [
        Retrieved(p.payload["text"], p.score, {k_: v for k_, v in p.payload.items() if k_ != "text"})
        for p in hits
    ]


# ---------------------------------------------------------------- BM25 / Hybrid
@lru_cache(maxsize=1)
def _kiwi():
    from kiwipiepy import Kiwi

    return Kiwi()


def tokenize(text: str, mode: str = "kiwi") -> list[str]:
    """kiwi: 한국어 형태소 분석(명사·동사어근·외래어·숫자만). bigram: 형태소 분석 없이 글자 2-gram."""
    if mode == "kiwi":
        keep = ("N", "V", "XR", "SL", "SN")
        return [t.form for t in _kiwi().tokenize(text) if t.tag.startswith(keep)]
    words = re.findall(r"[가-힣A-Za-z0-9]+", text)
    return [w[i : i + 2] for w in words for i in range(max(len(w) - 1, 1))]


@lru_cache(maxsize=8)
def _bm25_index(collection: str, mode: str):
    """Qdrant에 저장된 청크 텍스트로 BM25 인덱스를 만든다 (Docling 재실행 불필요)."""
    client = get_qdrant_client()
    points, _ = client.scroll(collection, limit=1000, with_payload=True, with_vectors=False)
    docs = [(p.payload["text"], {k: v for k, v in p.payload.items() if k != "text"}) for p in points]
    return BM25Okapi([tokenize(t, mode) for t, _ in docs]), docs


def retrieve_bm25(query: str, k: int = 5, collection: str = COLLECTION, mode: str = "kiwi") -> list[Retrieved]:
    bm25, docs = _bm25_index(collection, mode)
    scores = bm25.get_scores(tokenize(query, mode))
    top = sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)[:k]
    return [Retrieved(docs[i][0], float(scores[i]), docs[i][1]) for i in top]


def _chunk_key(d: Retrieved) -> tuple:
    return (d.metadata["article"], d.metadata.get("paragraph"))


def retrieve_hybrid(
    query: str, k: int = 5, collection: str = COLLECTION, mode: str = "kiwi", pool: int = 20, rrf_k: int = 60
) -> list[Retrieved]:
    """Dense + BM25 결과를 RRF(Reciprocal Rank Fusion)로 합친다: score = Σ 1/(rrf_k + rank)."""
    fused: dict[tuple, float] = {}
    keep: dict[tuple, Retrieved] = {}
    for results in (retrieve(query, pool, collection), retrieve_bm25(query, pool, collection, mode)):
        for rank, d in enumerate(results, 1):
            key = _chunk_key(d)
            fused[key] = fused.get(key, 0.0) + 1.0 / (rrf_k + rank)
            keep.setdefault(key, d)
    ranked = sorted(fused, key=fused.get, reverse=True)[:k]
    return [Retrieved(keep[key].text, fused[key], keep[key].metadata) for key in ranked]


# ---------------------------------------------------------------- Multi Query
EXPAND_PROMPT = """다음은 「인공지능 발전과 신뢰 기반 조성 등에 관한 기본법」에 대한 사용자의 질문입니다.
같은 의미를 다른 표현으로 바꾼 검색용 질문 {n}개를 만드세요.
- 법조문에 쓰일 법한 용어(예: 의무, 정의, 대상, 요건)로 바꾼 표현을 포함하세요.
- 질문의 의미를 바꾸거나 새로운 사실을 추가하지 마세요.
JSON 문자열 배열만 출력하세요. 예: ["...", "...", "..."]

질문: {q}"""


@lru_cache(maxsize=256)
def expand_queries(query: str, n: int = 3) -> tuple[str, ...]:
    """Multi Query: LLM으로 질문을 n개의 다른 표현으로 바꾼다. 실패하면 빈 튜플(원 질문만 사용)."""
    found = cached("expand", [EXPAND_PROMPT, MODEL, query, n], lambda: _expand(query, n))
    return tuple(found or ())


def _expand(query: str, n: int) -> list[str] | None:
    import json

    llm_call_guard()
    resp = get_llm_model(max_tokens=300).invoke(EXPAND_PROMPT.format(n=n, q=query))
    log_usage("expand", resp)
    m = re.search(r"\[.*\]", resp.content, re.S)
    try:
        return [str(x) for x in json.loads(m.group(0))[:n]]
    except (AttributeError, ValueError):
        return None


def retrieve_multiquery(
    query: str, k: int = 5, collection: str = COLLECTION, mode: str = "kiwi", pool: int = 20, n: int = 3, rrf_k: int = 60
) -> list[Retrieved]:
    """원 질문 + 변형 질문들 각각에 Hybrid 검색을 하고 결과를 RRF로 합친다."""
    fused: dict[tuple, float] = {}
    keep: dict[tuple, Retrieved] = {}
    for q in (query, *expand_queries(query, n)):
        for rank, d in enumerate(retrieve_hybrid(q, pool, collection, mode), 1):
            key = _chunk_key(d)
            fused[key] = fused.get(key, 0.0) + 1.0 / (rrf_k + rank)
            keep.setdefault(key, d)
    ranked = sorted(fused, key=fused.get, reverse=True)[:k]
    return [Retrieved(keep[key].text, fused[key], keep[key].metadata) for key in ranked]
