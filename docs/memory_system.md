# 5-Layer Memory System (`src/core/memory.py`)

## 설계 원칙
각 에이전트마다 **통합 메모리 1개** + 엔티티 태그로 "누구에 관한 건지" 관리 (사람처럼). 저장은 영구, 주입만 budget 기반 선별.

## 레이어
- **L0 — Raw Archive** (영구): `conversations` 테이블, 평소 미주입
- **L1 — Working Window**: 최근 10~15 verbatim, 매 턴 주입
- **L2 — Episodic Chronicle** (영구): L1 (5 msg→글머리표) → L2 (5 L1→단락) → L3 (5 L2→월단위). 저장 cap 없음, 주입만 score top-N
- **L3 — Semantic Facts** (영구, entity-indexed): `agent_facts` 테이블. (subject, predicate, object) + supersession (`valid_to` 닫고 새 row)
- **L4 — Relationship State**: `relationships` snapshot + `relationship_history` 변곡점 delta
- **L5 — Pinned Memories**: `memories.is_pinned=1`, 오너/유나가 `pin_memory` 도구로 고정, 항상 주입

## 핵심 필드 (`memories` 테이블)
- `related_entities` (JSON): 이 기억이 누구에 관한 것인지
- `knows` (JSON): 이 기억을 직접 아는 사람 배열 (disclosure 제어)
  - `dm-X` → `[X, "owner"]` / `internal-dm-A-B` → `[A, B]`
- `importance` (1-10): retrieval 스코어
- `parent_memory_id`: L2/L3 origin 링크

## Disclosure 룰
- 주입 시 `owner ∉ knows` (internal 출처) 기억도 포함하되 "이 내용은 사적 대화 — 자발적으로 꺼내지 마" 마커 부착
- 에이전트가 자발적으로 공유하면 → 새 기억 생성 (knows 에 owner 추가)

## Cross-channel raw peek
- A 가 참여 중인 다른 running 채널의 최근 5 raw 를 매 턴 주입
- 3 채널 동시 대화 중일 때 A 가 internal-dm-A-B 대화를 dm-A 에서 자연스럽게 이어갈 수 있음

## Retrieval scoring
```
score = 0.4·semantic + 0.3·importance + 0.2·recency_decay + 0.1·relational
recency_decay = exp(-days/30)
```

## 주입 Budget (~800 토큰/턴)
- Pinned ~100 / Relationship ~50 / Working ~200 / Episodic(현) ~150
- Episodic(retrieved) ~100 / Facts ~100 / Cross-channel peek ~100

## 도구
- `recall_memory(query, entity, time_range)` — 에이전트가 직접 deep search
- `pin_memory(memory_id, reason)` — 오너/유나가 고정

## Async extraction
- 메시지 저장 즉시 반환 → 백그라운드 Haiku worker 큐 처리
- 단일 패스 JSON 추출: summary + mem_type + related_entities + importance + facts + relationship_delta
