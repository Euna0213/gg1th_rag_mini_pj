"""국가법령정보 공동활용 Open API로 인공지능기본법 본문(JSON)을 내려받는다.

사용: uv run python scripts/fetch_law_api.py
필요: .env 의 LAW_OC (키 값은 출력하지 않는다)
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE = "https://www.law.go.kr/DRF"
LAW_NAME = "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법"
OUT = Path(__file__).resolve().parent.parent / "data" / "ai_basic_law" / "law_api.json"


def call(endpoint: str, **params) -> str:
    oc = os.getenv("LAW_OC")
    if not oc:
        sys.exit("LAW_OC가 .env에 없습니다.")
    url = f"{BASE}/{endpoint}?" + urllib.parse.urlencode({"OC": oc, "type": "JSON", **params})
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def parse_json(text: str, what: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        sys.exit(f"{what}: JSON이 아닌 응답입니다 (IP 미등록/승인 대기 가능). 앞부분: {text[:200]!r}")


def main():
    search = parse_json(call("lawSearch.do", target="law", query=LAW_NAME), "lawSearch")
    print("검색 응답 키:", list(search.keys()))
    laws = search.get("LawSearch", {}).get("law", [])
    laws = [laws] if isinstance(laws, dict) else laws
    for law in laws:
        print(" -", law.get("법령명한글"), "| MST", law.get("법령일련번호"), "| 시행", law.get("시행일자"))
    match = next((l for l in laws if l.get("법령명한글") == LAW_NAME), None)
    if not match:
        sys.exit("정확히 일치하는 법령을 찾지 못했습니다. 위 목록을 확인하세요.")

    body = parse_json(call("lawService.do", target="law", MST=match["법령일련번호"]), "lawService")
    OUT.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    print("저장:", OUT, f"({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
