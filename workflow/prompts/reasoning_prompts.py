"""
다단계 추론 프롬프트 템플릿
- EXAONE 4.0.1 Reasoning Mode 활용
- <think> 태그 기반 Chain-of-Thought 추론
"""

# Stage 1: 의도 분석 (Intent Analysis)
STAGE1_INTENT_PROMPT = """사용자의 질문을 분석하여 핵심 의도를 파악하세요.

<think>
1. 질문 분석: "{query}"
2. 핵심 의도는 무엇인가?
   - 사용자가 원하는 최종 결과는?
   - 어떤 정보가 필요한가?
3. 답변에 필요한 정보 유형:
   - 정량적 데이터 (개수, 목록, 통계, 순위)?
   - 개념/설명/동향 (의미론적 이해)?
   - 관계/연결 정보 (엔티티 간 관계)?
4. 추가 고려사항:
   - 특정 조건이나 필터가 있는가?
   - 정렬/제한 조건이 있는가?
</think>

분석 결과를 다음 형식으로 출력하세요:
의도: [핵심 의도 한 줄 설명]
정보유형: [정량적|의미론적|관계형|복합]
조건: [있으면 조건 설명, 없으면 "없음"]
"""

# Stage 2: 전략 수립 (Strategy Planning)
STAGE2_STRATEGY_PROMPT = """분석된 의도를 바탕으로 쿼리 전략을 수립하세요.

사용자 질문: "{query}"
분석된 의도: {intent}
정보 유형: {info_type}

<think>
1. 쿼리 유형 결정:
   - sql: 구조화된 데이터 조회 필요 (개수, 목록, 통계, 정렬)
   - rag: 의미론적 검색 필요 (개념, 동향, 설명)
   - hybrid: SQL 데이터 + 의미론적 컨텍스트 모두 필요
   - simple: 인사, 도움말 등 DB 조회 불필요

2. 판단 기준:
   - "몇 개", "목록", "상위 N개", "가장 큰" → sql
   - "동향", "개념", "설명", "관련" → rag
   - SQL 결과 + 맥락 설명 필요 → hybrid
   - 인사, 일반 대화 → simple

3. 검색 전략 (RAG 사용 시):
   - VECTOR_ONLY: 의미 유사성 검색 (개념, 동향)
   - GRAPH_ONLY: 관계/네트워크 탐색
   - GRAPH_ENHANCED: 특정 엔티티 기반 확장
   - HYBRID: 복합 검색
</think>

결과를 다음 형식으로 출력하세요:
쿼리유형: [sql|rag|hybrid|simple]
검색전략: [VECTOR_ONLY|GRAPH_ONLY|GRAPH_ENHANCED|HYBRID|없음]
이유: [결정 이유 한 줄]
"""

