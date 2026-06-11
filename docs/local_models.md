# Glimi 로컬 모델 모드 (Claude 의존 0)

> Glimi Core 는 모델 중립 하네스다. `GLIMI_LLM_BACKEND=ollama` 한 줄로 **모든 LLM 호출**
> (페르소나 대화·매니저 도구 호출·메모리 추출·슈퍼바이저 판정·도전과제 판정)이 로컬
> Ollama 모델로 라우팅된다. Anthropic API 키 불필요.
>
> 이 문서 = ① 에이전트 종류별 권장 모델 + VRAM ② 권장 하드웨어 (Mac/Windows)
> ③ 모델 선택 실험 결과 ④ 설정 방법. 상세 셋업은 [`ollama_setup.md`](ollama_setup.md),
> 런타임 분기 설계는 [`ollama_runtime_migration.md`](ollama_runtime_migration.md).

## 1. 에이전트 종류별 모델 + VRAM (prod 분리 구성 기준)

아래는 **prod 티어**(매니저=큰 모델, 그 외=작은 모델 분리, 24GB+ 필요) 기준이다.
12GB GPU 등 저사양은 §2 의 quality(iq3-26b 단일) 또는 standard(e4b 단일) 티어를 쓴다.
(전부 gemma4 abliterated — 거부·검열 없음)

| 에이전트 종류 | 역할 | 모델 | 상주 VRAM |
|---|---|---|---|
| **매니저** (유나 mgr) | 채널·프로필 도구 호출, 온보딩 | `gemma4-26b-a4b-abl:iq3` | **~13 GB** |
| **크리에이터** (하나 creator) | 페르소나 생성, 도구 호출 | `gemma4-26b-a4b-abl:iq3` *(매니저와 공유)* | (위와 동일 모델) |
| **페르소나** (AI 친구들) | 일상 대화, 캐릭터 유지 | `gemma4 e4b abl` | **~10 GB** |
| **슈퍼바이저** (대화 감시/개입) | 개입 판정, 멈춘 대화 재개 | `gemma4 e4b abl` *(전역 공유)* | (위와 동일 모델) |
| **메모리 추출** | 대화 → facts JSON | `gemma4 e4b abl` *(전역 공유)* | (위와 동일 모델) |
| **도전과제 판정** | 달성 여부 판정 | `gemma4 e4b abl` *(전역 공유)* | (위와 동일 모델) |
| **개발 담당** (dev) | triage/응답 | `gemma4 e4b abl` *(전역 공유)* | (위와 동일 모델) |

→ **동시 상주 = iq3-26b (13GB) + e4b (10GB) ≈ 23 GB** (8K 컨텍스트 KV 캐시 포함)

매니저(iq3-26b)는 `GLIMI_OLLAMA_MODEL_MAP`, 나머지(e4b)는 전역 `GLIMI_OLLAMA_MODEL` 로
지정된다. 같은 모델은 Ollama 가 한 번만 로드하므로 메모리는 **모델 2종 합산**이지 에이전트
수만큼 늘지 않는다.

### 모델 사양

| | iq3-26b (매니저) | e4b (그 외 전부) |
|---|---|---|
| 아키텍처 | gemma4 MoE | gemma4 MatFormer |
| 파라미터 | 25.2B 총 / **4B active** | 8B 총 / **4B effective** |
| 양자화 | IQ3_XS | Q4_K_M |
| 디스크 | 11 GB | 9.6 GB |
| 컨텍스트 | 262K | 131K |
| 웜 응답 | ~1 s | ~0.5 s |

둘 다 **실연산 4B급**이라 빠르고, 도구 호출 정확도는 26b-a4b 가 e4b 보다 확실히 높다(아래 실험).

## 2. 티어 & 권장 하드웨어

부하는 **전적으로 LLM 추론**이다. 봇·대시보드·Discord 어댑터는 순수 파이썬이라 가볍다.
즉 권장 사양 = "어떤 로컬 모델 구성을 VRAM 에 올리느냐"로 결정된다. 4개 티어를
`GLIMI_LOCAL_TIER` 로 고른다 (`run.sh --local-models` 가 자동 세팅, 기본 standard).

| 티어 | 구성 | 모델 메모리 | Mac (통합) | Windows/Linux (VRAM) | 특성 |
|---|---|---|---|---|---|
| **lite** | e2b 단일 | ~7 GB | 16 GB | 8 GB | 최속, 도구 정확도 낮음 |
| **standard** *(기본)* | e4b 단일 | ~10 GB | 16 GB | 12 GB (RTX 3060/4070) | 균형. 대부분 케이스 |
| **quality** | **iq3-26b 단일** | ~13 GB | 24 GB | **12 GB** (RTX 4070) | 도구 3/3 + 26b 품질. 12GB 면 ~1GB 만 CPU 오프로드 (MoE 라 영향 작음) |
| **prod** | 26b 매니저 + e4b 분리 (동시상주) | ~23 GB | 32 GB | 24 GB (RTX 4090/3090) | 최고품질. 둘 다 풀 GPU, 스왑 0 |

### 핵심: VRAM 별 선택

- **12 GB GPU (예: RTX 4070 SUPER) — 동시상주 분리는 불가.** 두 양질 모델이 12GB 에 안 들어간다.
  → **quality(iq3-26b 단일)** 가 최적: 13GB 라 12GB 를 1GB 만 초과, MoE active 4B 라 오프로드
  페널티가 작고, 전 에이전트가 26b 라 매니저 정확도(3/3)와 페르소나 품질을 둘 다 챙긴다. **스왑 0.**
  속도 우선이면 standard(e4b 단일).
