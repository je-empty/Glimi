# Elastic Memory — 어떤 컨텍스트 윈도우에도 맞는 메모리

[← README](../README.ko.md)

로컬 모델은 윈도우가 작다(Ollama 4096). 전체 Glimi 프롬프트 — 캐릭터 시스템 + L0–L5 메모리 + 대화 히스토리 — 는 종종 그걸 넘겨 앞쪽 토큰이 잘린다. `Elastic Memory`(`glimi/context_budget.py`)가 이걸 관리한다:

- **메모리가 윈도우에 맞춰 스케일** — 기준 `num_ctx` 8192; 4096 이면 줄이고, 16384 면 회상이 두 배.
- **Best-effort fit** — 가장 오래된 대화부터 자르고, 시스템 프롬프트마저 넘치면 warning 을 남긴다.
- **백엔드 무관** — Claude 든 뭐든 동작하지만, 주로 로컬용(클라우드 200k 는 거의 필요 없음).
- **커뮤니티별·하드웨어 인지** — `community/core/system_specs.py` 가 RAM/VRAM 을 읽어 Low 4096 / Mid 8192 / High 16384 티어를 제안하고, 품질 슬라이더처럼 config 에 기록한다.

같은 에이전트가 4096·8192·16384 어디서든 성격 손실 없이 동작한다. Glimi 는 윈도우 크기를 직접 토큰 버짓으로 삼아 프롬프트를 그 안에 유지한다 — CrewAI·Letta·OpenAI Agents SDK·AutoGen·LangGraph 도 히스토리를 자르지만 목표 크기 기준은 아니다. Ollama 의 VRAM 기반 컨텍스트 조절 이슈는 미해결 상태다.
