# Ollama 로컬 LLM 백엔드 셋업

`claude -p` (Claude Code 구독) 대신 로컬 GGUF 모델을 Ollama 로 띄워 페르소나 추론에 쓰는 절차.
`src/llm/ollama.py` 백엔드와 함께 작동.

예시 모델: `gemma-4-26B-A4B-it-abliterated.i1-Q5_K_M` (mradermacher imatrix Q5_K_M 양자화 GGUF).
다른 GGUF 도 같은 절차로 적용 가능 — 파일명만 교체.

## 1. Ollama 설치 확인

```powershell
ollama --version
```

없으면 https://ollama.com/download 에서 Windows installer 받기. 설치 후 자동으로 백그라운드 서비스로 돌아감.

## 2. GGUF 파일 위치 확인

받은 파일이 어디 있는지 확인. 예시 (실제 경로로 교체):

```
C:\Users\사용자명\Downloads\gemma-4-26B-A4B-it-abliterated.i1-Q5_K_M.gguf
```

## 3. Modelfile 작성

GGUF 와 **같은 폴더**에 `Modelfile` 이라는 파일(확장자 없음) 만들기. 내용:

```
FROM ./gemma-4-26B-A4B-it-abliterated.i1-Q5_K_M.gguf

PARAMETER temperature 0.7
PARAMETER num_ctx 8192
PARAMETER stop "<end_of_turn>"
```

> Ollama 가 GGUF 메타데이터에서 chat template 을 자동 인식하는 경우가 많음. 일단 위처럼 minimal 로 시도하고, 안 되면 (응답이 깨지거나 `<start_of_turn>` 같은 토큰이 그대로 찍히면) `TEMPLATE` 블록 추가 (아래 "자주 막히는 지점" 참조).

## 4. 임포트 (한 번만)

PowerShell 에서 **GGUF 가 있는 폴더로 이동 후**:

```powershell
cd C:\Users\사용자명\Downloads
ollama create gemma4-abliterated -f Modelfile
```

진행 중 출력:

```
transferring model data 100%
using existing layer sha256:...
creating new layer sha256:...
writing manifest
success
```

