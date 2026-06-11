# Glimi 로컬 모델 모드 (Claude 의존 0)

> Glimi Core 는 모델 중립 하네스다. `GLIMI_LLM_BACKEND=ollama` 한 줄로 **모든 LLM 호출**
> (페르소나 대화·매니저 도구 호출·메모리 추출·슈퍼바이저 판정·도전과제 판정)이 로컬
> Ollama 모델로 라우팅된다. Anthropic API 키 불필요.
>
> 이 문서 = ① 에이전트 종류별 권장 모델 + VRAM ② 권장 하드웨어 (Mac/Windows)
> ③ 모델 선택 실험 결과 ④ 설정 방법. 상세 셋업은 [`ollama_setup.md`](ollama_setup.md),
> 런타임 분기 설계는 [`ollama_runtime_migration.md`](ollama_runtime_migration.md).

## 1. 권장 디폴트 — 에이전트 종류별 모델 + VRAM

로컬 모드 권장 구성은 **2개 모델**만 상주시킨다: 도구 호출이 잦은 매니저류는 큰 모델,
나머지는 빠른 작은 모델. (전부 gemma4 abliterated — 거부·검열 없음)

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

## 2. 권장 하드웨어

부하는 **전적으로 LLM 추론**이다. 봇·대시보드·Discord 어댑터는 순수 파이썬이라 가볍다.
즉 권장 사양 = "어떤 로컬 모델 구성을 VRAM 에 올리느냐"로 결정된다.

### 경량 구성 (단일 모델 — 전 에이전트 e4b)

도구 정확도를 조금 양보하고 e4b 하나로 전부 돌리는 모드. 메모리 ~10 GB.

| 플랫폼 | 최소 | 권장 |
|---|---|---|
| **Mac** (통합 메모리) | 16 GB | 24 GB |
| **Windows/Linux** (전용 VRAM) | 12 GB (RTX 3060 12G / 4070) | 16 GB |

### 권장 구성 (분리 — iq3-26b 매니저 + e4b 그 외, ≈23 GB)

| 플랫폼 | 최소 | 권장 | 비고 |
|---|---|---|---|
| **Mac** (통합 메모리) | **24 GB** (빠듯, 헤드룸 ~1GB) | **32 GB** | 48GB+ = 긴 컨텍스트/프로덕션 여유. M3/M4 어느 칩이든 GPU 코어로 구동 |
| **Windows/Linux** (전용 VRAM) | **24 GB** (RTX 4090 / 3090) | 24 GB+ | 12~16GB GPU 는 iq3-26b 만 VRAM, e4b 는 시스템 RAM 오프로드 → 느려짐. 시스템 RAM 32GB+ 권장 |

> **핵심**: 두 모델을 **전부 VRAM 에 올리려면** Mac 32GB / Windows 24GB VRAM 이 분기점.
> 그 아래에선 모델 스왑(콜드 로드 10~20초)이나 CPU 오프로드로 체감 속도가 급락한다.
> VRAM 이 작으면 차라리 경량(단일 e4b) 구성이 더 빠르다.

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
