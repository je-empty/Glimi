# Glimi Core — 내부 구조

[← README](../README.ko.md)

Glimi Core(`glimi` 커널)의 전체 기능 상세 — "박스 안에 든 것" 전 항목, 라이브러리 의존성 주입 seam, 읽기 전용 관찰성 대시보드, 기본 LLM 모델 역할 분리. 런타임 파이프라인과 메모리 레이어는 [memory.ko.md](memory.ko.md), Elastic Memory 는 [elastic_memory.ko.md](elastic_memory.ko.md) 에 있다.

---

## 박스 안에 든 것

| 기능 | 상세 |
|---|---|
| **멀티 에이전트 런타임** | 에이전트별 모델 오버라이드 DB 저장. 클라우드(Claude) 와 로컬(Ollama) 이 한 fleet 에 공존 — Grok CLI 도 가능, vLLM / llama.cpp 는 pluggable backend seam 으로 예정. 재시작 없이 스왑 가능 |
| **도구 프로토콜** | `<tools><call id="1" name="...">...</call></tools>` 인라인 XML — 선언적 `ToolSpec` 레지스트리 + 권한·타입·env 게이팅 |
| **레이어드 영속 메모리 (L0–L5)** | L0 원본(`conversations`) → L1 워킹 윈도우(최근 발화 그대로, 라이브 주입) → L2 에피소드 rollup(`memories` 안 L1→L2→L3 digest) → L3 의미 사실(`agent_facts`: subject·predicate·object + `valid_from`/`valid_to` supersession) → L4 관계(`relationships` + 이력) → L5 고정(`memories.is_pinned`). 응답 경로 밖에서 비동기 Haiku 추출 |
| **자율 A2A 대화** | 1:1 및 멀티-에이전트 채널. 턴 제한, closure 감지. 에이전트가 도구 프로토콜로 다른 에이전트와 대화 시작 |
| **Proactive supervisor 레이어** | 입력 없이도 도는 유일한 레이어. 페어 스캐너가 새 에이전트-간 채널을 열고, chat 감시자가 멈춘 채널을 깨우고, scene 감시자가 정체된 워크플로우를 진행시킨다 |
| **라이브 관찰성 대시보드** (`glimi[dashboard]`, 읽기 전용) | Cytoscape.js 에이전트 그래프, per-agent 메모리 인스펙터(L0–L5), 실시간 채널 뷰어, 도구 호출 타임라인, LLM 사용량/비용 카드, 런타임 상태 배지. (라이브 모델 스왑 *쓰기*는 Community/Workspace 플랫폼 기능 — Core 대시보드는 에이전트별 모델을 조회용으로 보여줄 뿐) |
| **평가 하네스** | 페르소나 / 도구사용 / 메모리 / 폴백 / 슈퍼바이저 능력별 골든셋; 결정적(deterministic) 체크 + LLM-as-judge(재사용, 재발명 아님); 백엔드 태깅된 **회귀 게이트**(pass-rate 또는 judge 점수 하락 시 CI 실패); 플래그된 나쁜 턴을 골든 케이스로 승격하는 프로덕션 피드백 루프. 오프라인 `echo` 백엔드에서 무료 실행 |
| **세대형 EDD QA** | 골든셋 eval 의 통합 짝: 자율 **오너 에이전트**가 앱을 온보딩부터 핵심 저니까지 구동하고, 가중 차원으로 채점해 **0–100 품질 점수**, 각 런은 **git-SHA 앵커 "세대"**(SQLite + 커밋 JSON)로 commit-over-commit 추적. [edd.ko.md](edd.ko.md) 참조. |
| **비용·지연 정산** | 모든 LLM 호출이 토큰·추정 비용·지연을 한 choke-point 에서 기록하고, 모든 도구 호출이 args/result/지연/성공여부를 또 한 곳에서 기록. 설계상 정직 — 로컬/echo 는 $0, CLI/추정 행은 *est.* 표시, 실제 과금된 지출에만 달러 표기 |
| **사람 개입 게이트** (Workspace) | 중대한 액션 둘레의 승인 정책(`승인 / 수정 / 거부` + 폴백 + 결정 로그). Workspace 가 사용; 절대 멈추지 않음(비대화형은 자동 승인) |
| **자가 치유** (실험적, 기본 비활성) | 에이전트가 `request_dev_fix` 호출 → dev_requests 행 큐잉 → dev-queue supervisor 가 트리아지 → 승인 시 Opus subprocess(`GLIMI_DEV_DISPATCH=1`)가 소스 패치 → 봇 재시작 시 패치 요약 주입 |

## 라이브러리 사용 & 의존성 주입

