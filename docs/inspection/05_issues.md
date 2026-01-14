# AX 시스템 이슈 추적

**작성일**: 2026-01-02
**최종 수정**: 2026-01-05
**Phase**: 99.4 (엔티티 타입 키워드 필터링)

---

## 0. 해결된 이슈 (Phase 99.4)

### 0.0 엔티티 타입 키워드가 검색에 포함되는 문제

| 항목 | 내용 |
|------|------|
| **ID** | ISSUE-99.4-001 |
| **발견일** | 2026-01-05 |
| **해결일** | 2026-01-05 |
| **심각도** | High |
| **영향** | 검색 정확도 향상, 불필요한 결과 제거 |

**증상:**
- "수소연료전지 특허 검색" 질문 시 keywords가 `["수소연료전지", "특허"]`로 추출
- "특허"가 검색 키워드로 사용되어 "특허 관리시스템", "특허 침해 확인" 등 관련 없는 결과 포함

**원인:**
- LLM이 반환한 keywords에서 엔티티 타입 단어("특허", "과제", "장비" 등)를 필터링하는 후처리 코드 부재
- 국가 단어 필터링은 있으나 엔티티 타입 단어 필터링은 없었음

**해결:**
```python
# analyzer.py - Phase 99.4: 엔티티 타입 키워드 필터링
ENTITY_TYPE_STOPWORDS = {
    "특허", "출원", "발명", "등록", "특허권", "지식재산", "명세서",
    "과제", "연구과제", "프로젝트", "연구", "연구개발",
    "장비", "기기", "설비", "인프라", "시설", "연구장비", "실험장비",
    "공고", "사업공고", "입찰", "모집",
    "제안서", "제안", "사업계획",
    "검색", "조회", "목록", "리스트", "찾아", "알려"
}

keywords = [kw for kw in keywords if kw not in ENTITY_TYPE_STOPWORDS]
```

**결과:**
- 수정 전: `["수소연료전지", "특허"]`
- 수정 후: `["수소연료전지"]` ✅

**수정 파일:**
- `workflow/nodes/analyzer.py`: 라인 755-778에 엔티티 타입 키워드 필터링 추가

---

## 0.1 해결된 이슈 (Phase 99.3)

### 0.0 프론트엔드 시각화 데이터 누락

| 항목 | 내용 |
|------|------|
| **ID** | ISSUE-99.3-001 |
| **발견일** | 2026-01-02 |
| **해결일** | 2026-01-02 |
| **심각도** | High |
| **영향** | Sources 탭, Graph 탭, RAG 배지 정상 표시 |

**증상:**
- Sources 탭: 빈 배열 표시
- Graph 탭: 그래프 데이터 없음
- RAG 결과 카드: community/pagerank 배지 없음

**원인:**
1. `streaming.py`: done 이벤트에서 sources가 항상 빈 배열
2. `streaming.py`: rag_complete 이벤트의 top_results에 metadata 미포함
3. `MessageVisualizationPanel`: 빈 sources 시 패널 숨김

**해결:**
```python
# streaming.py - Phase 99.3: RAG 메타데이터 추가
top_results.append({
    "node_id": r.get("node_id", ""),
    "name": r.get("name", ""),
    "entity_type": r.get("entity_type", ""),
    "score": round(r.get("score", 0), 3),
    "metadata": {
        "community": metadata.get("community"),
        "pagerank": metadata.get("pagerank"),
        "connections": metadata.get("connections"),
        "content": (r.get("content", "") or "")[:200]
    }
})

# streaming.py - Phase 99.3: done 이벤트에 sources 구성
sources = []
if sql_result and sql_result.success:
    sources.append({"type": "sql", "count": sql_result.row_count, ...})
if rag_results:
    sources.append({"type": "rag", "count": len(rag_results), ...})
if graph_results:
    sources.append({"type": "graph", "count": len(graph_results)})
```

**수정 파일:**
- `api/streaming.py`: RAG 메타데이터 및 sources 구성
- `frontend/types/workflow.ts`: RAGResultMetadata 타입 추가
- `frontend/components/visualization/MessageVisualizationPanel.tsx`: 소스 처리 개선

---

## 0.1 해결된 이슈 (Phase 99)

