"""MonoRouter API 크레딧 잔액과 지난 조회 이후의 변화량을 보여준다 (크레딧 소모 없는 조회).

사용: uv run python scripts/check_credits.py
- LLM_API_KEY는 .env에서만 읽는다. 키·계정 라벨 등 식별 정보는 출력하지 않는다.
- 이전 조회 값을 .cache/credits.json 에 저장해, 작업 전후로 실행하면 그 작업이 쓴 크레딧을 알 수 있다.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
URL = "https://monogpt.kr/api/monorouter/v1/credits"
SNAP = Path(__file__).resolve().parent.parent / ".cache" / "credits.json"


def main():
    key = os.getenv("LLM_API_KEY")
    if not key:
        sys.exit("LLM_API_KEY가 .env에 없습니다.")
    req = urllib.request.Request(URL, headers={"Authorization": f"Bearer {key}", "User-Agent": "Mozilla/5.0"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=20))
    except Exception as e:  # noqa: BLE001  오류 내용에 키가 섞일 일은 없지만 종류만 알린다
        sys.exit(f"잔액 조회 실패: {type(e).__name__}")

    now = {k: d.get(k) for k in ("max_credits", "used_credits", "reserved_credits", "remaining_credits")}
    print(f"남은 크레딧: {now['remaining_credits']:,}   (사용 {now['used_credits']:,} / 한도 {now['max_credits']:,})")

    try:
        prev = json.loads(SNAP.read_text(encoding="utf-8"))
        delta = prev["used_credits"] - now["used_credits"]
        if delta:
            print(f"지난 조회 이후 사용: {-delta:,} 크레딧")
        else:
            print("지난 조회 이후 변화 없음")
    except (OSError, ValueError, KeyError):
        print("(이전 조회 기록이 없어 변화량은 다음 조회부터 보여요)")
    try:
        SNAP.parent.mkdir(parents=True, exist_ok=True)
        SNAP.write_text(json.dumps(now), encoding="utf-8")
    except OSError:
        pass


if __name__ == "__main__":
    main()