- **24 GB+ GPU / 32 GB Mac — prod(분리)** 가능: 매니저 iq3-26b + 페르소나 e4b 를 동시 상주.
  매니저↔페르소나 전환에 스왑 없음 (둘 다 GPU 상주). 시스템 RAM 32GB+ 권장.
- **16 GB Mac — standard(e4b 단일)** 가 상한. 분리는 통합 메모리 24GB+ 필요.

> 두 모델 동시 상주(prod)는 Mac 32GB / Windows 24GB VRAM 이 분기점. 그 아래에서 분리를 강제하면
> 모델 스왑(콜드 로드 10~20초)으로 체감이 급락하므로, **차라리 단일 티어(quality/standard)** 가 빠르다.

## 3. 모델 선택 실험 (2026-06-11)

Glimi 백엔드(`src.llm` + runtime 스트림 소비기) 경유로 동일 하네스 측정. 항목: blocking/스트리밍
지연, `<tools>` `create_room` 호출 정확도, control/think token 누출.

### winpc (RTX 4070S 12GB)

| 모델 | blocking | 스트리밍(웜) | `<tools>` | 비고 |
|---|---|---|---|---|
| **gemma4 26b-a4b** | 20s* | 1.6s | **3/3** | 도구 전승, 품질 최고. *콜드 로드 포함 |
| gemma4 e4b | 14s | 1.3s | 2/3 | 미스=되묻기. 톤 자연. 페르소나 적합 |
| gemma4 e2b | 7s | 0.3s | 1/3 | 최속이나 도구 미스 질 나쁨(빈 블록) |
| qwen3.5 9b | 22s | 3.7s | 1/3 | 표현력 있으나 고유명사 발명 경향 |

### Mac (M3 Air 24GB)

| 모델 | blocking | 스트리밍(웜) | `<tools>` |
|---|---|---|---|
| gemma4 e2b | 6.9s | 0.7s | 3/3 |
| gemma4 e4b | 14.2s | 1.3s | 3/3 |
| **gemma4 26b-a4b (IQ3_XS)** | 20.4s | 2.3s | **3/3** |
| qwen3.5 9b | 22.3s | 3.7s | 2/3 (평균 17s — 탈락) |

### 결론

- **도구 호출(매니저/크리에이터)은 26b-a4b 가 가장 안정적** — 작은 모델은 `<tools>` 정확도
  편차가 크다.
- **페르소나/메모리/슈퍼바이저는 e4b 로 충분** — 도구보다 자연스러움·속도가 중요.
- **24GB Mac 에서 26b-q4(17GB)+e4b 동시 상주는 불가** → 스왑 발생. 12GB VRAM 에 맞춘
  **IQ3_XS quant(11GB)** 를 쓰면 e4b 와 함께 ~23GB 로 24GB 에 올라간다(스왑 없음).
  교대 호출 실측: 매니저 ~1s / 페르소나 ~0.5s, 스왑 페널티 없음.

## 4. 설정 방법

### 원커맨드 부트스트랩 (권장)

아무것도 세팅 안 된 머신에서 한 줄로 끝낸다 — venv/deps + Ollama 설치(맥=brew, 윈도우=winget)
+ 서버 기동 + 기본 모델(e4b) 다운로드까지. **이미 된 단계는 전부 자동 스킵** (idempotent).

```bash
./run.sh --local-models          # Mac — 그대로 로컬 모드로 플랫폼 기동
run.bat --local-models           # Windows
./run.sh --local-models --setup-only   # 세팅만 하고 서버는 안 띄움
```

`GLIMI_OLLAMA_MODEL` 을 미리 export 해두면 기본 모델 대신 그 태그를 확인/다운로드한다.
ENV `GLIMI_LOCAL_MODELS=1` 은 플래그와 동등.

### 수동 설정

커뮤니티 `.env` (또는 환경변수):

```bash
GLIMI_LLM_BACKEND=ollama

# 그 외 전부(페르소나·메모리·슈퍼바이저·judge·dev)의 전역 모델
GLIMI_OLLAMA_MODEL=huihui_ai/gemma-4-abliterated:e4b

# 종류별 분리 — 매니저/크리에이터만 큰 모델 (JSON 은 작은따옴표로 감쌀 것: bash source 가
# 큰따옴표를 벗겨내 JSON 파싱이 깨짐)
GLIMI_OLLAMA_MODEL_MAP='{"mgr":"gemma4-26b-a4b-abl:iq3","creator":"gemma4-26b-a4b-abl:iq3","persona":"huihui_ai/gemma-4-abliterated:e4b","_default":"huihui_ai/gemma-4-abliterated:e4b"}'

# 모델 2종 상주 유지 (스왑 방지)
OLLAMA_KEEP_ALIVE=30m
```

모델 우선순위: **에이전트 개별**(DB `agents.model_override` = `ollama:<태그>`)
> **종류별**(`GLIMI_OLLAMA_MODEL_MAP[type]`) > **전역**(`GLIMI_OLLAMA_MODEL`).
대시보드 에이전트 카드는 이 우선순위를 그대로 해석해 **실제 사용 모델**을 표시한다(상수 박지 않음).

IQ3 quant 는 Ollama 레지스트리에 없으므로 GGUF 임포트가 필요하다:

```bash
ollama create gemma4-26b-a4b-abl:iq3 -f Modelfile   # FROM <IQ3_XS gguf>
```

검증: 로컬 모드 QA E2E 풀런에서 **Claude 호출 0건, control token 누출 0건** 확인.
