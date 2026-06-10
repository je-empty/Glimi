"""
Ollama 백엔드 — 로컬 LLM 추론 엔진 (HTTP API).

환경변수:
  OLLAMA_HOST          — Ollama 서버 base URL (기본 http://localhost:11434)
  GLIMI_OLLAMA_MODEL   — 모든 호출의 model 인자 override (Claude 모델명 매핑 회피용)

지원:
  - `/api/chat` (system + user messages)
  - 스트리밍 (`stream_lines`) — Ollama NDJSON 줄단위 파싱
  - prompt caching 없음 (Ollama 가 자체 KV cache 일부 활용)

의존성: stdlib only (urllib.request).

운영 노트:
  GGUF 파일 (mradermacher 등 imatrix 양자화) 은 `ollama create <tag> -f Modelfile` 로
  먼저 임포트해야 함. 그 후 `GLIMI_OLLAMA_MODEL=<tag>` 로 지정.
"""
from __future__ import annotations

import json
import os
from typing import Iterator
from urllib import error as urlerror
from urllib import request as urlrequest

from .base import LLMBackend, LLMResponse


_DEFAULT_HOST = "http://localhost:11434"


def _base_url() -> str:
    return os.environ.get("OLLAMA_HOST", _DEFAULT_HOST).rstrip("/")


def _resolve_model(model: str) -> str:
    """env override 가 있으면 그것 우선. Claude 모델명이 그대로 들어오는 경로 회피용."""
    override = os.environ.get("GLIMI_OLLAMA_MODEL", "").strip()
    return override or model


def _think_setting():
    """`think` 필드 값 결정 (GLIMI_OLLAMA_THINK env).

    추론(thinking) 모델은 기본적으로 추론 토큰을 먼저 뱉는데, num_predict 가 작으면
    추론이 예산을 다 먹고 실제 답이 빈 채로 잘림 (관찰됨). 채팅 sim 엔 추론 불필요 →
    기본 think=False 로 끈다.

    반환: True | False (payload 에 think 키 추가) | None (키 생략 — 모델 기본동작)
      - unset / "false" / "0" / "off" → False (기본, 빠름)
      - "true" / "1" / "on"          → True
      - "auto"                       → None (비추론 모델 호환용 escape hatch)
    """
    v = os.environ.get("GLIMI_OLLAMA_THINK", "").strip().lower()
    if v in ("true", "1", "on"):
        return True
    if v == "auto":
        return None
    return False


def _post_json(url: str, body: dict, *, timeout: float, stream: bool = False):
    """urllib POST + JSON. stream=True 면 response 객체 그대로 반환 (호출자가 line-iter)."""
    data = json.dumps(body).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urlrequest.urlopen(req, timeout=timeout)  # noqa: S310 (localhost 신뢰)


class OllamaBackend(LLMBackend):
    name = "ollama"

    def available(self) -> bool:
        try:
            with urlrequest.urlopen(f"{_base_url()}/api/tags", timeout=2) as r:  # noqa: S310
                return 200 <= r.status < 300
        except Exception:
            return False

    def generate(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 2048,
        timeout: int = 60,
        cacheable_system: bool = False,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        api_model = _resolve_model(model)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        payload = {
            "model": api_model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        _think = _think_setting()
        if _think is not None:
            payload["think"] = _think

        try:
            with _post_json(f"{_base_url()}/api/chat", payload, timeout=timeout) as r:
                body = r.read().decode("utf-8", errors="replace")
            data = json.loads(body)
            text = (data.get("message") or {}).get("content", "").strip()
            return LLMResponse(
                text=text,
                model=api_model,
                input_tokens=int(data.get("prompt_eval_count", 0) or 0),
                output_tokens=int(data.get("eval_count", 0) or 0),
            )
        except urlerror.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                err_body = ""
            return LLMResponse(
                text="", model=api_model,
                error=f"ollama: http={e.code} {err_body or e.reason}",
            )
        except urlerror.URLError as e:
            return LLMResponse(
                text="", model=api_model,
                error=f"ollama: connection: {e.reason}",
            )
        except Exception as e:
            return LLMResponse(
                text="", model=api_model,
                error=f"ollama: {type(e).__name__}: {str(e)[:200]}",
            )

    def stream_lines(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 2048,
        timeout: int = 120,
        cacheable_system: bool = False,
        temperature: float = 0.7,
        **kwargs,
    ) -> Iterator[str]:
        """Ollama stream=true 응답은 NDJSON. content 청크 누적 후 \\n 단위 split → yield."""
        api_model = _resolve_model(model)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        payload = {
            "model": api_model,
            "messages": messages,
            "stream": True,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        _think = _think_setting()
        if _think is not None:
            payload["think"] = _think

        buf = ""
        try:
            with _post_json(f"{_base_url()}/api/chat", payload, timeout=timeout, stream=True) as r:
                for raw in r:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    chunk = (evt.get("message") or {}).get("content", "")
                    if not chunk:
                        continue
                    buf += chunk
                    while "\n" in buf:
                        out, buf = buf.split("\n", 1)
                        yield out
            if buf:
                yield buf
        except Exception:
            return
