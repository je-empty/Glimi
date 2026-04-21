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
python -m src.platform.accounts bootstrap       # admin/1234 + test/1234 초기 생성
python -m src.platform.accounts list
python -m src.platform.accounts add <user>
python -m src.platform.accounts grant <user> <community_id>

# 커뮤니티 관리 (CLI — 웹 UI 대체 중)
python -m src.community list
python -m src.community init <id>
python -m src.community export <id> <output_dir>
python -m src.community import <input_dir> <id>
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