Glimi Core 는 **알파 (0.1.0, PyPI 미배포)**. 소스에서 설치한다. 커널은 인메모리 스토어와 **오프라인 `echo` 백엔드**를 내장한다. 예제는 **의존성·API 키 0**으로 실행된다. `echo` 는 모델 호출 없이 하네스 배선을 검증한다:

```python
from glimi import Glimi

chat = Glimi(backend="echo")          # 오프라인: 의존성·API 키·네트워크 전부 불필요
chat.add_agent("nova", persona="호기심 많고 잘 묻는 명랑한 친구.")

print(chat.reply("nova", "안녕! 이름이 뭐야?"))
print(chat.reply("nova", "좋네 — 재밌는 얘기 하나 해줘."))
```

백엔드 교체만으로 실제 모델로 전환된다.

```python
chat = Glimi(backend="claude_cli")    # Claude CLI 로그인 사용 (SDK 불필요) — 구독 무료가 아니라 사용량만큼 과금(metered)
chat = Glimi(backend="ollama")        # Ollama 로 완전 로컬 — 무료 옵션 (GLIMI_OLLAMA_MODEL 설정)
```

`Glimi` 는 인메모리 `KernelStore`, `ProfileProvider`/`OwnerContext`, `NullObserver`, 지정 LLM 백엔드를 자동 배선한다. 세부 제어가 필요하면 각 구성요소를 직접 로드해 사용한다.

```python
from glimi import (
    InMemoryKernelStore, SimpleProfileProvider, SimpleOwnerContext,
    KernelStore, ProfileProvider, OwnerContext, KernelObserver,  # 직접 구현할 seam
    LLMBackend, LLMResponse, EchoBackend,
)
```

자체 DB 를 쓰려면 `KernelStore` 와 필요한 provider/observer 를 구현해 `glimi.runtime.set_store(...)` 로 등록한다. 완성 예시(SQLite + 웹 어댑터):

- `community/adapters/kernel_store.py` — `SqliteKernelStore` + 프로필/옵저버 어댑터
- `community/core/runtime.py` — 커널 주입 + API 재export

## 웹 대시보드 (Glimi Core 의 관찰성)

Core 대시보드는 모든 에이전트에 대한 **읽기 전용** 관찰성이다 — Cytoscape.js 그래프, 메모리 인스펙터(L0–L5), 채널 뷰어, 도구 호출 타임라인, 에이전트별 모델 배지. **읽기 전용**이며 모델 스왑 *쓰기* 는 Community/Workspace 기능이다.

| 연결 그래프 | 메모리 인스펙터 |
|---|---|
| <img src="screenshots/ko/04-graph-live.png" height="300" alt="연결 그래프"/> | <img src="screenshots/ko/02-persona-memory.png" height="300" alt="메모리 인스펙터"/> |

- **Cytoscape.js 그래프** — 에이전트 연결·채널 활동·supervisor overlay 표시
- **메모리 인스펙터 (L0–L5)** — pinned, 에피소드, 의미 사실, 관계 변곡점 표시
- **실시간 채널 뷰어** — 각 에이전트의 현재 시점 표시
- **도구 호출 타임라인** — `<tools>` 호출 이력과 결과 표시
- **에이전트별 모델 (읽기 전용)** — 클라우드/로컬 모델 표시 (스왑은 Community/Workspace 전용)

## LLM 모델 역할 (기본 설정)

기본 config 는 역할을 모델별로 쪼갠다(메모리/judge/응답은 Haiku, 추론은 Sonnet, 일회성/자가치유는 Opus) — Sonnet 단일 대비 대략 **10배 저렴**.

| 역할 | 모델 | 이유 |
|---|---|---|
| 메모리 추출 | `claude-haiku-4-5` | 싸고 빠름, 매 배치마다 백그라운드 worker |
| Supervisor / judge | `claude-haiku-4-5` | 경량 상태 판정 |
| 에이전트 응답 (기본) | `claude-haiku-4-5` | 대화량 많고 지연 민감 |
| 추론 / 도구 조합 | `claude-sonnet-4-6` | 대시보드에서 per-agent 오버라이드 |
| 원샷 구조화 출력 | `claude-opus-4-6` | 프로필 JSON, 복잡 생성 |
| 자가 치유 | `claude-opus-4-6` | 런타임 에러 기반 소스 패치 |
| 로컬 / 대안 | Ollama · Grok | 로컬 무료(Ollama) + Grok CLI; vLLM / llama.cpp 는 예정 (`AVAILABLE_MODELS` 스텁 준비됨) |

균일 Sonnet 대비 약 10배 저렴하다.
