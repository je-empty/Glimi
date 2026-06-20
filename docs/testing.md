# 테스트 절차

> 기여자용 테스트 가이드. PR 올리기 전 무엇을 어떻게 돌리는지.
> Claude Code 자율 QA 사이클(판정 기준·반복 절차)은 `docs/qa_playbook.md`.

## 변경 유형 → 돌릴 테스트

| 변경한 것 | 필수 | 권장 |
|---|---|---|
| `community/core/` · `community/db.py` (global state) | 격리 테스트 | E2E QA 1회 |
| `community/bot/formatting.py` | 포맷팅 테스트 | |
| 씬·튜토리얼·봇 플로우 | E2E QA | |
| 프롬프트·콘텐츠 (catalog/씬 텍스트) | 실제 대화 1회 이상 | E2E QA |
| 플랫폼 UI (`community/platform/`) | 브라우저 실확인 | |
| 문서만 | 없음 | |

## 1. 단위 테스트

```bash
python -m tests.unit.test_formatting             # 포맷팅 (#channel 치환 등)
python -m tests.unit.test_community_isolation    # 커뮤니티 격리 — ⚠ 현재 레드 (#4), 복구 전까지 참고용
```

## 2. E2E QA — `scripts/qa.sh`

tmux 백그라운드 세션(`Glimi-QA-Runner`)에서 테스트 봇이 가짜 오너로 발화하며
튜토리얼부터 실플레이를 자동 수행한다.

### 최초 1회 셋업 (사람마다)

1. QA 전용 디스코드 서버 1개 + 봇 2개 (에이전트 봇 / 테스트 유저 봇) 생성
2. 설정 파일 복사 후 채우기:
   ```bash
   cp tests/e2e/qa.env.example communities/qa/.env
   ```
3. **QA 페르소나에 자기 자신을 넣는다** (`QA_USER_NAME` 등) — 에이전트가 이 사람을
   오너로 인식하므로, 본인 이름/호칭이어야 호칭·기억 로직이 실사용 조건으로 검증된다.
   `communities/` 는 gitignore 라 개인정보·토큰은 커밋되지 않는다.

### 실행

```bash
./scripts/qa.sh                                  # 초기화 후 1회 (튜토리얼부터)
./scripts/qa.sh --resume                         # 이전 DB/채널 유지, 이어서
./scripts/qa.sh --resume --seed-prompt "지시"    # 첫 발화에 지시 주입
./scripts/qa.sh attach                           # 실행 중 세션 보기
./scripts/qa.sh stop                             # 종료
tail -f tests/e2e/results/latest.log             # 로그
```

결과: `tests/e2e/results/run-*.json`. 판정 기준 (P0 튜토리얼 완주 ~ P5 도구 오류 0건 +
품질 게이트 7항목)은 `docs/qa_playbook.md` §1.

### 바이브코딩으로 돌리기

Claude Code 에게 **"QA 진행해"** 라고 하면 `docs/qa_playbook.md` 를 따라
실행→분석→수정→재실행 사이클을 자율 수행한다. 셋업(위 2-3번)만 사람이 한 번 해두면 됨.

## 3. 콘텐츠·프롬프트 변경 확인

테스트 통과 ≠ 체감 품질. 프롬프트·씬·도전과제 텍스트를 바꿨으면 **실제 대화를 1회 이상**
돌려보고 어색한 발화가 없는지 확인 후, 가능하면 스크린샷을 PR 에 첨부.

## 4. CI (자동)

PR 과 main/develop push 에서 자동 실행: `compileall` (문법) + 포맷팅 테스트.
격리 테스트는 #4 그린 복구 후 게이트에 추가 예정 (#5). E2E QA 는 Discord 토큰이
필요해 CI 부적합 — 로컬 절차로 유지.
