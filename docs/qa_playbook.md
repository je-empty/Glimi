# QA 자율 수행 절차 (Claude Code 용)

유저가 "QA 진행해" / "QA 돌려" / "qa 돌리자" 등 한 마디 하면, 이 문서를 읽고 **자율적으로** QA 사이클을 수행한다. 분석·수정·재실행 반복. 유저 개입 없이 합리적으로 판단.

## 0. 트리거 → 즉시 체크리스트

1. **현재 QA 세션 상태**: `tmux ls | grep QA` + `ps aux | grep discord_bot`
   - 이미 돌아가면: 멈출지(백업+분석) 그대로 둘지 유저 의도 확인.
2. **최근 결과 스캔**: `tests/e2e/results/run-*.json` 최신 3개 — 연속 PASS 면 목표 상향, FAIL 면 원인 확인 먼저.
3. **git 상태**: 커밋 안 된 변경 있으면 먼저 파악 (내가 방금 뭘 고쳤는지 맥락 복구).
4. **미완 작업 메모리**: `MEMORY.md` 의 `Onboarding Bugs` / `QA Automation` 항목 재확인.

## 1. 이번 사이클의 QA 목표 설정

유저가 타겟 명시 안 하면 아래 우선순위로 자율 설정:

| 우선순위 | 목표 | 성공 기준 |
|---|---|---|
| P0 | 튜토리얼 완주 | `tutorial_done: true`, 에러 0 |
| P1 | 페르소나 3명 생성 + 각자 DM 대화 2턴 이상 | DB 에 3 persona + 각 dm 채널 log ≥ 4 건 |
| **P2** | **Haiku 페르소나 품질 Sonnet 급 유지** | 아래 § 1.1 품질 게이트 — 7 항목 중 ≥ 6 개 통과 |
| P3 | 메타 누출 0건 (`#mgr-*` / "대시보드" / "만들어졌다" persona 발화) | conversation grep 결과 0 |
| P4 | 에이전트 간 internal-dm 자연 발동 (orchestrator) | `[sup:orchestrator] ▶ 대화 시작` 1회 이상 + 실제 메시지 교환 |
| P5 | 도구 오류 0건 | 로그에서 `[Tool] ✗` 0건, `TypeError` 0건 |
| P6 | 그룹 채팅 / 씬 트리거 | 추후 확장 |

**이번 사이클 어디까지 가볼지 결정 후 한 줄로 유저에게 보고** ("이번엔 P0–P3 타겟").

### 1.1 Haiku 페르소나 품질 게이트

**컨텍스트**: persona 기본 모델이 Sonnet 4.6 → Haiku 4.5 로 변경됨 (비용/지연 절감). Haiku 는 reasoning 얕아서 페르소나 일관성·뉘앙스 드리프트 위험. 이 게이트는 드리프트 감지용.

**절대 금지**: Haiku 성능 끌어올리려고 system prompt 에 수 백 줄 규칙/예시 추가. 토큰 늘면 Haiku 쓰는 의미 상실 (Sonnet 보다 비싸질 수 있음 — 입력 토큰 관점). 개선은 **구조/어휘 최적화** 로만.

**7 품질 체크** (DB conversations 기반, sqlite 로 샘플):

| # | 항목 | 측정 |
|---|---|---|
| 1 | **페르소나 일관성** | 같은 페르소나의 전체 발화에서 말투/성격이 한 가지로 유지 (MBTI 반영) |
| 2 | **맥락 추적** | 유저 발화 내용을 다음 발화에서 언급·반영 (n=3 샘플) |
| 3 | **발화 자연스러움** | `ㅋㅋ`, `~`, 적절한 줄바꿈, 이모지 사용 — 로봇 아님 |
| 4 | **반복 회피** | 같은 문장 구조 3회 이상 연속 금지 |
| 5 | **질문 되돌려주기** | 자기 얘기만 하지 않고 상대에게 되묻는 발화가 총 발화의 ≥ 20% |
| 6 | **도구 안 건드리기** | persona 가 `<tools>` 블록 생성 0건 (mgr/creator 권한) |
| 7 | **길이 적절성** | 평균 발화 ≤ 60자, 긴 설교 금지 |

체크 쿼리 예:
```bash
# 항목 3, 7 한 번에
sqlite3 communities/qa/community.db "
  SELECT speaker, COUNT(*) AS n, AVG(LENGTH(message)) AS avg_len,
         SUM(CASE WHEN message LIKE '%ㅋㅋ%' OR message LIKE '%ㅎㅎ%' THEN 1 ELSE 0 END) AS casual,
         SUM(CASE WHEN message LIKE '%?%' THEN 1 ELSE 0 END) AS questions
  FROM conversations WHERE speaker LIKE 'agent-persona-%' GROUP BY speaker"

# 항목 6 (치명적)
sqlite3 communities/qa/community.db "
  SELECT speaker, message FROM conversations
  WHERE speaker LIKE 'agent-persona-%' AND message LIKE '%<tools>%'"
```