이 과정에서 Ollama 가 GGUF 를 자기 store (`%USERPROFILE%\.ollama\models\`) 로 복사함 — **18-19GB 추가 디스크 사용** (Q5_K_M 26B 기준). 끝나면 원본 GGUF 는 지워도 됨.

## 5. 확인

```powershell
ollama list
```

→ `gemma4-abliterated` 가 목록에 보여야 함.

대화 테스트:

```powershell
ollama run gemma4-abliterated "안녕! 한국어로 자연스럽게 답해줘."
```

→ 응답이 한국어로 나오면 성공. 첫 응답은 모델 로딩 때문에 수십 초 ~ 수 분 걸릴 수 있음 (이후엔 빠름).

## 6. Glimi 연결

```powershell
$env:GLIMI_OLLAMA_MODEL = "gemma4-abliterated"
$env:GLIMI_LLM_AGENT_MAP = '{\"persona\":\"ollama\",\"mgr\":\"claude_cli\",\"creator\":\"claude_cli\"}'
```

`mgr`/`creator` 는 도구 호출 정확도 중요해서 일단 Claude 유지 권장. 나중에 Gemma 가 `<tools>` 잘 따르는지 확인되면 ollama 로 바꿔도 됨.

봇/플랫폼 재시작 → 페르소나 호출이 ollama 로 라우팅됨.

### 재시작 범위

`src/llm/` 수정/연결 → **봇 + 플랫폼 둘 다 재시작 필요** (CLAUDE.md 의 재시작 범위 표 참조).

### 동작 검증

```powershell
python -c "from src.llm import generate; r = generate(system='너는 한국 친구', user='안녕', model='dummy', agent_type='persona', timeout=300); print('text:', r.text or r.error)"
```

`model` 인자는 `GLIMI_OLLAMA_MODEL` 가 override 하므로 dummy OK. 첫 호출은 모델 로딩 때문에 시간 걸리므로 `timeout=300` 권장.

## 자주 막히는 지점

### Modelfile 인식 못 함

윈도우 메모장이 자동으로 `Modelfile.txt` 로 저장하는 경우. `dir` 로 확장자 확인. 의심되면 PowerShell:

```powershell
Get-ChildItem Modelfile* | Format-List Name, Extension
```

`.txt` 붙어있으면 rename:

```powershell
Rename-Item Modelfile.txt Modelfile
```

### 응답에 `<start_of_turn>` 같은 토큰 그대로 노출

GGUF 메타에 template 정보 없는 경우. Modelfile 에 명시:

```
TEMPLATE """{{ if .System }}<start_of_turn>user
{{ .System }}

{{ .Prompt }}<end_of_turn>
<start_of_turn>model
{{ else }}<start_of_turn>user
{{ .Prompt }}<end_of_turn>
<start_of_turn>model
{{ end }}"""
```

> Gemma 는 별도 system role 미지원 — system 을 user 메시지 앞에 붙이는 패턴.

### "only one parent model" 에러

같은 태그 이름으로 이미 만든 경우.

```powershell
ollama rm gemma4-abliterated
```

후 재시도.

### VRAM 부족

일부 layer CPU offload 되며 느려짐. 정상 작동하긴 함.

```powershell
ollama ps
```

으로 CPU/GPU 분할 확인 가능.

### 첫 응답이 너무 느림 / timeout

26B Q5_K_M 첫 응답은 모델 로딩까지 합쳐 분 단위 걸릴 수 있음. `generate(timeout=300)` 정도로 호출하거나, Glimi 호출 경로에서 timeout 늘리기. 이후 호출은 모델이 메모리 상주하면 빠름.

## 관련 파일

- `src/llm/base.py` — 백엔드 추상 인터페이스
- `src/llm/__init__.py` — 백엔드 선택 로직 (`_select_backend`)
- `src/llm/ollama.py` — Ollama 백엔드 구현 (urllib stdlib only, 외부 의존성 없음)

## 환경변수 요약

| 변수 | 용도 | 기본값 |
|---|---|---|
| `OLLAMA_HOST` | Ollama 서버 base URL | `http://localhost:11434` |
| `GLIMI_OLLAMA_MODEL` | 전역 모델 태그 (아래 우선순위 3순위) | (없으면 호출자가 넘긴 model 사용) |
| `GLIMI_OLLAMA_MODEL_MAP` | agent_type 별 모델 태그 JSON (2순위) | (없음) |
| `GLIMI_LLM_AGENT_MAP` | agent_type 별 백엔드 매핑 JSON | (없으면 전역 기본 사용) |
| `GLIMI_LLM_BACKEND` | 전역 기본 백엔드 강제 | (없으면 SDK → CLI 순 자동 선택) |

## 모델 선택 우선순위 (타입별 / 에이전트별 분리)

큰 모델(mgr/creator)과 작은 모델(persona)을 같이 올려놓고 쓰는 구성 지원:

1. **에이전트 개별** — DB `agents.model_override` 에 `ollama:<태그>` (예: `ollama:gemma4:e2b-it-q4_K_M`)
2. **타입별** — `GLIMI_OLLAMA_MODEL_MAP` JSON. `_default` 키는 미지정 타입 폴백
   ```bash
   GLIMI_OLLAMA_MODEL_MAP={"mgr":"gemma4:26b-a4b-it-q4_K_M","creator":"gemma4:26b-a4b-it-q4_K_M","persona":"gemma4:e4b-it-q4_K_M"}
   ```
3. **전역** — `GLIMI_OLLAMA_MODEL` (1·2 가 없을 때, Claude 모델명이 그대로 들어오는 경로 회피)

주의: 여러 모델 혼용 시 VRAM 에 동시 상주 못 하면 호출마다 ollama 모델 스왑(콜드 로드 수십 초)이 발생.
`ollama ps` 로 상주 상태 확인. 단일 GPU 가 작으면 전역 단일 모델이 체감 더 빠를 수 있음.
