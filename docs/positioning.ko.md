# Glimi 의 차별점

[← README](../README.ko.md)

Glimi Core 는 세션이 끊겨도 초기화되지 않는 에이전트 엔진이다. 요청마다 역할을 재생성하는 일반 도구와 달리, Glimi 는 압축·복원 단계를 생략한다. 각 에이전트는 자기 맥락·결정·사용자 취향·가치를 저장소에 보관한다. 모델을 바꿔도 같은 데이터를 따른다. 이 영속성은 **Glimi Workspace**(작업 팀), **Glimi Community**(기억하는 친구) 로 구현된다. 두 앱은 Core 예시이며 같은 엔진을 쓴다.

기존 오픈소스 프레임워크(LangChain/LangGraph, AutoGen, CrewAI, OpenAI Agents SDK, Letta 등)는 에이전트를 **task** 단위로 실행 후 폐기한다. Letta 에는 영속 메모리가 있고, Stanford Generative Agents·AI Town 에서는 자율 군집이 있다. Glimi 는 이 조각들을 **단일 pip 런타임**으로 묶는다. 핵심 구성은 다음 두 가지다.

**1. 컨텍스트 윈도우 맞춤 메모리 (Elastic Memory).** 메모리를 `num_ctx` 목표값에 맞춰 잘라 프롬프트를 윈도우 내에 유지한다. 완전 보장은 아니며 추정치로 동작한다. 4096·8192·16384 윈도우에서도 동작 방식은 동일하다. CrewAI·Letta·AutoGen 도 히스토리를 자르지만, Glimi 는 윈도우 크기를 직접 버짓으로 삼는다. Ollama 의 VRAM 기반 컨텍스트 조절 이슈는 미해결 상태다.

**2. 내장 런타임의 드리프트 방지 메모리.** `agent_facts` 는 유효기간을 가지며 모순된 정보는 supersede 처리된다(이력 유지). Zep Graphiti 는 독점 UI 포함 엔진, Mem0 는 2026 년 모순 해소 기능이 제거되었다. Glimi 는 supersession, 런타임, 대시보드를 모두 무료 제공한다. SQLite 행 단위 supersession 을 사용하며 작지만 동일하게 동작한다.

## 통합 개요

이 구조 위에서 다음 기능이 작동한다.

- **영속 인구.** 각 에이전트의 페르소나와 모델을 정의하고 Claude·Ollama 를 묶어 fleet 으로 운영한다. 상태는 스토리지 기반이라 모델 전환 후에도 기억과 관계가 남는다.
- **자율 실행.** proactive supervisor 가 주기적으로 채널을 열어 대화를 이어간다. 대부분 reactive 만 지원하지만 Glimi 는 인구가 스스로 동작한다.
- **저사양 친화.** 여러 에이전트가 로컬 모델 하나를 공유해 16GB 환경에서도 실행된다. Ollama 모델 위에 상태 관리층을 추가했다.
- **인구 대시보드.** 관계 그래프, L0–L5 메모리 뷰, 라이브 채널, 모델 조회를 실시간 표시한다. Letta ADE·Hermes HUD 는 단일 어시스턴트만 다루지만, Glimi 는 인구 단위로 본다.

현재 알파 버전(0.1.0, PyPI 미배포)이다. 기능적으로 Letta·AI Town·SillyTavern·Zep 이 앞서지만, Glimi 는 이 조합으로 차별화된다.

## Glimi vs. 대안들

프로젝트별 강점은 다르다. Glimi 의 포지션은 다음과 같다.

| 기능 | Glimi | Letta (MemGPT) | AI Town | Zep / Graphiti | CrewAI / LangGraph | SillyTavern |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| pip 설치형 라이브러리, fleet 직접 설계 | ✅ | ✅ | ❌ TS 게임 스택 | ✅ 엔진만 | ✅ | ❌ 챗 프론트엔드 |
| 에이전트별 모델, 한 fleet 에 클라우드+로컬 | ✅ | ✅ | ❌ 단일 공유 모델 | — | ✅ | ◐ |
| 모델 스왑에도 메모리 유지 (상태=스토리지) | ✅ | ✅ | ✅ | ✅ | ◐ | ◐ |
| 시간 기반 fact supersession (드리프트 방지) | ✅ 스코프 | ❌ | ❌ | ✅ 레퍼런스 | ❌ | ❌ |
| 자율 에이전트-간 대화 (스스로 시작) | ✅ | ❌ | ✅ | ❌ | ❌ | ◐ |
| 하드웨어 인지 elastic 컨텍스트 버짓 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 관계 그래프 + 메모리 대시보드 내장 | ✅ | ◐ 단일 | ◐ 시뮬뷰 | ❌ 호스팅 | ❌ 별도 | ❌ |

✅ 됨 · ◐ 부분 · ❌ 안 됨 · — 해당 없음. 메모리 페이징은 Letta 가 깊고, AI Town 은 완성도가 높다. Zep 은 시간 그래프가 더 완전하며, SillyTavern 은 캐릭터 도구가 많다. Glimi 는 이 일곱 줄을 하나의 AGPL-3.0 패키지로 제공하는 유일한 프로젝트다.