**판정**: 7 중 ≥ 6 통과면 Haiku 유지 OK. ≤ 5 면 처음엔 **프롬프트 구조 정리** (현 프롬프트에서 불필요한 반복/훈수 제거) 시도. 그래도 안 되면 해당 페르소나만 Sonnet override 로 fallback, 이슈 기록 + 유저 상의.

## 2. 실행 — 원자 단계

### 2.0 resume vs reset 판단 (연속 사이클 최적화)

**원칙**: 직전 사이클이 자연 종료 + 튜토리얼 완료 + BLOCKER 없음 → **`--resume` 로 이어 실행**.
튜토리얼 재실행은 비싸고 (~900초 + Sonnet 수십 콜) 검증 가치도 낮음. 이미 통과한 구간이라.

| 직전 상태 | 다음 사이클 명령 |
|---|---|
| PASS + tutorial_done + 이슈 없음 | `./scripts/qa.sh --resume --seed-prompt "<지시>"` |
| PASS + tutorial_done + DRIFT 관찰만 (1회) | `./scripts/qa.sh --resume` (같은 DB에서 재현 시도) |
| BLOCKER 픽스 직후 | `./scripts/qa.sh` (전체 reset — 클린 DB에서 검증) |
| 구조 변경 (스키마/프롬프트 큰 수정) | `./scripts/qa.sh` (reset) |

`--seed-prompt` 활용 예:
- 자율 대화 검증: `--seed-prompt "오늘은 얘들 좀 구경하면서 돌아다니기만 할게"` → test_user 가 대화 유도만 하고 도구 호출 안 시킴
- 메타 누출 회귀 테스트: `--seed-prompt "박지안한테 여기가 뭐하는 곳이냐고 물어봐"` → 1회 이슈 재현 시도

**반드시 `./scripts/qa.sh` 로만 실행. `python -m tests.e2e.runner` 직접 호출 금지.**

qa.sh 는 `Glimi-QA-Runner` 라는 이름의 tmux 세션을 detached 로 띄움. 이유:
- macOS Keychain 언락을 세션 내부로 전파 (Claude CLI 가 keychain 참조)
- SSH 끊겨도 런이 계속됨
- 중복 실행 자동 차단 (`tmux has-session` 가드)
- `./scripts/qa.sh stop` / `attach` 로 깔끔하게 제어

```bash
# (a) 토큰 스냅샷 (델타 계산용)
python -m tests.e2e.capture_usage snapshot > /tmp/qa_usage_before.json

# (b) QA 시작 — 이미 실행 중이면 에러 나고 종료 (안전)
./scripts/qa.sh

# run_id 확인 — tests/e2e/results/ 의 가장 최근 json 파일명
ls -t tests/e2e/results/run-*.json | head -1
```

즉시 return. run_in_background 불필요. 호출 후 바로 다음 단계로.

세션 상태 확인:
- `tmux has-session -t Glimi-QA-Runner 2>/dev/null && echo alive || echo dead`
- 살아있으면 런 진행 중. 죽어있으면 자연 종료 (또는 stop).

## 3. 모니터링 루프

`tests/e2e/results/latest.log` 와 `communities/qa/logs/system.log` 를 주기적으로 tail. 기본 사이클 **2–3분 간격**:

```bash
tail -50 tests/e2e/results/latest.log
tail -80 communities/qa/logs/system.log
```

`Monitor` 툴로 `until <condition>; do sleep 120; done` 형태 추천 (오래 sleep 가능).

### 중단 트리거 — 감지하면 즉시 `./scripts/qa.sh stop`

| 신호 | 의미 | 행동 |
|---|---|---|
| `Test Complete` / `🎯 튜토리얼 완료 감지` / 런 JSON 파일 생성 | 런 정상 종료 | Step 4 로 |
| 동일 에러 메시지 5회 이상 연속 (`TypeError`, `CLI 오류`, `Tool ✗`) | 루프 스택 | 즉시 stop → 분석 |
| `❌ 봇 즉시 종료` / `봇 준비 타임아웃` | 시작 실패 | 즉시 stop → 분석 |
| 30분 무활동 (system.log mtime 30분 전) | 데드록 | 즉시 stop → 분석 |
| test_user_bot turns 소진 (150턴 기본) | 자연 종료 | Step 4 로 |
| 유저가 `/` 메시지로 개입 | 유저 인계 | 작업 중단 + 유저에게 상황 요약 |

**중단 판단 기준**: 같은 에러 반복 → 지금 자산으로 분석 가능한 신호를 이미 확보했다는 뜻. 더 돌리면 토큰 낭비.

## 4. 결과 수집 & 토큰 기록

```bash
# 런 JSON 확인
cat tests/e2e/results/run-<ID>.json

# 백업 — 모든 런은 백업 (다음 세션에서 장기 추세 분석 가능)
mkdir -p communities/qa/backups/run-<ID>
cp communities/qa/community.db communities/qa/backups/run-<ID>/
cp -r communities/qa/logs communities/qa/backups/run-<ID>/
cp tests/e2e/results/run-<ID>.log tests/e2e/results/run-<ID>.json communities/qa/backups/run-<ID>/

# 토큰 사용량 델타 기록
python -m tests.e2e.capture_usage diff /tmp/qa_usage_before.json \
  --run-id run-<ID> \
  --elapsed <초> \
  --status <PASS|WARN|FAIL|ERROR>
```

