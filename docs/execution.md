# 실행 & QA

## 실행
```bash
./run.sh                              # 플랫폼 데몬 (FastAPI, :8000) — 기본
./run.sh --port 9000                  # 포트 변경
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

## 멀티 커뮤니티 지원
- 플랫폼(`community.platform`)이 단일 프로세스로 N 커뮤니티를 웹으로 서빙 (`GLIMI_TRANSPORT=web`).
- 커뮤니티별 격리는 `GLIMI_DATA_DIR`/`GLIMI_COMMUNITIES_DIR` 로 잡고, 라우팅은 `community_id` 로.
- 채널 전송은 transport 중립 seam(`Outbox`/`ChannelAdapter`) 위에서 web 어댑터(`community/adapters/web/channels.py`)가 처리.

## QA 자동 테스트

**자율 수행 절차:** `docs/qa_playbook.md` — "QA 진행해" 하면 이 문서 따라 사이클.
**토큰 누적 기록:** `tests/e2e/results/token_usage.md` — 매 런 델타 append.

```bash
.venv/bin/python -m tests.e2e.community_e2e --rounds 1   # 1회 (웹 자체 채팅)
./scripts/community_e2e.sh                                # 백그라운드 (권장)
```

### 웹 E2E (실서버 HTTP/WS 구동)

**웹 자체 채팅을 진짜 서버로 구동하는 E2E** — 현재 정본 경로:

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

### 구조 (현재 웹 E2E)
```
tests/e2e/
├── community_e2e.py        ← 커뮤니티 서버 spawn + 오너 에이전트 드라이브
├── community_owner_agent.py ← 개발자 자아 오너 에이전트
├── community_verdict.py    ← 구조 판정
├── community_report.py     ← 마크다운 리포트
└── results/                ← JSON + 로그
```

### 동작
1. 격리된 temp `GLIMI_DATA_DIR`/`GLIMI_COMMUNITIES_DIR` 에 `qa` 커뮤니티 자동 생성/초기화 (DB + 유저 프로필)
2. `community.platform` 서버 기동 (web transport) → 친구 DM 채널을 채팅 WebSocket 으로 구동
3. 오너 에이전트가 신규 오너처럼 인사→질문→후속 대화 진행
4. 라운드 완료 or 타임아웃
5. 로그 → 자동 판정 (프로필 중복, race condition, 태그 노출 등)

### 필요 설정
- 토큰/외부 계정 불필요 — 웹 자체 채팅으로 격리 temp dir 에서 셀프 구동.
- 유저(오너) 프로필 커스텀: `QA_OWNER_NAME`, `QA_OWNER_NICKNAME`, `QA_OWNER_AGE` 등
