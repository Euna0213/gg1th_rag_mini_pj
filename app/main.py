import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from qdrant_client.models import FieldCondition, Filter, MatchValue

from common.qdrant import get_qdrant_client
from rag.pipeline import answer_question
from rag.vectorstore import COLLECTION

log = logging.getLogger("app")
STATIC = Path(__file__).resolve().parent / "static"
PARAGRAPH_ORDER = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

app = FastAPI(title="AI 법률 길잡이")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    regenerate: bool = False  # True: 저장된 답변을 무시하고 새로 생성 (LLM 호출이 발생한다)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/ask")
def ask(req: AskRequest):
    """RFP 계약: {question} -> {answer, sources:[{article, content}]}"""
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="질문을 입력해 주세요.")
    try:
        return answer_question(question, refresh=req.regenerate)
    except Exception as e:  # noqa: BLE001  내부 오류 내용은 로그에만 남기고 사용자에게는 원인 범주만 알린다
        log.exception("answer_question failed")
        if "insufficient_credits" in str(e) or "quota" in str(e).lower():
            raise HTTPException(status_code=503, detail="API 크레딧이 부족해 답변을 만들 수 없어요.")
        if "RAG_MAX_LLM_CALLS" in str(e):
            raise HTTPException(status_code=503, detail="LLM 호출 상한에 도달했어요.")
        raise HTTPException(status_code=502, detail="답변을 만드는 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요.")


@app.get("/api/article")
def article(article: str):
    """조 하나의 원문 전체(항 단위로 나뉜 청크를 이어 붙임). LLM·임베딩 호출 없음."""
    points, _ = get_qdrant_client().scroll(
        COLLECTION,
        scroll_filter=Filter(must=[FieldCondition(key="article", match=MatchValue(value=article))]),
        limit=100,
        with_payload=True,
        with_vectors=False,
    )
    if not points:
        raise HTTPException(status_code=404, detail="해당 조문을 찾을 수 없어요.")

    def order(p):
        para = p.payload.get("paragraph") or ""
        return PARAGRAPH_ORDER.index(para) if para in PARAGRAPH_ORDER else -1

    points.sort(key=order)
    first = points[0].payload
    title = f"{first['article']}({first['article_title']})"
    parts = []
    for i, p in enumerate(points):
        body = p.payload["text"].split("\n", 1)[-1]  # 첫 줄은 "[제N장 …]" 문맥 헤더
        if i > 0 and body.startswith(title):  # 항 청크마다 붙인 조 제목은 한 번만 보여준다
            body = body[len(title):].lstrip()
        parts.append(body)
    return {
        "article": first["article"],
        "title": first["article_title"],
        "chapter": first.get("chapter"),
        "section": first.get("section"),
        "text": "\n".join(parts),
    }