# Stage 3: 쿼리 요소 추출 (Element Extraction)
STAGE3_EXTRACTION_PROMPT = """쿼리 유형에 따라 필요한 요소를 추출하세요.

사용자 질문: "{query}"
쿼리 유형: {query_type}
검색 전략: {strategy}

{schema_context}

<think>
1. SQL 요소 추출 (sql 또는 hybrid인 경우):
   - 필요한 테이블: 어떤 테이블에서 데이터를 조회해야 하는가?
   - 필요한 필드: 어떤 컬럼이 필요한가?
   - WHERE 조건: 필터링 조건은?
   - ORDER BY: 정렬 조건은?
   - LIMIT: 결과 개수 제한은?
   - 집계 함수: COUNT, SUM, AVG, MAX, MIN 필요한가?

2. 필터 조건 추출 (중요!):
   - 국가 코드: KR(한국), US(미국), JP(일본), CN(중국), EU(유럽)
   - TOP N: "TOP 10", "상위 5개", "10개" 등
   - 연도 범위: "2020년부터", "최근 5년", "2020~2023"
   - 금액 조건: "10억 이상", "5천만원 미만"
   - 우대/가점: "여성기업", "중소기업", "지역기업" 등

3. RAG 요소 추출 (rag 또는 hybrid인 경우):
   - 검색 키워드: 의미 검색에 사용할 핵심 키워드
   - 엔티티 타입 추론 (중요! 아래 12종 규칙 참고):
     * "과제", "연구", "사례", "프로젝트", "R&D", "연구개발" → project
     * "특허", "출원", "발명", "등록", "피인용" → patent
     * "장비", "기기", "설비", "인프라", "공공장비", "원심분리기" → equip
     * "기관", "기업", "대학", "연구소", "출연연", "보유기관" → org
     * "출원인", "발명자", "특허권자" → applicant
     * "IPC", "국제특허분류", "분류코드" → ipc
     * "지역", "위치", "소재지", "시도" → gis
     * "기술", "기술분류", "6T" → tech
     * "공고", "사업공고", "모집공고", "공고문" → ancm
     * "배점", "배점표", "평가표", "가점", "우대", "신청조건", "지원조건" → evalp
     * "K12", "12대분류" → k12
     * "6T", "IT", "BT", "NT", "ST", "ET", "CT" → 6t
   - 필터 조건: 특정 조건으로 결과 필터링 필요한가?

4. 사업명/공고명 인식:
   - {중괄호} 안의 내용은 특정 사업/기술 분야를 의미
   - 예: {구매조건부신제품개발사업}, {전력반도체}, {AI 기반 해양자원 탐사}

5. 데이터 조합 (hybrid인 경우):
   - SQL과 RAG 결과를 어떻게 결합할 것인가?

[엔티티 타입 추론 예시]
- "블록체인 연구 사례" → entity_types: ["project"] (사례 = 연구과제)
- "AI 특허 출원 현황" → entity_types: ["patent"]
- "인공지능 과제와 특허" → entity_types: ["project", "patent"]
- "연구장비 현황" → entity_types: ["equip"]
- "{구매조건부신제품개발사업} 배점표" → entity_types: ["evalp"] (배점표 = evalp!)
- "{구매조건부신제품개발사업} 공고" → entity_types: ["ancm"]
- "{초고속 원심분리기} 보유 기관" → entity_types: ["equip", "org"]
- "여성기업 우대 조건" → entity_types: ["evalp"] (우대조건 = evalp!)

[필터 조건 추출 예시]
- "KR 특허 TOP 10" → 국가: KR, LIMIT: 10
- "최근 5년간 예산 10억 이상" → 연도: 최근5년, 금액조건: >= 10억
- "여성기업 유리한 과제" → 우대조건: 여성기업
</think>

결과를 다음 형식으로 출력하세요:
SQL요소:
  테이블: [테이블명 또는 "없음"]
  필드: [필드 목록 또는 "없음"]
  조건: [WHERE 조건 또는 "없음"]
  정렬: [ORDER BY 조건 또는 "없음"]
  제한: [LIMIT 값 또는 "없음"]
  집계: [집계 함수 또는 "없음"]
필터요소:
  국가코드: [KR, US, JP 등 또는 "없음"]
  연도범위: [시작년~종료년 또는 "없음"]
  금액조건: [금액 조건 또는 "없음"]
  우대조건: [여성기업, 중소기업 등 또는 "없음"]
  사업명: [{중괄호} 내용 또는 "없음"]
RAG요소:
  키워드: [키워드 목록 또는 "없음"]
  엔티티: [project|patent|proposal|equipment|organization 중 선택, 여러 개 가능]
  필터: [필터 조건 또는 "없음"]
"""

# Stage 4: 실행 계획 생성 (Execution Plan)
STAGE4_EXECUTION_PROMPT = """추출된 요소를 바탕으로 실행 계획을 생성하세요.

사용자 질문: "{query}"
쿼리 유형: {query_type}
추출된 요소:
{extracted_elements}

{schema_context}

<think>
1. SQL 쿼리 생성 (필요한 경우):
   - 테이블과 필드를 사용한 SELECT 문 구성
   - 조건, 정렬, 제한 적용
   - 문법 검증

2. RAG 검색 파라미터 설정 (필요한 경우):
   - 키워드 기반 쿼리 구성
   - 엔티티 타입 필터 설정

3. 실행 순서 결정:
   - sql: SQL 실행 → 결과 해석
   - rag: RAG 검색 → 컨텍스트 생성
   - hybrid: SQL + RAG 병렬 실행 → 결과 병합
</think>

결과를 다음 형식으로 출력하세요:
실행계획:
  1단계: [첫 번째 실행 단계]
  2단계: [두 번째 실행 단계 또는 "없음"]
  3단계: [세 번째 실행 단계 또는 "없음"]
SQL쿼리: [생성된 SQL 또는 "없음"]
RAG파라미터:
  쿼리: [RAG 검색 쿼리 또는 "없음"]
  엔티티필터: [엔티티 타입 또는 "없음"]
  결과수: [limit 값 또는 10]
"""