### 0.1.1 장비 검색 전략 개선

| 항목 | 내용 |
|------|------|
| **ID** | ISSUE-99-001 |
| **발견일** | 2026-01-02 |
| **해결일** | 2026-01-02 |
| **심각도** | High |
| **영향** | 장비 검색 정확도 향상, 다중 필드 검색 지원 |

**증상:**
- 장비 검색 시 SQL 직접 쿼리만 사용
- ES 인덱스 `ax_equipments` 미활용
- 장비명(`conts_klang_nm`)만 검색

**원인:**
- `EquipmentKPILoader`가 SQL만 사용
- ES/Qdrant 사전 탐색 없음

**해결:**
```python
# sql_executor.py - Phase 99: ES→SQL 확장 패턴
def _execute_equipment_recommendation():
    # 1. ES 다중 필드 검색 (장비명, 설명, 스펙, KPI, 기관명)
    es_results = _search_equipment_es(keywords, region, limit=50)

    # 2. Qdrant 벡터 검색
    qdrant_results = _search_equipment_qdrant(keywords, limit=30)

    # 3. 후보 ID 추출
    candidate_ids = set()
    for r in es_results + qdrant_results:
        candidate_ids.add(r.get("conts_id"))

    # 4. SQL로 상세 정보 확장
    sql = _build_equipment_sql_by_ids(candidate_ids, region)
```

---

### 0.2 SQL 스키마 불일치 수정

| 항목 | 내용 |
|------|------|
| **ID** | ISSUE-99-002 |
| **발견일** | 2026-01-02 |
| **해결일** | 2026-01-02 |
| **심각도** | Medium |
| **영향** | SQL 오류 감소 |

**수정 파일:**
1. `sql/sql_prompts.py`: `region_code` → `address_dosi`
2. `workflow/prompts/schema_context.py`:
   - f_equipments: `equip_mdel_nm`, `equip_spec`, `address_dosi`, `kpi_nm_list` 추가
   - f_ancm_evalp: `eval_score` → `eval_score_num`
   - f_gis: `pnu` 컬럼 및 지역코드 설명 추가

---

### 0.3 PNU 기반 지역 검색

| 항목 | 내용 |
|------|------|
| **ID** | ISSUE-99-003 |
| **발견일** | 2026-01-02 |
| **해결일** | 2026-01-02 |
| **심각도** | Medium |
| **영향** | 지역 필터 정확도 향상 |

**증상:**
- `address_dosi` 컬럼 값이 일관되지 않음
- 지역 필터가 정확히 적용되지 않는 경우 발생

**해결:**
```python
# sql_executor.py - Phase 99.2: PNU 기반 지역 필터
PNU_REGION_MAP = {
    '11': '서울', '26': '부산', '27': '대구', '28': '인천',
    '29': '광주', '30': '대전', '31': '울산', '36': '세종',
    '41': '경기', '42': '강원', '43': '충북', '44': '충남', ...
}

# 지역 검색 시 f_gis.pnu 앞 2자리로 필터
region_condition = f"""
    AND EXISTS (
        SELECT 1 FROM f_gis g
        WHERE g.conts_id = e.conts_id
        AND g.pnu LIKE '{pnu_code}%'
    )
"""
```

---

## 1. 해결된 이슈 (Phase 98)

### 1.1 장비 쿼리 오분류

| 항목 | 내용 |
|------|------|
| **ID** | ISSUE-98-001 |
| **발견일** | 2026-01-02 |
| **해결일** | 2026-01-02 |
| **심각도** | High |
| **영향** | Easy 테스트 80점 → 100점 |

**증상:**
- "표면단차측정기 보유 기관" → query_type="rag"로 오분류
- "경기도 광탄성시험기" → query_type="rag"로 오분류

**원인:**
- LLM이 장비 조회 질문을 개념 설명으로 오해
- 규칙 기반 사전 분류 부재

**해결:**
```python
# analyzer.py:430
def _check_equipment_query(query: str) -> Dict[str, Any] | None:
    """Phase 98: 장비 관련 쿼리 규칙 기반 분류"""
    equip_keywords = ["장비", "측정기", "시험기", "분석기", ...]
    action_keywords = ["보유", "찾", "추천", "검색", ...]

    if has_equip and (has_action or has_region):
        return {"query_type": "sql", "entity_types": ["equip"], ...}
```

