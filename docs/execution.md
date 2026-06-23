# 실행 & QA

## 실행
```bash
./run.sh                              # 플랫폼 데몬 (FastAPI, :8000) — 기본
./run.sh --port 9000                  # 포트 변경
./run.sh --legacy <community>         # 구 단일 봇 모드 (QA/디버깅)
./run.sh tui                          # 레거시 TUI wizard (deprecated)
./run.sh tui <community>              # 레거시 TUI dashboard
./scripts/stop.sh                     # 전체 종료

# 계정 관리 (CLI)
python -m community.platform.accounts bootstrap       # admin 계정 생성 (비번은 프롬프트/GLIMI_ADMIN_PASSWORD/랜덤)
python -m community.platform.accounts list
python -m community.platform.accounts add <user>
python -m community.platform.accounts grant <user> <community_id>

# 커뮤니티 관리 (CLI — 웹 UI 대체 중)
python -m community.community list
python -m community.community init <id>
python -m community.community export <id> <output_dir>
python -m community.community import <input_dir> <id>
```

## 멀티 서버 지원
- `.env` 에 `DISCORD_GUILD_ID=서버ID` 설정 → 특정 서버만 사용
- `on_message` 에서 guild 필터링 → 다른 서버 메시지 무시
- 미설정 시 `guilds[0]` 사용

## QA 자동 테스트

**자율 수행 절차:** `docs/qa_playbook.md` — "QA 진행해" 하면 이 문서 따라 사이클.
**토큰 누적 기록:** `tests/e2e/results/token_usage.md` — 매 런 델타 append.

```bash
python -m tests.e2e.runner              # 1회
python -m tests.e2e.runner --runs 3
./scripts/qa.sh                          # tmux 백그라운드 (권장)
./scripts/qa.sh stop
```

### 웹 E2E (실서버 HTTP/WS 구동)

위 `qa.sh` 는 디스코드 기반. **웹 자체 채팅을 진짜 서버로 구동하는 E2E** 는 별도:

- **커뮤니티 웹 E2E** — `tests/e2e/community_e2e.py` + `scripts/community_e2e.sh`.
  격리된 temp `GLIMI_DATA_DIR`/`GLIMI_COMMUNITIES_DIR` 에 `community.platform` 서버를
  띄우고, 친구 DM 채널을 채팅 WebSocket 으로 구동(오너 인사→질문→후속, 친구가 답)한 뒤
  판정·리포트한다. `--keep-serving` 이면 서버를 살려둬 브라우저/터널로 라이브 관전.
- **워크스페이스 웹 E2E** — `tests/e2e/ws_e2e.py` + `scripts/ws_e2e.sh` (동일 구조의 미러).

```bash
# 무료 셀프테스트 ($0, echo 백엔드) — 서버는 끝나면 정리됨
GLIMI_LLM_BACKEND=echo .venv/bin/python -m tests.e2e.community_e2e --rounds 1 --port 8231

# 실제 대화 (비용 발생, claude_cli) + 라이브 관전용으로 서버 유지
./scripts/community_e2e.sh --rounds 2 --keep-serving --host 0.0.0.0

# 판정 / 리포트 단독 재실행 (최신 snapshot)
.venv/bin/python -m tests.e2e.community_verdict --pretty
.venv/bin/python -m tests.e2e.community_report
```

비표준 기본 포트(8230) + 격리 temp dir 라 je-empty(:8200)·실커뮤니티에 절대 닿지 않는다.
판정 산출물: `tests/e2e/results/community-e2e-<ts>.json` (verdict) + `community-e2e-store-<ts>.json`
(served snapshot) + `community-report-<ts>.{md,json}` (포트폴리오 리포트).

### 구조
```
tests/e2e/
├── runner.py           ← 오케스트레이터
├── test_user_bot.py    ← Claude Haiku 테스트 유저
└── results/            ← JSON + 로그
```

### 동작
1. `qa` 커뮤니티 자동 생성/초기화 (DB + 유저 프로필 + `.clean-channels` 플래그)
2. Glimi 봇 시작 → 기존 디스코드 채널 삭제 → 튜토리얼 시작
3. 테스트 유저 봇 시작 → 신규 유저처럼 대화
4. 튜토리얼 완료 or 타임아웃
5. 로그 → 자동 판정 (프로필 중복, race condition, 태그 노출 등)

### 필요 설정
- `communities/qa/.env`: `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `TEST_BOT_TOKEN`
- 별도 디스코드 서버에 Glimi 봇 + 테스트 유저 봇 초대
- 유저 프로필 커스텀: `QA_USER_NAME`, `QA_USER_NICKNAME`, `QA_USER_AGE` 등