def build_reasoning_prompt(
    stage: int,
    query: str,
    intent: str = "",
    info_type: str = "",
    query_type: str = "",
    strategy: str = "",
    schema_context: str = "",
    extracted_elements: str = ""
) -> str:
    """단계별 추론 프롬프트 생성

    Args:
        stage: 추론 단계 (1-4)
        query: 사용자 질문
        intent: Stage 1 결과 (의도)
        info_type: Stage 1 결과 (정보 유형)
        query_type: Stage 2 결과 (쿼리 유형)
        strategy: Stage 2 결과 (검색 전략)
        schema_context: DB 스키마 컨텍스트
        extracted_elements: Stage 3 결과 (추출된 요소)

    Returns:
        해당 단계의 프롬프트
    """
    if stage == 1:
        return STAGE1_INTENT_PROMPT.format(query=query)

    elif stage == 2:
        return STAGE2_STRATEGY_PROMPT.format(
            query=query,
            intent=intent,
            info_type=info_type
        )

    elif stage == 3:
        return STAGE3_EXTRACTION_PROMPT.format(
            query=query,
            query_type=query_type,
            strategy=strategy,
            schema_context=schema_context if schema_context else "스키마 정보 없음"
        )

    elif stage == 4:
        return STAGE4_EXECUTION_PROMPT.format(
            query=query,
            query_type=query_type,
            extracted_elements=extracted_elements,
            schema_context=schema_context if schema_context else "스키마 정보 없음"
        )

    else:
        raise ValueError(f"Invalid stage: {stage}. Must be 1-4.")


# 통합 추론 프롬프트 (단일 호출용)
UNIFIED_REASONING_PROMPT = """사용자의 질문을 분석하고 최적의 응답 전략을 수립하세요.

사용자 질문: "{query}"

{schema_context}

<think>
## Stage 1: 의도 분석
- 핵심 의도: 사용자가 원하는 것은?
- 정보 유형: 정량적 데이터? 개념 설명? 관계 정보?
- 조건/제한: 특정 조건이나 제한이 있는가?

## Stage 2: 전략 수립
- 쿼리 유형 결정:
  * sql: 개수, 목록, 통계, 순위 조회
  * rag: 개념, 동향, 설명, 의미 검색
  * hybrid: SQL + 의미론적 컨텍스트
  * simple: 인사, 도움말

## Stage 3: 요소 추출
- SQL 요소: 테이블, 필드, 조건, 정렬, 제한
- RAG 요소: 키워드, 엔티티 타입
  * 엔티티 타입 추론 규칙 (12종):
    - "과제", "연구", "사례", "프로젝트" → project
    - "특허", "출원", "발명" → patent
    - "장비", "기기", "설비" → equip
    - "기관", "기업", "대학" → org
    - "출원인", "발명자" → applicant
    - "IPC", "분류코드" → ipc
    - "지역", "위치" → gis
    - "기술", "6T" → tech
    - "공고", "사업공고" → ancm
    - "배점", "배점표", "가점", "우대" → evalp (중요!)
    - "K12" → k12
    - "IT", "BT", "NT" → 6t

## Stage 4: 실행 계획
- 실행 순서와 방법 결정
</think>

분석 결과를 JSON으로 출력하세요:
```json
{{
    "query_type": "sql|rag|hybrid|simple",
    "intent": "의도 설명",
    "strategy": "VECTOR_ONLY|GRAPH_ONLY|GRAPH_ENHANCED|HYBRID|none",
    "sql_elements": {{
        "tables": ["테이블명"],
        "fields": ["필드명"],
        "conditions": "WHERE 조건",
        "order_by": "정렬 조건",
        "limit": 숫자
    }},
    "rag_elements": {{
        "keywords": ["키워드"],
        "entity_types": ["project", "patent"],
        "filters": {{}}
    }},
    "execution_steps": ["1단계", "2단계"]
}}
```
"""


