import re
from pathlib import Path

from docling.document_converter import DocumentConverter

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "ai_basic_law"

SKIP_LABELS = {"page_header", "page_footer"}
KEEP_HEADER = re.compile(r"^(제\d+(장|절)|부칙)")
NOISE = re.compile(r"^(\[시행|과학기술정보통신부 \()")


def find_law_pdf(data_dir: Path = DATA_DIR) -> Path:
    pdfs = sorted(data_dir.glob("*기본법(법률)*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"기본법 PDF가 없습니다: {data_dir}")
    return pdfs[0]


def load_law_lines(path: Path | None = None) -> list[str]:
    """Docling으로 PDF를 읽어 원문 번호(호·목 포함)를 보존한 줄 목록을 반환한다.

    export_to_markdown()은 목록 번호를 다시 매겨 호/목이 깨지므로
    항목(doc.texts) 단위로 읽고, 쪽 머리글/바닥글과 반복되는 표제는 제거한다.
    """
    path = path or find_law_pdf()
    doc = DocumentConverter().convert(str(path)).document

    lines = []
    for item in doc.texts:
        label = item.label.value
        text = item.text.strip()
        if label in SKIP_LABELS or not text or NOISE.match(text):
            continue
        if label == "section_header" and not KEEP_HEADER.match(text):
            continue
        marker = getattr(item, "marker", "") or ""
        lines.append(f"{marker} {text}".strip() if marker else text)
    return lines


def load_law_text(path: Path | None = None) -> str:
    return "\n".join(load_law_lines(path))
