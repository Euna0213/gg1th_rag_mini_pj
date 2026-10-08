import re
from dataclasses import dataclass, field

from rag.loader import load_law_lines

CHAPTER = re.compile(r"^(제\d+장)\s*(.*)")
SECTION = re.compile(r"^(제\d+절)\s*(.*)")
ARTICLE = re.compile(r"^제(\d+)조(?:의(\d+))?\(([^)]*)\)\s*(.*)")
PARAGRAPH = re.compile(r"^([①-⑳])")
ITEM = re.compile(r"^(\d+(?:의\d+)?)\.\s")  # 호: 1. 2. 2의2.
APPENDIX = re.compile(r"^부칙")

# 조 전체가 이 길이 이하면 조 단위 1청크, 넘으면 항 단위로 분할
MAX_ARTICLE_CHARS = 700


@dataclass
class Chunk:
    text: str
    metadata: dict = field(default_factory=dict)


def _article_label(no: str, branch: str | None) -> str:
    return f"제{no}조" + (f"의{branch}" if branch else "")


def _parse_articles(lines: list[str]) -> list[dict]:
    """줄 목록을 조 단위 dict(장/절/조/본문 줄)로 묶는다."""
    articles, cur = [], None
    chapter = section = None
    for line in lines:
        if m := CHAPTER.match(line):
            chapter, section = f"{m[1]} {m[2]}".strip(), None
            cur = None
        elif m := SECTION.match(line):
            section = f"{m[1]} {m[2]}".strip()
            cur = None
        elif m := ARTICLE.match(line):
            cur = {
                "chapter": chapter,
                "section": section,
                "article": _article_label(m[1], m[2]),
                "article_title": m[3],
                "lines": [line],
            }
            articles.append(cur)
        elif APPENDIX.match(line):
            cur = {
                "chapter": "부칙",
                "section": None,
                "article": "부칙",
                "article_title": "부칙",
                "lines": [line],
            }
            articles.append(cur)
        elif cur:
            cur["lines"].append(line)
    return articles


def _split_paragraphs(lines: list[str]) -> list[tuple[str | None, str]]:
    """조 본문 줄을 항(①②…) 단위로 나눈다. 첫 줄이 '제N조(제목) ①…'이면 ①도 항으로 본다."""
    parts: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in lines:
        rest = m[4] if (m := ARTICLE.match(line)) else line
        if rest and PARAGRAPH.match(rest):
            parts.append((rest[0], [line]))
        else:
            parts[-1][1].append(line)
    return [(p, "\n".join(ls)) for p, ls in parts if ls]


def _split_items(lines: list[str]) -> list[tuple[str, str]]:
    """정의 조항처럼 항 없이 호(1. 2. …)로 이어진 조를 호 단위로 나눈다.

    목(가. 나. …)은 바로 앞 호에 붙는다. 반환: [(도입문, ''), ('4호', '4. …가. … 나. …'), …]
    """
    intro, items = [], []
    for line in lines:
        if m := ITEM.match(line):
            items.append([f"{m[1]}호", [line]])
        elif items:
            items[-1][1].append(line)
        else:
            intro.append(line)
    return " ".join(intro), [(no, "\n".join(ls)) for no, ls in items]


def chunk_law(lines: list[str] | None = None, split_definitions: bool = False) -> list[Chunk]:
    lines = lines if lines is not None else load_law_lines()
    chunks: list[Chunk] = []
    for art in _parse_articles(lines):
        body = "\n".join(art["lines"])
        base = {
            "chapter": art["chapter"],
            "section": art["section"],
            "article": art["article"],
            "article_title": art["article_title"],
        }
        header = f"[{art['chapter']}" + (f" > {art['section']}" if art["section"] else "") + "]"
        title = f"{art['article']}({art['article_title']})"

        if split_definitions and art["article"] == "제2조":
            # 개선: 정의 19개가 한 청크로 뭉치면 임베딩이 희석되므로 호 단위로 분할
            intro, items = _split_items(art["lines"])
            for no, text in items:
                chunks.append(Chunk(f"{header}\n{intro}\n{text}", {**base, "paragraph": no}))
            continue

        if len(body) <= MAX_ARTICLE_CHARS:
            chunks.append(Chunk(f"{header}\n{body}", {**base, "paragraph": None}))
            continue
        # 긴 조: 항 단위 분할. 조 제목이 없는 항 청크에는 제목을 붙여 문맥을 유지한다
        for para, text in _split_paragraphs(art["lines"]):
            if not text.startswith(art["article"]):
                text = f"{title} {text}"
            chunks.append(Chunk(f"{header}\n{text}", {**base, "paragraph": para}))
    return chunks