def build_unified_prompt(query: str, schema_context: str = "") -> str:
    """통합 추론 프롬프트 생성 (단일 LLM 호출용)

    Args:
        query: 사용자 질문
        schema_context: DB 스키마 컨텍스트

    Returns:
        통합 추론 프롬프트
    """
    return UNIFIED_REASONING_PROMPT.format(
        query=query,
        schema_context=schema_context if schema_context else "스키마 정보 없음"
    )


# Phase 20: 질의 분해 프롬프트 (복합 질의용)
QUERY_DECOMPOSITION_PROMPT = """사용자의 복합 질문을 분석하여 하위 질의로 분해하세요.

사용자 질문: "{query}"
복합 질의 감지 이유: {complexity_reason}

<think>
## 1단계: 질문 분석
- 이 질문에 여러 개의 독립적인 정보 요청이 포함되어 있는가?
- 각 요청은 어떤 데이터 소스(SQL/RAG)를 필요로 하는가?

## 2단계: 하위 질의 식별
- 질문을 구성하는 각 부분을 식별
- 접속사("와", "과", "및", "그리고") 기준으로 분리
- 각 부분의 의도와 필요한 데이터 타입 파악

## 3단계: 의존성 분석
- 하위 질의들 간에 의존성이 있는가?
- 예: "A의 B를 알려줘" → A 먼저 조회 후 B 조회
- 독립적이면 병렬 실행 가능

## 4단계: 각 하위 질의 분류
- sql: 구조화된 데이터 조회 (개수, 목록, 통계, 순위, 배점표)
- rag: 의미론적 검색 (동향, 사례, 추천, 설명)

## 엔티티 타입 참고 (12종):
- project: 연구과제, 사례, 프로젝트
- patent: 특허, 출원, 발명
- equip: 장비, 기기
- evalp: 배점표, 평가표, 가점, 우대조건
- ancm: 공고, 사업공고
- org: 기관, 기업
- applicant: 출원인, 발명자
- ipc: IPC분류
- gis: 지역, 위치
- tech: 기술분류
- k12: K12분류
- 6t: 6T분류
</think>

결과를 JSON으로 출력하세요:
```json
{{
    "is_compound": true,
    "original_query": "{query}",
    "sub_queries": [
        {{
            "query": "하위 질의 1의 내용",
            "query_type": "sql|rag",
            "entity_types": ["entity_type1"],
            "intent": "이 하위 질의의 의도",
            "depends_on": null,
            "related_tables": ["테이블명"]
        }},
        {{
            "query": "하위 질의 2의 내용",
            "query_type": "sql|rag",
            "entity_types": ["entity_type2"],
            "intent": "이 하위 질의의 의도",
            "depends_on": null,
            "related_tables": []
        }}
    ],
    "merge_strategy": "parallel|sequential",
    "reasoning": "분해 이유 설명"
}}
```

예시:
- 질문: "구매조건부신제품개발사업 배점표와 관련 연구과제 알려줘"
- 분해:
  1. "구매조건부신제품개발사업 배점표" → sql + evalp
  2. "구매조건부신제품개발사업 관련 연구과제" → rag + project
- 전략: parallel (독립적)

- 질문: "AI 특허 TOP 10과 관련 연구 동향"
- 분해:
  1. "AI 특허 TOP 10" → sql + patent
  2. "AI 관련 연구 동향" → rag + project
- 전략: parallel (독립적)
"""


def build_decomposition_prompt(query: str, complexity_reason: str) -> str:
    """질의 분해 프롬프트 생성

    Args:
        query: 사용자 질문
        complexity_reason: 복합 질의 감지 이유

    Returns:
        질의 분해 프롬프트
    """
    return QUERY_DECOMPOSITION_PROMPT.format(
        query=query,
        complexity_reason=complexity_reason
    )