→ `tests/e2e/results/token_usage.md` 에 한 줄 append 됨. 이게 누적 기록.

## 5. 분석 절차

### 5.1 정량 — 런 JSON
`status` / `issues` / `metrics` / `tutorial_done` 확인. WARN 이상이면 5.2 로.

### 5.2 정성 — 로그 + DB grep

```bash
# 에러/경고
grep -E "❌|⚠|Error|Exception|TypeError|[Tool] ✗|회귀" \
  tests/e2e/results/run-<ID>.log

# 메타 누출 (persona 발화에서만)
sqlite3 communities/qa/community.db \
  "SELECT channel,speaker,substr(message,1,200) FROM conversations
   WHERE speaker LIKE 'agent-persona-%'
     AND (message LIKE '%mgr-%' OR message LIKE '%대시보드%'
       OR message LIKE '%만들어졌%' OR message LIKE '%시뮬레이션%'
       OR message LIKE '%에이전트%' OR message LIKE '%캐릭터%')"

# 도구 호출 실패
grep -E "\[Tool\] ✗" communities/qa/logs/system.log

# orchestrator 동작
grep -E "\[sup:orchestrator\]" communities/qa/logs/system.log
```

### 5.3 이슈 분류 → TaskCreate

각 이슈를 태스크로:
- **BLOCKER**: 튜토리얼 진행 불가, 봇 크래시. 재실행 전 반드시 픽스.
- **REGRESSION**: 이전 커밋에서 동작하던 게 깨짐. 바로 픽스.
- **DRIFT**: 프롬프트/LLM 판단 흔들림 (예: 응답 스타일 어긋남). 프롬프트 조정.
- **FLAKY**: 1회성, 재현 불분명. 메모하고 패스 (2회 반복되면 승급).
- **COSMETIC**: UX 이슈, 기능 영향 X. 여유 있을 때.

## 6. 수정 절차

1. 각 BLOCKER/REGRESSION 타스크 `in_progress` → 코드 읽고 근본 원인 파악 → 픽스.
2. 프롬프트 변경은 `profile.py` + `formatting.py` 위주. LLM 환각은 **예시 오염** 의심 우선 (persona 에게 mgr-* 예시 노출 등).
3. 도구 관련은 `src/core/tools/validator.py` 에서 강성→관대(type coercion) 조정.
4. 픽스 후 단위 테스트:
   ```bash
   python -m tests.unit.test_formatting
   python -m tests.unit.test_community_isolation
   ```
5. 모든 BLOCKER 해결되면 Step 2 (재실행) 로.

## 7. 반복 루프 종료 조건

다음 중 하나 충족 시 루프 종료 + 유저에게 요약 보고:

- 목표(Step 1) 전부 달성 + 2사이클 연속 PASS (안정성 확인)
- 5사이클 이상 돌려도 동일 이슈 재발 → 구조적 문제, 유저 판단 필요
- 새 BLOCKER 가 내 판단 범위 밖 (아키텍처 변경, 외부 API 등)
- 유저가 중단 요청

## 8. 세션 종료 시 유저 리포트 포맷

```
## QA 사이클 완료

**런 수**: N회 (PASS M, WARN X, FAIL Y, ERROR Z)
**목표 달성**: P0 ✓ / P1 ✓ / P2 △ (이슈 있음)
**토큰 합**: $X.XX, 입력 Nk, 출력 Nk (상세: token_usage.md)
**주요 픽스**: (파일:라인 — 한 줄 설명) × N
**잔여 이슈**: (태스크 ID — 상세)
**다음 세션 제안**: (예: P3 internal-dm 자율 시작 검증)
```

## 9. 안전 규칙

- **커밋 자동 금지**: 픽스가 쌓여도 유저 승인 없이 commit 금지 (CLAUDE.md Co-Authored-By 정책). 픽스 요약만 보고.
- **DB 파괴 금지**: `communities/qa/community.db` 는 매 런 초기화되지만, 다른 커뮤니티 건드리지 말 것.
- **토큰 폭주 방지**: 런 1회당 대략 참고값 → `token_usage.md` 평균 대비 2배 이상이면 중단.
- **공유 상태 오염 방지**: 항상 `GLIMI_COMMUNITY=qa` 전제. 대시보드(:8765) 건드리지 말 것.

## 10. 레퍼런스

- 전체 아키텍처: `CLAUDE.md`
- 기존 QA 자동화 구조: `tests/e2e/runner.py`, `tests/e2e/test_user_bot.py`
- 토큰 델타 기록: `tests/e2e/capture_usage.py` → `tests/e2e/results/token_usage.md`
- 유나 지식 베이스 (메타 질문 응답 테스트): `docs/yuna_knowledge.md`
