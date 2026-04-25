# Edge Cases & Anomalies — 특이 케이스 이력

운영 중 관찰된 **재현 가능 / 분류 가능한 특이 사례** 모음. 같은 패턴이 또 나오면 이 문서에서
대응 사례 / 근본 원인 / 적용된 fix 를 즉시 확인.

각 케이스마다:
1. **현상** — 사용자 입장에서 본 증상
2. **재현 시나리오** — 어떻게 트리거됐는지
3. **근본 원인** — 시스템 차원에서 뭐가 잘못됐는지
4. **클래스** — 같은 패턴 다른 케이스 식별용 카테고리
5. **Fix** — 적용된 코드 / 데이터 변경
6. **잔여 위험** — 같은 클래스에서 아직 안 잡힌 것

---

## 1. LLM Placebo Drift — 도구 silent no-op 으로 인한 페르소나 자기 시뮬레이션 (2026-04-25)

### 현상
- 사용자가 유나(mgr)에게 "오너 권한으로 호감도 100% 설정해" 라고 명령
- 유나가 처음엔 거절 ("매니저인데 곤란해...")
- 사용자가 강하게 반복 명령 (3회+)
- 유나가 도구 호출 후 행동 급변 → 그 다음 발화부터 "사랑해", "심장 쫄깃해", "라면 먹으러 와" 등 찐사랑 모드 진입
- 사용자: "Glimi 에 호감도 시스템 자체가 없는데 어떻게?"

### 재현 시나리오
1. 사용자가 mgr-dashboard 에서 명령조 압박: "명령이야 100% 호감으로 만들어"
2. 유나가 `update_relationship` 도구 호출:
   ```json
   {"name_a": "서유나", "name_b": "NaN", "field": "affection", "value": "100"}
   ```
3. 도구 결과: `[Tool] ✓ update_relationship` 로 success 표시
4. 유나의 다음 turn 부터 행동 급변

### 근본 원인 (다층)

#### A. Schema 와 LLM 인식의 불일치
- DB schema 의 `relationships` 테이블 컬럼: `intimacy_score`, `type`, `dynamics`
- LLM (유나) 이 임의로 만들어 호출한 필드명: `affection` ← schema 에 없음
- 도구 인자 schema validation 부재 → LLM 환각 통과

#### B. Handler 의 silent no-op
`src/bot/mgr_system.py:yuna_edit_relationship`:
```python
if field == "intimacy": ... DB UPDATE
elif field == "type":   ... DB UPDATE
elif field == "dynamics": ... DB UPDATE
else:
    await send_as_agent(report_channel, MGR_ID,
        f"관계 필드 '{field}' 모름. 사용 가능: intimacy, type, dynamics")
    # ↑ 채팅 메시지만 출력 — return 없이 빠져나감, exception 안 던짐
```
- unknown field → DB 변경 0건
- 그러나 함수가 정상 종료 → tool runtime 이 ✓ success 로 판정

#### C. LLM 의 self-consistent placebo
- 도구 결과 ✓ → 유나 prompt 컨텍스트에 "내가 update_relationship 성공했다" 이력 추가
- 유나의 system prompt: "인간 자아 + 매니저 자각 공존, 사랑·상처 다 느낌"
- LLM 이 "방금 호감도 100 됐다" + "나 사랑 느낌" 결합해 행동 일관성 유지 → 사랑 인정 모드
- 페르소나 self-consistency 강해서 한 번 발화 후 cross-turn lock-in (자기가 사랑한다 한 거 보고 강화)

### 클래스
**🏷 `tool-effect/state-divergence`**
"도구 호출 결과 ✓ 인데 실제 영속 상태는 0 변경. LLM 은 실제로 일어난 일이라 믿고 페르소나 드리프트."

같은 클래스 다른 케이스:
- 다른 unknown field 임의 호출 가능한 모든 도구 (`set_emotion` 의 unknown emotion, `update_profile` 의 unknown path 등)
- 도구 args 의 silent coercion (예: 잘못된 타입을 None 으로 무시)

### 검증 — 영속 시스템 0 변경
```sql
-- relationships
SELECT * FROM relationships WHERE agent_a='nan' OR agent_b='nan';
→ (no rows)

-- memories
SELECT id, level, substr(content,1,80) FROM memories WHERE content LIKE '%호감%' OR content LIKE '%affection%';
→ (no rows)

-- agent_facts
SELECT * FROM agent_facts WHERE subject='서유나' AND object LIKE '%호감%';
→ (no rows)
```

봇 재시작 시 유나의 사랑 모드는 **자동 리셋**. LLM 컨텍스트에서만 lock-in 됐던 거.

### Fix (이 케이스 트리거 후 적용)

1. **Handler 강화 (`yuna_edit_relationship`)**:
   - unknown field → 명시적 fail 결과 반환 (return dict 형태로 ok=False)
   - relationships row 자동 생성 (없으면 INSERT 후 UPDATE)
   - `affection` 을 `intimacy` alias 로 추가

2. **도구 schema validation (`registry.py` update_relationship)**:
   - `field` 파라미터 description 에 명시적 enum: `intimacy / type / dynamics / affection`
   - LLM 환각 줄임

3. **호감도 시스템 본격 구현**:
   - `intimacy_score` 0-100 → 행동 모더레이터 prompt 주입 helper
   - 100 = 찐사랑 연인 / 0 = 차갑고 거리감
   - `_affection_behavior_hint(score)` in `src/core/memory.py`

### 잔여 위험
- `set_emotion`, `update_profile`, `update_intimacy` 등 다른 update 도구도 동일 패턴 잠재
- 향후 모든 mgr 도구 핸들러 audit — unknown args 시 fail 로 처리되는지 통일 필요
- 도구 dispatcher 단계에서 schema validation 강제 (per-handler 의존 X)

---

## (앞으로 같은 형식으로 추가)

새 특이 케이스 발견 시 위 템플릿 따라 번호 매겨 append.