---

### 1.2 GraphRAG 초기화 스킵

| 항목 | 내용 |
|------|------|
| **ID** | ISSUE-98-002 |
| **발견일** | 2026-01-02 |
| **해결일** | 2026-01-02 |
| **심각도** | Medium |
| **영향** | 그래프 교차 검증 미실행 |

**증상:**
```
WARNING: Phase 95: graph_builder 미초기화, 그래프 검색 스킵
```

**원인:**
- `get_graph_rag()` 호출 시 `initialize()` 미호출
- `graph_builder`가 None 상태로 유지

**해결:**
```python
# graph_rag.py:792
def get_graph_rag() -> GraphRAG:
    """Phase 98: 자동 초기화"""
    global _graph_rag_instance
    if _graph_rag_instance is None:
        _graph_rag_instance = GraphRAG()
        # Phase 98: 첫 호출 시 기본 초기화 수행
        try:
            _graph_rag_instance.initialize(graph_id="713365bb", project_limit=500)
        except Exception as e:
            logger.warning(f"Phase 98: 자동 초기화 실패: {e}")
    return _graph_rag_instance
```

---

### 1.3 Equipment Loader 스키마 불일치

| 항목 | 내용 |
|------|------|
| **ID** | ISSUE-98-003 |
| **발견일** | 2026-01-02 |
| **해결일** | 2026-01-02 |
| **심각도** | High |
| **영향** | 장비 검색 0건 반환 |

**증상:**
- SQL 실행 시 "table f_equips does not exist" 오류
- 컬럼명 불일치로 데이터 미반환

**원인:**
- 테이블명: `f_equips` → 실제: `f_equipments`
- 컬럼명: `equip_nm` → 실제: `conts_klang_nm`
- 좌표: `lat/lng` → 실제: `x_coord/y_coord`

**해결:**
```python
# equipment_kpi_loader.py:62
self.table_name = "f_equipments"

# 쿼리 수정
query = """
    SELECT
        e.conts_klang_nm AS equipment_name,
        e.org_nm AS org_name,
        e.equip_mdel_nm AS model,
        ...
    FROM f_equipments e
    LEFT JOIN f_gis g ON e.conts_id = g.conts_id
"""
```

---

## 2. 미해결 이슈

### 2.1 SQL Agent 스키마 불일치 (부분 해결)

| 항목 | 내용 |
|------|------|
| **ID** | ISSUE-OPEN-001 |
| **발견일** | 2026-01-02 |
| **심각도** | Low |
| **상태** | 부분 해결 (Phase 99) |

**증상:**
```
ERROR:sql.sql_agent:SQL 실행 오류: column "rsrh_expn" does not exist
```

**Phase 99 수정:**
- `sql/sql_prompts.py`: region_code → address_dosi 수정
- `workflow/prompts/schema_context.py`: f_equipments, f_ancm_evalp, f_gis 스키마 보완

**남은 작업:**
- `rsrh_expn` 등 기타 존재하지 않는 컬럼 정리 필요
- sql/sql_agent.py 내 스키마 정보 전체 점검

---

### 2.2 추상적 키워드 매핑 부재 (부분 해결)

| 항목 | 내용 |
|------|------|
| **ID** | ISSUE-OPEN-002 |
| **발견일** | 2026-01-02 |
| **심각도** | Low |
| **상태** | 부분 해결 (Phase 99) |

**증상:**
```
WARNING:workflow.loaders.equipment_kpi_loader:KPI 키워드가 없습니다.
WARNING:workflow.loaders.base_loader:EquipmentKPILoader: DB에 데이터 없음
```

**Phase 99 개선:**
- ES 다중 필드 검색으로 추상 키워드 → 관련 장비 탐색 가능
- Qdrant 벡터 유사도 검색으로 의미적 매칭 지원
- KPI 키워드 없어도 ES→SQL 확장 패턴으로 검색 가능

**남은 작업:**
- KPI 키워드 사전 확장
- 유사어/동의어 매핑 테이블 추가

---

### 2.3 응답 시간 편차

| 항목 | 내용 |
|------|------|
| **ID** | ISSUE-OPEN-003 |
| **발견일** | 2026-01-02 |
| **심각도** | Medium |
| **상태** | Open |

