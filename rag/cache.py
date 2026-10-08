"""LLM·임베딩 호출 결과를 디스크에 저장해, 같은 입력이면 API를 다시 호출하지 않는다.

- 저장 위치: <프로젝트>/.cache/<namespace>/<해시>.json  (.gitignore 대상)
- 키: 호출을 결정하는 모든 입력(프롬프트, 모델 이름, 질문, 컨텍스트 등)의 해시.
  프롬프트나 모델이 바뀌면 키가 달라지므로 낡은 결과를 쓰지 않는다.
- 비활성화: 환경변수 RAG_CACHE=0. 같은 설정의 실행 간 흔들림(재현성)을 재고 싶을 때 쓴다.
- 실패한 결과(None)는 저장하지 않는다. 호출자는 유효한 결과만 돌려주면 된다.
"""
import hashlib
import json
import os
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"


def enabled() -> bool:
    return os.getenv("RAG_CACHE", "1") != "0"


def _path(namespace: str, key_parts) -> Path:
    raw = json.dumps(key_parts, ensure_ascii=False, sort_keys=True, default=str)
    return CACHE_DIR / namespace / (hashlib.sha256(raw.encode("utf-8")).hexdigest() + ".json")


def cached(namespace: str, key_parts, compute, refresh: bool = False):
    """캐시에 있으면 그 값을, 없으면 compute()를 호출해 유효하면(None이 아니면) 저장한다.

    refresh=True 이면 저장된 값을 무시하고 새로 계산해 덮어쓴다 (챗봇의 '다시 생성하기')."""
    if not enabled():
        return compute()
    path = _path(namespace, key_parts)
    if not refresh:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass  # 없거나 깨진 파일이면 새로 계산
    value = compute()
    if value is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)  # 쓰는 도중 중단돼도 깨진 파일이 남지 않게
        except OSError:
            pass  # 캐시 저장 실패는 결과에 영향을 주지 않는다
    return value


# ------------------------------------------------------------ 호출 상한 · 사용량 기록
_calls = 0
USAGE_LOG = CACHE_DIR / "usage.jsonl"


def llm_call_guard() -> None:
    """LLM을 실제로 호출하기 직전에 부른다. RAG_MAX_LLM_CALLS(>0)를 넘으면 중단해 크레딧 낭비를 막는다."""
    global _calls
    limit = int(os.getenv("RAG_MAX_LLM_CALLS", "0"))
    if limit and _calls >= limit:
        raise RuntimeError(f"RAG_MAX_LLM_CALLS={limit} 에 도달해 LLM 호출을 중단합니다.")
    _calls += 1


def log_usage(tag: str, resp) -> None:
    """응답의 토큰 사용량을 .cache/usage.jsonl 에 한 줄로 남긴다 (캐시 적중 시에는 호출이 없어 기록되지 않는다)."""
    meta = getattr(resp, "usage_metadata", None) or {}
    try:
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"tag": tag, "in": meta.get("input_tokens", 0), "out": meta.get("output_tokens", 0)}) + "\n")
    except OSError:
        pass


def usage_summary() -> dict:
    totals: dict[str, dict] = {}
    if USAGE_LOG.exists():
        for line in USAGE_LOG.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            t = totals.setdefault(r["tag"], {"calls": 0, "in": 0, "out": 0})
            t["calls"] += 1
            t["in"] += r["in"]
            t["out"] += r["out"]
    return totals


if __name__ == "__main__":  # uv run python -m rag.cache  -> 지금까지의 사용량 요약
    for tag, t in usage_summary().items():
        print(f"{tag:10s} calls={t['calls']:4d}  input_tokens={t['in']:8d}  output_tokens={t['out']:7d}")