**증상:**
- 최소: 8,870ms (마찰견뢰도 장비)
- 최대: 65,764ms (표면단차측정기)
- 편차: 7배 이상

**원인:**
- Loader 성공: 빠름 (LLM 호출 없음)
- Loader 실패 → SQL Agent fallback: 느림 (LLM 재호출)

**영향:**
- 사용자 경험 불일치
- 일부 케이스에서 타임아웃 위험

**권장 조치:**
1. Loader 커버리지 확대
2. SQL Agent 캐싱 도입
3. 병렬 처리 최적화

---

## 3. 모니터링 포인트

### 3.1 핵심 로그 패턴

| 패턴 | 의미 | 조치 |
|------|------|------|
| `Phase 98: 장비 검색 쿼리 감지 → SQL 분류` | 장비 규칙 분류 적용 | 정상 |
| `Phase 98: GraphRAG 자동 초기화 완료` | 그래프 초기화 성공 | 정상 |
| `Phase 96: 그래프 교차 검증 완료` | 교차 검증 수행 | 정상 |
| `KPI 키워드가 없습니다` | Loader 키워드 미스 | 사전 확장 필요 |
| `column does not exist` | 스키마 불일치 | 스키마 동기화 필요 |

### 3.2 품질 지표

| 지표 | 기준 | 현재 | 상태 |
|------|------|------|------|
| 성공률 | 95% | 100% | OK |
| 평균 점수 | 85점 | 100점 | OK |
| 테이블 포함률 | 90% | 100% | OK |
| 평균 응답시간 | <30초 | ~30초 | 주의 |

---

## 4. 개선 로드맵

### 4.1 단기 (1주 내)

| 우선순위 | 작업 | 예상 효과 |
|----------|------|----------|
| P1 | SQL Agent 스키마 동기화 | 에러 로그 감소 |
| P2 | KPI 키워드 사전 확장 | Loader 히트율 증가 |

### 4.2 중기 (1개월 내)

| 우선순위 | 작업 | 예상 효과 |
|----------|------|----------|
| P1 | 응답 시간 최적화 | 평균 30초 → 10초 |
| P2 | Loader 커버리지 확대 | fallback 빈도 감소 |
| P3 | 유사어 매핑 도입 | 검색 정확도 향상 |

### 4.3 장기 (분기 내)

| 우선순위 | 작업 | 예상 효과 |
|----------|------|----------|
| P1 | 캐싱 레이어 도입 | 반복 쿼리 가속 |
| P2 | 자동 스키마 동기화 | 유지보수 비용 감소 |
| P3 | A/B 테스트 프레임워크 | 품질 지속 모니터링 |

---

## 5. 점검 결론

### 5.1 시스템 상태

| 영역 | 상태 | 비고 |
|------|------|------|
| 기능 정확도 | **양호** | 100% 성공률 |
| 응답 품질 | **양호** | 100점 평균 |
| 응답 시간 | **주의** | 편차 큼 |
| 에러 처리 | **양호** | fallback 정상 |
| 코드 품질 | **양호** | Phase 98 수정 적용 |

### 5.2 권장 사항

1. **즉시 조치 필요**
   - SQL Agent 스키마 정보 업데이트

2. **주간 모니터링**
   - 응답 시간 추세 확인
   - Loader 히트율 확인

3. **월간 점검**
   - 전체 테스트 스위트 실행
   - 품질 지표 리포트 생성

---

## 6. 문서 목록

| 문서 | 경로 | 내용 |
|------|------|------|
| 아키텍처 개요 | [01_architecture.md](./01_architecture.md) | 전체 구조, 노드 목록 |
| 기능요소 상세 | [02_components.md](./02_components.md) | 핵심 코드 원본 |
| 연결 분석 | [03_connections.md](./03_connections.md) | 데이터 흐름, 라우팅 |
| 테스트 결과 | [04_test_results.md](./04_test_results.md) | 실행 결과, 점수 |
| 이슈 추적 | [05_issues.md](./05_issues.md) | 해결/미해결 이슈 |

---

**문서 작성 완료**: 2026-01-02
**다음 점검 예정**: 2026-01-09
