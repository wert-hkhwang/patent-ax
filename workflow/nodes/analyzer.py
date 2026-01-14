"""
쿼리 분석 노드
- Phase 7: LLM 기반 의미 분류 (키워드 규칙 제거)
- LLM 기반 쿼리 유형 분류 (sql/rag/hybrid/simple)
- 의도 추출 및 엔티티 타입 식별
- 관련 테이블 추론

NOTE: Phase 7에서 규칙 기반 분류 제거됨
- is_complex_query(): DEPRECATED (사용하지 않음)
- _check_rule_based_query(): DEPRECATED (사용하지 않음)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import logging
import re
from typing import Dict, List, Any, Optional, Tuple

from workflow.state import AgentState
from llm.llm_client import get_llm_client

logger = logging.getLogger(__name__)


# Phase 90.2: Ranking 유형 분류를 위한 키워드 및 패턴
# 복잡한 ranking (SQL 필수) vs 단순 ranking (ES/Vector 우선)
COMPLEX_RANKING_KEYWORDS = {
    # 계산/비율 키워드 - SQL 집계 함수 필요
    "calculation": ["등록률", "비율", "증가율", "점유율", "피인용", "인용수", "성장률", "평균"],
    # 집계 키워드 (단순 TOP N이 아닌 그룹화 필요)
    "aggregation": ["연도별", "연간", "추이", "변화", "분포", "현황", "통계"],
    # 복잡 필터 (다중 조건)
    "complex_filter": ["최근", "기간", "사이", "이상", "이하", "미만", "초과"],
}

COMPLEX_RANKING_PATTERNS = [
    r"\d{4}년.*\d{4}년",  # 연도 범위 (2020년부터 2023년)
    r"(KR|US|JP|CN|한국|미국|일본|중국).*(?:와|과|,|및).*(?:KR|US|JP|CN|한국|미국|일본|중국)",  # 다중 국가
    r"(?:등록|출원).*(?:기관|기업|회사).*(?:비교|대비)",  # 등록/출원 비교
]

# Reasoning Mode 사용 여부 설정
# Phase 105: EXAONE 4.0.1 추론 기능 활성화 (기본값 true로 변경)
# - enable_thinking=True + <think> 태그 기반 단계별 추론
# - EXAONE 4.0.1 공식 권장 파라미터: temperature=0.6, top_p=0.95
# - 복잡한 질의의 단계별 분해 정확도 향상 기대
USE_REASONING_MODE = os.getenv("USE_REASONING_MODE", "true").lower() == "true"

# Phase 64: 국가 키워드 매핑 상수
# 국가 키워드 → 국가 코드 변환 (keywords에서 제거 및 structured_keywords['country']로 이동)
COUNTRY_KEYWORDS = {
    "KR": ["한국", "국내", "대한민국", "자국", "kr", "KR"],
    "US": ["미국", "USA", "us", "US"],
    "JP": ["일본", "jp", "JP"],
    "CN": ["중국", "cn", "CN"],
    "EU": ["유럽", "eu", "EU"],
    "NOT_KR": ["해외", "타국", "외국"]
}

# 복합 질의 감지 패턴 (Phase 20)
COMPLEXITY_PATTERNS = {
    # 접속사 패턴 (공백 포함하여 정확히 매칭)
    "conjunctions": ["와 ", "과 ", "및 ", "그리고 ", " and "],
    # 다중 요청 동사
    "multi_request": ["알려주고", "해주고", "보여주고", "찾아주고", "추천해주고"],
    # 리스트 마커
    "list_markers": ["첫째", "둘째", "1)", "2)", "①", "②", "1.", "2."],
}

# 쿼리 분류 프롬프트 (Phase 36.1: 복합 의도 분해 추가)
QUERY_CLASSIFICATION_PROMPT = """질문의 **의도**를 분석하여 JSON으로 응답하세요.

## 핵심 원칙
키워드가 아닌 **문맥과 의도**로 분류:
- "출원인별 현황 분석해줘" → 그룹별 통계 = **aggregation**
- "국내 vs 해외 비교 분석해줘" → 두 대상 비교 = **comparison**
- "딥러닝 연구 동향" / "AI 특허 동향" → **trend_analysis** (반드시!)

```json
{{
    "query_type": "sql|rag|hybrid|simple",
    "query_subtype": "list|aggregation|trend_analysis|ranking|concept|compound|recommendation|comparison",
    "intent": "의도 설명",
    "entity_types": [],
    "keywords": ["핵심_키워드"],
    "related_tables": [],
    "is_aggregation": true|false,
    "is_compound": true|false,
    "sub_queries": [],
    "structured_keywords": {{"tech":[],"org":[],"country":[],"region":[],"filter":[],"metric":[]}}
}}
```

**[Phase 104] entity_types 결정 방식**:
entity_types는 질문에서 언급된 데이터 유형을 추론하세요:
- 특허/발명/출원/IP → "patent"
- 과제/연구/프로젝트/R&D → "project"
- 장비/기자재/설비/분석기기 → "equip"
- 공고/제안/RFP/사업공고 → "proposal"
- 여러 유형이 언급되면 모두 포함 (예: ["patent", "project"])
- 불명확하면 기본값 ["patent", "project"] 사용
- related_tables는 비워두세요 (빈 배열 [])

## query_subtype 분류:

| 유형 | 의도 | 패턴 |
|------|------|------|
| list | 목록 조회 | "알려줘/N개/목록" |
| aggregation | 통계/집계 | "~별 현황/추이/동향/분포" |
| trend_analysis | 동향 분석 | "~동향/기술동향/연구동향/특허동향" → **반드시 sql** |
| ranking | 순위 | "TOP N/가장/상위" |
| recommendation | 추천 | "추천/매칭/적합한" |
| comparison | 비교 | "A vs B/비교/차이" (대상 2개↑ 필수) |
| concept | 개념 | "~란/설명해줘/뭐야/어떤것이 있/무엇이 있/종류/유형" |
| compound | 복합 | 2개 이상 독립적 요청 |

## trend_analysis (동향 분석) - 중요!
"동향", "기술동향", "연구동향", "특허동향" 키워드가 있으면:
- query_type: **sql** (RAG 아님!)
- query_subtype: **trend_analysis**
- is_aggregation: **true**
- 필수 분석: 연도별 건수 추이 + 주요 수행기관 TOP 5
- 예: "딥러닝 연구 동향" → sql, trend_analysis, keywords=["딥러닝"], entity_types=["project"]
- 예: "인공지능 특허 동향" → sql, trend_analysis, keywords=["인공지능"], entity_types=["patent"]
- **"동향" 자체는 keywords에서 제외** (검색 키워드가 아님)

## is_compound 판단 (의미 기반 - 중요!):

compound는 **처리 방식(subtype)이 다른 독립적 요청**이 있을 때만 true:
- "연도별 추이와 최근 목록" → **compound=True** (aggregation + list = 다른 SQL)
- "TOP 5와 총 건수" → **compound=True** (ranking + aggregation = 다른 처리)

**compound=True (분해 필요) - 통합검색 핵심!**:
- **"AI 특허와 연구과제"** → compound=**True** (특허 검색 + 과제 검색 각각 수행 후 취합)
- **"인공지능 특허와 연구과제"** → compound=**True** (다른 테이블에서 각각 검색)
- **"딥러닝 관련 특허와 연구과제"** → compound=**True**
- 분해 예시:
```json
"sub_queries": [
    {{"intent": "특허 검색", "subtype": "list", "keywords": ["AI"], "entity_types": ["patent"]}},
    {{"intent": "연구과제 검색", "subtype": "list", "keywords": ["AI"], "entity_types": ["project"]}}
]
```

compound가 **아닌** 경우 (compound=False):
- "삼성과 LG 비교" → 1개 요청 (comparison subtype)
- "특허 목록과 출원인 정보" → 1개 요청 (JOIN으로 해결)
- "수소연료전지 특허" → 단일 엔티티 검색

**핵심 판단 기준**: **다른 엔티티 유형(특허+과제+제안서 등)**을 검색하면 compound=True

## 역량 보유 기관 검색 (Phase 104.3 - 핵심! 기관 집계)
**"~역량 보유 기관", "~개발 역량", "~분야 기관"** 질문은 반드시 **compound=True**:
- 특허 출원기관 + 과제 수행기관 + 제안서 참여기관 등 여러 소스에서 검색 필요
- **중요**: subtype을 **"ranking"**으로 설정 (기관별 집계 필요)
- 예: "수소연료전지 개발 역량을 보유하고 있는 기관은?"
```json
{{
  "is_compound": true,
  "query_subtype": "ranking",
  "entity_types": ["patent", "project"],
  "keywords": ["수소연료전지"],
  "sub_queries": [
    {{"intent": "특허 출원기관 TOP 20", "subtype": "ranking", "keywords": ["수소연료전지"], "entity_types": ["patent"], "aggregation_target": "organization"}},
    {{"intent": "과제 수행기관 TOP 20", "subtype": "ranking", "keywords": ["수소연료전지"], "entity_types": ["project"], "aggregation_target": "organization"}}
  ]
}}
```
- 예: "인공지능 분야 역량 있는 기관" → compound=True, ranking subtype, patent+project 검색
- **"X 특허와 연구과제"** → 다른 데이터 소스 검색 → compound=**True**, sub_queries로 분해
- 같은 엔티티 내 다른 분석 (aggregation+list) → compound=True

**기관 집계 subtype 구분** (중요!):
- "역량 보유 기관", "개발 기관", "~분야 기관" → **subtype=ranking** + **aggregation_target="organization"**
- 특허: 출원기관(patent_frst_appn)별 특허 수 집계
- 과제: 수행기관(f_proposal_orgn.orgn_nm)별 과제 수 집계 (주관/참여 구분)

## sub_queries (compound=true일 때만):
다른 subtype 또는 **다른 entity_types**면 분해:
```json
// 예1: 특허 + 과제 검색 (다른 entity_types)
"sub_queries": [
    {{"intent": "특허 검색", "subtype": "list", "keywords": ["AI"], "entity_types": ["patent"]}},
    {{"intent": "과제 검색", "subtype": "list", "keywords": ["AI"], "entity_types": ["project"]}}
]
// 예2: 다른 subtype
"sub_queries": [
    {{"intent": "연도별 추이", "subtype": "aggregation", "keywords": [...]}},
    {{"intent": "최근 목록", "subtype": "list", "keywords": [...]}}
]
```

## 긴 질문 분해 (Phase 91 - 중요!)
**질문이 길거나 여러 요청이 포함되면 분해**:

예시 질문:
"이미지 기반 특허맵 저작 엔진에 대한 역량 보유 기관 및 유사 역량을 가진 협력 가능 기관을 추천해주세요. 해당 분야 기술 동향도 알려주세요."

분해 결과:
```json
{{
  "is_compound": true,
  "keywords": ["특허맵"],
  "sub_queries": [
    {{"intent": "역량 보유 기관 검색", "subtype": "list", "keywords": ["특허맵"], "entity_types": ["proposal"]}},
    {{"intent": "협력 가능 기관 추천", "subtype": "recommendation", "keywords": ["특허맵"], "entity_types": ["proposal"]}},
    {{"intent": "기술 동향 분석", "subtype": "trend_analysis", "keywords": ["특허맵"], "entity_types": ["patent", "project"]}}
  ]
}}
```

**분해 기준**:
1. "및", "그리고", "또한", "~도 알려줘" 연결어 있으면 분해 검토
2. 서로 다른 조회 대상 (기관 목록 + 동향 분석 = 다름) → 분해
3. 질문 길이 > 50자이면서 여러 요청 포함 → 분해

## recommendation의 query_type 판단:
- **sql**: 구체적 키워드 있음 ("마찰견뢰도 장비 추천" → sql)
- **rag**: 추상적 요구 ("협력 기관 추천" → rag)

## is_aggregation:
- **true**: 통계/집계/랭킹 (연도별, TOP N)
- **false**: 개별 목록 (5개 알려줘)

## query_type 판단 (중요!):

### SQL 우선 엔티티 (무조건 sql):
- **evalp**: 평가표, 배점표, 평가기준 관련 → query_type=**sql**
  - "세부 항목", "상세", "전체 항목", "개별 항목", "항목별" 키워드 → entity_types에 **evalp_detail** 사용
  - 그 외 (목록, 요약) → entity_types에 **evalp** 사용
- **ancm**: 공고문, 모집, 사업공고 관련 → query_type=**sql**, query_subtype=**list**
- 예: "기술혁신개발사업 평가표 알려줘" → sql (list), evalp (요약)
- 예: "기술혁신개발사업 평가표 세부 항목" → sql (list), evalp_detail (개별 행)
- 예: "2024년 R&D 사업 공고 목록" → sql (list), ancm

### 일반 규칙:
- **sql**: 목록/수량/통계 조회 (구체적 키워드로 DB 검색 가능)
- **rag**: 개념 설명/유사 검색/맥락 분석 (텍스트 의미 기반)
  - "~란?", "~란 무엇인가", "어떤 것이 있는가?", "종류", "유형" 형태의 **개념 질문**만 rag (concept)
  - 예: "평가표란 무엇인가?" → rag (concept)
  - 예: "융복합 기술은 어떤것이 있는가?" → rag (concept) - 종류/유형 질문
  - 주의: "최근"이 있어도 **"동향"이 없으면 trend_analysis가 아님!**
- **hybrid**: SQL 데이터 + RAG 분석이 **모두** 필요한 경우:
  - "협업/협력 기관 추천" → 제안서 기반 참여기관 검색 + 기술 매칭 분석
  - "시장 동향 분석" → 통계 데이터 + 트렌드 해석 필요
  - **협업 기관 추천 키워드** (중요!): "협업", "협력", "기관 추천", "파트너", "공동연구", "협력기관", "협업기관"
    - 예: "인공지능 관련 협업 기관 추천" → query_type=**hybrid**, entity_types=["proposal"], subtype=recommendation
    - 예: "반도체 협력 기업 추천" → query_type=**hybrid**, entity_types=["proposal"]
    - **주의**: "기술분류 추천"과 구분! "분류"/"분류코드" 키워드 없으면 협업 기관 추천임
- **simple**: 인사/도움말

## [Phase 96] entity_types 사전 추측 금지 (중요!)
**entity_types와 related_tables는 비워두세요**:
- ES Scout 단계에서 실제 데이터 존재 여부를 확인 후 자동 결정
- LLM이 추측하면 데이터 없는 도메인 검색 → 검색 실패
- **예**: "특허맵 역량 보유 기관" → entity_types: [] (ES Scout에서 project 발견 후 채움)

## 참고: 엔티티-테이블 매핑 (ES Scout 참조용):
- patent: f_patents, f_patent_applicants (특허, 출원, 등록, 발명)
- project: f_projects (과제, 연구과제, 프로젝트, R&D)
- equip: f_equipments (장비, 기기, 측정, 분석장비)
- proposal: f_proposal_profile (기업 프로필, 기업 역량)
- evalp: f_ancm_evalp (배점표, 평가표)
- ancm: f_ancm_prcnd (공고문, 모집, 지원사업)

## 키워드 추출:
- 기술 용어는 분리 금지: "수소연료전지"✅ "수소","연료전지"✗
- **기관/기업명도 핵심 키워드로 추출** (중요!)
  - "서울테크노파크 보유 장비" → keywords: ["서울테크노파크"] (장비 제외!)
  - "삼성전자 특허" → keywords: ["삼성전자"]
- **일반 단어 제외** (중요!): 장비, 리스트, 목록, 보유, 추천, 시험, 측정 → 키워드에서 제외
  - "장비리스트", "특허목록", "과제리스트" 등은 키워드가 아님

## 키워드 추상화 (Phase 91 - 핵심!)
복잡한 용어는 **핵심 개념으로 추상화**:
- "이미지 기반 특허맵 저작 엔진" → keywords: ["특허맵"]
- "자율주행 라이다 센서 퓨전 시스템" → keywords: ["자율주행", "라이다"]
- "IoT 기반 스마트팜 통합 관리 플랫폼" → keywords: ["스마트팜", "IoT"]
- "불량률 측정을 위한 장비" → keywords: ["불량률"], entity_types: ["equip"]

**추상화 원칙**:
1. 수식어 제거: "기반", "시스템", "엔진", "플랫폼", "통합", "관리" 등은 키워드에서 제외
2. 핵심 기술 용어만 추출: DB 검색에 유용한 핵심 개념 (1-3개)
3. 조회 대상과 키워드 분리: "장비 추천" → entity_types: ["equip"], keywords에서 "장비" 제외
- structured_keywords 분류:
  - tech: 기술/주제 ("반도체")
  - org: 기관/기업명 ("서울테크노파크", "삼성전자") ← Phase 59 추가
  - country: 국가 코드 (**중요! 반드시 코드로 변환, keywords에서 제외**)
    - "한국", "국내", "KR", "대한민국" → ["KR"]
    - "미국", "US", "USA" → ["US"]
    - "일본", "JP" → ["JP"]
    - "중국", "CN" → ["CN"]
    - "유럽", "EU" → ["EU"]
    - "자국" → ["KR"], "해외"/"타국" → ["NOT_KR"]
    - 예: "한국 특허" → country: ["KR"], keywords: ["특허"] (한국은 keywords에서 제외!)
  - region: 지역 ("강원", "서울", "부산", "경기")
  - filter: 조건 ("TOP 10", "최근 2년")
  - metric: 분석 ("추이", "급증")

질문: {query}
"""


def _is_complex_ranking(query: str, structured_keywords: Dict = None) -> Tuple[bool, str]:
    """Phase 90.2: 복잡한 ranking인지 판단

    SQL 필수 케이스:
    - 통계/집계 (COUNT, 평균, 합계 등)
    - 계산 필요 (등록률, 비율, 피인용수)
    - 복잡한 필터 (연도 범위, 다중 국가, 조건 조합)

    Returns:
        (is_complex, reason): 복잡 여부와 판단 이유
    """
    query_lower = query.lower()

    # 1. 계산/비율 키워드 검사 - SQL 집계 함수 필요
    for kw in COMPLEX_RANKING_KEYWORDS["calculation"]:
        if kw in query:
            return True, f"계산 키워드 '{kw}' 감지 → SQL 필수"

    # 2. 집계 키워드 검사 (단순 TOP N이 아닌 그룹화 필요)
    for kw in COMPLEX_RANKING_KEYWORDS["aggregation"]:
        if kw in query:
            return True, f"집계 키워드 '{kw}' 감지 → SQL 필수"

    # 3. 복잡한 패턴 검사 (연도 범위, 다중 국가 등)
    for pattern in COMPLEX_RANKING_PATTERNS:
        if re.search(pattern, query, re.IGNORECASE):
            return True, f"복잡 패턴 감지 → SQL 필수"

    # 4. structured_keywords에서 다중 국가 검사
    if structured_keywords:
        countries = structured_keywords.get("country", [])
        if len(countries) >= 2:
            return True, f"다중 국가 필터 {countries} → SQL 필수"

        # 연도 필터 + 다른 조건 조합
        filters = structured_keywords.get("filter", [])
        if len(filters) >= 2:
            return True, f"다중 필터 {filters} → SQL 필수"

    # 5. 단순 TOP N 패턴 - ES/Vector로 처리 가능
    # "TOP 10 출원기관", "가장 많이 출원한 기업" 등
    logger.debug(f"Phase 90.2: 단순 ranking 판정 - query='{query[:50]}...'")
    return False, "단순 TOP N → ES/Vector 우선"


def is_complex_query(query: str) -> Tuple[bool, str]:
    """[DEPRECATED - Phase 7] 복합 질의 여부 판단

    NOTE: 이 함수는 더 이상 사용되지 않습니다.
    키워드 기반 패턴 매칭 대신 LLM 기반 분류를 사용합니다.

    Args:
        query: 사용자 질문

    Returns:
        (is_complex, reason): 복합 여부와 판단 이유
    """
    query_lower = query.lower()

    # 패턴 1: 접속사 감지 (서로 다른 요청을 연결)
    for conj in COMPLEXITY_PATTERNS["conjunctions"]:
        if conj in query:
            return True, f"접속사 '{conj.strip()}' 감지"

    # 패턴 2: 다중 요청 동사
    for verb in COMPLEXITY_PATTERNS["multi_request"]:
        if verb in query_lower:
            return True, f"다중 요청 동사 '{verb}' 감지"

    # 패턴 3: 리스트 마커
    for marker in COMPLEXITY_PATTERNS["list_markers"]:
        if marker in query:
            return True, f"리스트 마커 '{marker}' 감지"

    # Patent-AX: 다중 엔티티 감지 제거 (특허만 처리)
    # 복합 질의는 특허 내에서만 발생 (출원인, IPC, 지역 등)
    return False, "단순 질의"


def analyze_query(state: AgentState) -> AgentState:
    """쿼리 분석 노드

    Phase 20: LLM 우선 파이프라인 재설계
    - 복합 질의: LLM 분해 → 다중 실행
    - 단순 질의: 규칙 기반 fast-path

    사용자 질문을 분석하여 쿼리 유형, 의도, 엔티티 타입, 관련 테이블을 결정.

    Args:
        state: 현재 에이전트 상태

    Returns:
        업데이트된 상태 (query_type, query_intent, entity_types, related_tables, keywords)
    """
    query = state.get("query", "")

    if not query.strip():
        return {
            **state,
            "query_type": "simple",
            "query_intent": "빈 질문",
            "error": "질문이 비어있습니다."
        }

    # 1. 간단한 규칙 기반 사전 분류 (인사/도움말) - 항상 먼저 체크
    simple_check = _check_simple_query(query)
    if simple_check:
        return {**state, **simple_check}

    # 2. Phase 98: 장비 검색 규칙 기반 사전 분류
    # LLM이 장비 검색을 잘못 RAG로 분류하는 문제 해결
    equip_check = _check_equipment_query(query)
    if equip_check:
        logger.info(f"Phase 98: 장비 쿼리 규칙 기반 분류 적용")
        return {**state, **equip_check}

    # 3. LLM 기반 분류 (유일한 분류 방법) - Phase 7: 의미 기반 분류
    # 키워드 패턴이 아닌 LLM의 의미 이해를 통해 분류
    # 규칙 기반은 사용하지 않음 (오류로 처리)
    logger.info("LLM 기반 의미 분류 시작")
    try:
        return _analyze_with_basic_llm(state, query)
    except Exception as e:
        # LLM 분류 실패 시 오류 반환 (규칙 기반 폴백 제거)
        logger.error(f"LLM 분류 실패: {e}")
        return {
            **state,
            "query_type": "simple",
            "query_intent": "분류 실패",
            "entity_types": [],
            "related_tables": [],
            "keywords": [],
            "error": f"쿼리 분류 실패: LLM 호출 오류 - {str(e)}"
        }


def _check_simple_query(query: str) -> Dict[str, Any] | None:
    """간단한 규칙 기반 사전 분류"""
    query_lower = query.lower().strip()

    # 인사말
    greetings = ["안녕", "hello", "hi", "반갑", "안녕하세요"]
    if any(g in query_lower for g in greetings):
        return {
            "query_type": "simple",
            "query_intent": "인사",
            "entity_types": [],
            "related_tables": [],
            "keywords": []
        }

    # 도움말
    help_words = ["도움", "help", "사용법", "가이드"]
    if any(h in query_lower for h in help_words):
        return {
            "query_type": "simple",
            "query_intent": "도움말 요청",
            "entity_types": [],
            "related_tables": [],
            "keywords": []
        }

    return None


def _check_equipment_query(query: str) -> Dict[str, Any] | None:
    """Phase 98: 장비 관련 쿼리 규칙 기반 분류

    장비 보유 기관, 장비 추천, 장비 검색 등을 SQL로 분류하여
    LLM이 잘못 RAG로 분류하는 문제 해결

    Args:
        query: 사용자 질문

    Returns:
        분류 결과 또는 None (매칭 안 될 경우)
    """
    query_lower = query.lower()

    # 장비 관련 키워드
    equip_keywords = ["장비", "측정기", "시험기", "분석기", "시스템", "기기", "스캐너", "현미경"]
    # 검색/조회 액션 키워드
    action_keywords = ["보유", "찾", "추천", "검색", "알려", "있는", "가진", "갖고"]
    # 지역 키워드 (지역 필터 장비 검색)
    region_keywords = ["경기", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
                       "경북", "경남", "전북", "전남", "충북", "충남", "강원", "제주", "지역"]

    has_equip = any(kw in query_lower for kw in equip_keywords)
    has_action = any(kw in query_lower for kw in action_keywords)
    has_region = any(kw in query_lower for kw in region_keywords)

    # 장비 키워드 + 액션 키워드 조합 감지
    if has_equip and (has_action or has_region):
        # 키워드 추출 (기술 용어 위주)
        extracted_keywords = []

        # Phase 98: 장비 이름에서 핵심 용어만 추출
        # "광탄성시험기" → "광탄성", "표면단차측정기" → "표면단차" 또는 "단차"
        import re

        # 1. 먼저 전체 장비명 패턴 매칭
        equip_pattern = r'([가-힣a-zA-Z]+(?:측정기|시험기|분석기|스캐너|현미경|시스템|기기|장비))'
        equip_matches = re.findall(equip_pattern, query)

        # 2. 매칭된 장비명에서 접미사(측정기, 시험기 등) 제거하여 핵심 키워드 추출
        for match in equip_matches:
            # 전체 장비명도 추가
            extracted_keywords.append(match)
            # 접미사 제거한 핵심 키워드도 추가 (검색 정확도 향상)
            core_keyword = re.sub(r'(측정기|시험기|분석기|스캐너|현미경|시스템|기기|장비)$', '', match)
            if core_keyword and len(core_keyword) >= 2 and core_keyword != match:
                extracted_keywords.append(core_keyword)
                logger.info(f"Phase 98: 장비 핵심 키워드 추출 - {match} → {core_keyword}")

        # Phase 104.7: 장비명 매칭이 없으면 용도/목적 키워드 추출
        # "시제품 장비", "인공지능 연구 장비" 등에서 목적 키워드 추출
        if not extracted_keywords:
            # 불용어 목록 (형태소 기본형 기준)
            stopwords = {
                # 엔티티/일반 단어
                "장비", "기기", "시스템", "기업", "연구", "개발", "진행", "활용", "보유",
                "위해", "위한", "추천", "필요", "가능", "사용", "제작", "제조",
                "저희", "해당", "하고자", "만들", "있는", "좋을", "때", "할",
                "연구개발", "기술개발", "시험", "측정", "분석",
                # 동사/부사 어근
                "만들려면", "활용해", "볼", "어떤",
                # 관형사
                "이", "그", "저", "어느", "무슨",
            }
            # 조사 패턴 (어미 제거용)
            josa_pattern = re.compile(r'(을|를|이|가|은|는|에|에서|에게|으로|로|와|과|도|만|까지|부터|의)$')

            # 한글 단어 추출 (2자 이상)
            words = re.findall(r'[가-힣]{2,}', query)
            for word in words:
                # 조사 제거
                clean_word = josa_pattern.sub('', word)
                if clean_word and len(clean_word) >= 2 and clean_word not in stopwords:
                    # 기술 키워드 후보 (예: 시제품, 인공지능, 반도체)
                    extracted_keywords.append(clean_word)
                    logger.info(f"Phase 104.7: 장비 용도 키워드 추출 - {word} → {clean_word}")
                    if len(extracted_keywords) >= 3:  # 최대 3개
                        break

        # 지역 추출
        extracted_regions = []
        for region in region_keywords:
            if region in query_lower and region != "지역":
                extracted_regions.append(region)

        logger.info(f"Phase 98: 장비 검색 쿼리 감지 → SQL 분류 (장비={has_equip}, 액션={has_action}, 지역={has_region})")

        return {
            "query_type": "sql",
            "query_subtype": "list",
            "query_intent": "장비 검색 또는 보유 기관 조회",
            "entity_types": ["equip"],
            "related_tables": ["f_equipments"],
            "keywords": extracted_keywords if extracted_keywords else [],
            "structured_keywords": {
                "tech": extracted_keywords,
                "org": [],
                "country": [],
                "region": extracted_regions,
                "filter": [],
                "metric": []
            },
            "is_equipment_query": True
        }

    return None


def _check_rule_based_query(query: str) -> Dict[str, Any] | None:
    """[DEPRECATED - Phase 7] 규칙 기반 사전 분류

    NOTE: 이 함수는 더 이상 사용되지 않습니다.
    키워드 기반 패턴 매칭 대신 LLM 기반 분류를 사용합니다.
    """
    query_lower = query.lower().strip()

    # 1-1. 우대/감점 관련 → sql + evalp_pref + f_ancm_prcnd (Phase 91)
    # 우대/감점 키워드를 배점표보다 먼저 체크하여 올바른 테이블 반환
    pref_keywords = ["우대", "가점", "감점", "우대조건", "우대 조건", "가산점", "감산점", "우대감점"]
    if any(kw in query_lower for kw in pref_keywords):
        return {
            "query_type": "sql",
            "query_intent": "우대/감점 조건 조회",
            "entity_types": ["evalp_pref"],
            "related_tables": ["f_ancm_prcnd"],
            "keywords": [kw for kw in pref_keywords if kw in query_lower]
        }

    # 1-2. 배점표/평가표 관련 → sql + evalp + f_ancm_evalp
    evalp_keywords = ["배점표", "배점", "평가표"]
    if any(kw in query_lower for kw in evalp_keywords):
        return {
            "query_type": "sql",
            "query_intent": "배점표/평가조건 조회",
            "entity_types": ["evalp"],
            "related_tables": ["f_ancm_evalp"],
            "keywords": [kw for kw in evalp_keywords if kw in query_lower]
        }

    # 2. 특허 + TOP N/숫자/검색 → sql + patent
    if "특허" in query_lower:
        if any(kw in query_lower for kw in ["top", "상위", "개", "목록", "검색", "찾아", "알려"]):
            return {
                "query_type": "sql",
                "query_intent": "특허 목록 조회",
                "entity_types": ["patent"],
                "related_tables": ["f_patents", "f_patent_applicants"],
                "keywords": ["특허"]
            }

    # 3. 연구 사례/동향 → rag + project
    if any(kw in query_lower for kw in ["사례", "연구사례", "연구 사례"]):
        return {
            "query_type": "rag",
            "query_intent": "연구 사례 검색",
            "entity_types": ["project"],
            "related_tables": [],
            "keywords": ["연구", "사례"]
        }

    if any(kw in query_lower for kw in ["동향", "연구동향", "연구 동향", "기술동향"]):
        return {
            "query_type": "rag",
            "query_intent": "연구/기술 동향 검색",
            "entity_types": ["project"],
            "related_tables": [],
            "keywords": ["동향"]
        }

    # 4. 신청조건/자격조건 → sql + evalp
    if any(kw in query_lower for kw in ["신청조건", "자격조건", "지원조건"]):
        return {
            "query_type": "sql",
            "query_intent": "신청조건 조회",
            "entity_types": ["evalp"],
            "related_tables": ["f_ancm_prcnd"],
            "keywords": ["신청조건"]
        }

    return None


def _analyze_with_basic_llm(state: AgentState, query: str) -> AgentState:
    """LLM 기반 분류 (Phase 52: USE_REASONING_MODE 분기 추가)"""
    logger.debug(f"_analyze_with_basic_llm 시작: query={query[:50]}...")
    try:
        logger.debug("LLM 클라이언트 가져오기...")
        llm = get_llm_client()
        logger.debug("프롬프트 포맷팅...")
        prompt = QUERY_CLASSIFICATION_PROMPT.format(query=query)

        # Phase 105: EXAONE 4.0.1 추론 모드 활용
        if USE_REASONING_MODE:
            # EXAONE 4.0.1 공식 문서 기반 추론 프롬프트 구성
            # <think> 블록에서 단계별 추론 후 JSON 출력
            enhanced_prompt = f"""<think>
사용자 질의를 단계별로 분석합니다:

## 1단계: 핵심 의도 파악
질문: "{query}"
→ 사용자가 원하는 정보 유형은 무엇인가? (목록, 통계, 개념 설명, 추천 등)

## 2단계: 쿼리 유형 결정
- sql: 구체적 데이터 조회 (목록, 수량, 통계)
- rag: 개념 설명, 의미 기반 검색
- hybrid: SQL 데이터 + RAG 분석 둘 다 필요
- simple: 인사, 도움말

## 3단계: 세부 유형(subtype) 결정
- list: 목록 조회 ("알려줘", "N개")
- aggregation: 통계/집계 ("~별 현황", "분포")
- trend_analysis: 동향 분석 ("~동향", "추이")
- ranking: 순위 ("TOP N", "상위")
- concept: 개념 설명 ("~란?", "어떤것이 있는가")
- compound: 복합 질의 (특허+과제 검색 등 다중 엔티티)
- recommendation: 추천 ("추천해줘")
- comparison: 비교 ("A vs B")

## 4단계: 엔티티 타입 추론
- 특허/발명/출원 → "patent"
- 과제/연구/R&D → "project"
- 장비/기자재 → "equip"
- 공고/제안서 → "proposal"
- 다중 엔티티가 언급되면 compound=true

## 5단계: 핵심 키워드 추출
- 기술 용어, 고유명사만 추출
- 조사, 접속사, 일반 동사 제외
- 복합어는 의미 단위로 유지 ("인공지능", "수소연료전지")

## 6단계: 복합 질의 분해 필요 여부
- 다른 엔티티 타입을 검색하면 compound=true
- 예: "인공지능 특허와 연구과제" → compound=true, sub_queries 분해

분석 완료.
</think>

{prompt}"""

            logger.info(f"Phase 105: EXAONE 추론 모드로 쿼리 분석 시작 (query={query[:50]}...)")
            reasoning_result = llm.generate_with_reasoning(
                prompt=enhanced_prompt,
                system_prompt="당신은 정확한 질의 분석 전문가입니다. <think> 태그 내에서 단계별 추론을 수행한 후, JSON 형식으로 최종 분석 결과를 출력하세요.",
                max_tokens=2000  # 추론 과정을 위해 토큰 증가
            )
            response = reasoning_result.answer
            if reasoning_result.thinking:
                logger.info(f"Phase 105: 추론 과정 완료 (길이={len(reasoning_result.thinking)}자)")
                logger.debug(f"추론 과정: {reasoning_result.thinking[:300]}...")
        else:
            # 기본 모드
            response = llm.generate(
                prompt=prompt,
                system_prompt="JSON 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요.",
                max_tokens=500,
                temperature=0.3
            )

        # JSON 파싱
        logger.debug(f"LLM 응답 원본 (첫 500자): {response[:500] if response else 'None'}")
        result = _parse_classification_response(response)
        logger.debug(f"파싱 결과: {result}")

        is_aggregation = result.get("is_aggregation", False)
        query_subtype = result.get("query_subtype", "list")

        # query_subtype 유효성 검증 (Phase 33: recommendation, comparison 추가, Phase 73/73.1: impact_ranking, nationality_ranking 추가, Phase 88: evalp_score, trend_analysis 추가, Phase 99.6: crosstab_analysis 추가)
        valid_subtypes = ["list", "aggregation", "ranking", "concept", "compound", "recommendation", "comparison", "impact_ranking", "nationality_ranking", "evalp_score", "evalp_pref", "pref_task_search", "trend_analysis", "crosstab_analysis"]
        if query_subtype not in valid_subtypes:
            query_subtype = "list"

        # Phase 88/99.5: 동향/통계 분석 패턴 강제 분류 (trend_analysis)
        # "동향", "추이", "통계", "연도별" 등 키워드 감지 시 trend_analysis로 전환
        TREND_KEYWORDS = {
            "동향", "기술동향", "연구동향", "특허동향", "시장동향",
            "추이", "출원추이", "등록추이", "연구추이",
            "통계", "현황", "분포",
            "연도별", "년도별", "연간"
        }
        query_lower = query.lower()

        # Phase 99.6: 크로스탭 통계 패턴 감지 (기관별 + 연도별 교차 분석)
        # crosstab_analysis = 기관별 연도별 교차 테이블 (2차원 집계)
        # Phase 104.7: 단순 "TOP N 출원기관"은 ranking으로 분류 (연도별 키워드 필수)
        import re as regex_temp
        has_top_n = bool(regex_temp.search(r'(top\s*\d*|상위|주요)', query_lower))
        has_applicant = any(kw in query_lower for kw in ["출원기관", "권리자", "출원인", "기관별"])
        has_yearly = any(kw in query_lower for kw in ["연도별", "년도별", "연간", "추이", "현황"])

        # crosstab_analysis 조건: TOP/상위 + 출원기관 + 연도별 (3가지 모두 필요)
        if has_top_n and has_applicant and has_yearly:
            logger.info(f"Phase 99.6: 크로스탭 패턴 감지 (TOP+출원기관+연도별) → query_subtype=crosstab_analysis 강제 설정")
            query_subtype = "crosstab_analysis"
            result["query_type"] = "sql"
        # TOP + 출원기관 (연도별 없음) → ranking으로 분류
        elif has_top_n and has_applicant and not has_yearly:
            logger.info(f"Phase 104.7: TOP+출원기관 패턴 (연도별 없음) → query_subtype=ranking 강제 설정")
            query_subtype = "ranking"
            result["query_type"] = "sql"
        elif any(kw in query_lower for kw in TREND_KEYWORDS):
            logger.info(f"Phase 88/99.5: 동향/통계 키워드 감지 → query_subtype=trend_analysis 강제 설정")
            query_subtype = "trend_analysis"
            # query_type도 sql로 강제 (ES aggregations로 라우팅)
            result["query_type"] = "sql"

        # Phase 72.4: TOP N 패턴이면 강제 ranking 분류
        # LLM이 ranking으로 분류하지 않아도 "TOP 10", "TOP 5" 등 패턴 감지 시 ranking으로 전환
        # Phase 99.6: crosstab_analysis도 제외 (TOP + 출원기관 패턴은 이미 처리됨)
        import re as regex_module
        top_n_pattern = regex_module.search(r'top\s*\d+', query.lower())
        if top_n_pattern and query_subtype not in ["ranking", "trend_analysis", "crosstab_analysis"]:
            logger.info(f"Phase 72.4: TOP N 패턴 감지 ({top_n_pattern.group()}) → query_subtype=ranking 강제 설정")
            query_subtype = "ranking"

        # Phase 90.2: ranking 유형 분류 (simple vs complex)
        # 단순 ranking: ES/Vector 우선, 복잡 ranking: SQL 필수
        ranking_type = "simple"  # 기본값: 단순 ranking
        if query_subtype == "ranking":
            is_complex, reason = _is_complex_ranking(query, result.get("structured_keywords"))
            if is_complex:
                ranking_type = "complex"
                # complex ranking은 hybrid (SQL + ES 병렬) 라우팅
                result["query_type"] = "hybrid"
                logger.info(f"Phase 90.2: complex_ranking 판정 - {reason}")
            else:
                ranking_type = "simple"
                # simple ranking은 rag_node로 라우팅 (ES aggregation)
                result["query_type"] = "rag"
                logger.info(f"Phase 90.2: simple_ranking 판정 - {reason}")

        # Phase 73: 영향력/피인용 순위 패턴 감지
        # "영향력", "피인용", "citation" 키워드 + TOP N 패턴 → impact_ranking subtype
        IMPACT_KEYWORDS = {"영향력", "피인용", "citation", "인용"}
        query_lower = query.lower()
        if any(kw in query_lower for kw in IMPACT_KEYWORDS) and top_n_pattern:
            logger.info(f"Phase 73: 영향력 키워드 감지 → query_subtype=impact_ranking 설정")
            query_subtype = "impact_ranking"

        # Phase 73.1: 국적별 분리 순위 패턴 감지
        # "국적별", "자국", "타국", "국내외", "구분" 등 키워드 감지 시 nationality_ranking 강제 설정
        NATIONALITY_KEYWORDS = {"국적별", "자국", "타국", "국내외", "구분해서", "국적으로"}
        if any(kw in query_lower for kw in NATIONALITY_KEYWORDS):
            logger.info(f"Phase 73.1: 국적 분리 키워드 감지 → query_subtype=nationality_ranking 강제 설정")
            query_subtype = "nationality_ranking"

        # Phase 88: 배점표/평가표 패턴 감지 → evalp_score 서브타입 강제 설정
        # LLM이 entity_types에 evalp를 포함하고 배점표 키워드가 있으면 evalp_score로 전환
        EVALP_SCORE_KEYWORDS = {"배점표", "배점", "평가표", "평가항목", "평가기준"}
        EVALP_PREF_KEYWORDS = {"우대", "가점", "우대조건", "감점"}
        entity_types = result.get("entity_types", [])
        if any(kw in query_lower for kw in EVALP_SCORE_KEYWORDS):
            # 배점표 요청
            if query_subtype not in ["evalp_score", "evalp_pref", "pref_task_search"]:
                logger.info(f"Phase 88: 배점표 키워드 감지 → query_subtype=evalp_score 강제 설정")
                query_subtype = "evalp_score"
            # entity_types에 evalp가 없으면 추가
            if "evalp" not in entity_types:
                entity_types = ["evalp"] + entity_types
                result["entity_types"] = entity_types
                logger.info(f"Phase 88: entity_types에 evalp 추가 → {entity_types}")
        elif any(kw in query_lower for kw in EVALP_PREF_KEYWORDS):
            # 우대조건 요청 (Phase 91: evalp_pref + f_ancm_prcnd로 수정)
            if query_subtype not in ["evalp_score", "evalp_pref", "pref_task_search"]:
                logger.info(f"Phase 88: 우대조건 키워드 감지 → query_subtype=evalp_pref 강제 설정")
                query_subtype = "evalp_pref"
            # Phase 91: entity_types를 evalp_pref로 설정
            if "evalp_pref" not in entity_types:
                entity_types = ["evalp_pref"] + [e for e in entity_types if e != "evalp"]
                result["entity_types"] = entity_types
            # Phase 91: related_tables를 f_ancm_prcnd로 설정
            result["related_tables"] = ["f_ancm_prcnd"]
            logger.info(f"Phase 91: 우대조건 → entity_types={entity_types}, related_tables=['f_ancm_prcnd']")

        # is_aggregation과 query_subtype 동기화 (Phase 73: impact_ranking, Phase 73.1: nationality_ranking, Phase 88: trend_analysis 추가, Phase 99.6: crosstab_analysis 추가)
        if query_subtype in ["aggregation", "ranking", "impact_ranking", "nationality_ranking", "trend_analysis", "crosstab_analysis"]:
            is_aggregation = True

        # Phase 34.5: 구조화된 키워드 처리
        structured_keywords = result.get("structured_keywords")
        if structured_keywords:
            # 유효성 검증
            if not isinstance(structured_keywords, dict):
                structured_keywords = None
            else:
                # 필수 키 확인 (Phase 59: org 추가)
                for key in ["tech", "org", "country", "region", "filter", "metric"]:
                    if key not in structured_keywords:
                        structured_keywords[key] = []
        else:
            # structured_keywords가 없으면 초기화
            structured_keywords = {"tech": [], "org": [], "country": [], "region": [], "filter": [], "metric": []}

        # Phase 64: 국가 키워드 후처리 - 폴백 + keywords에서 제거
        keywords = result.get("keywords", [])

        # 1. structured_keywords['country']가 비어있으면 원본 쿼리에서 국가 코드 추출
        if not structured_keywords.get("country"):
            for code, country_words in COUNTRY_KEYWORDS.items():
                if any(kw in query for kw in country_words):
                    structured_keywords["country"] = [code]
                    logger.info(f"Phase 64: 국가 키워드 폴백 - {code}")
                    break

        # 2. (핵심!) keywords에서 국가 키워드 제거 - SQL이 '%한국%' 조건 생성 방지
        all_country_words = set()
        for words in COUNTRY_KEYWORDS.values():
            all_country_words.update(words)

        original_keywords = keywords.copy()
        keywords = [kw for kw in keywords if kw not in all_country_words]

        if len(keywords) < len(original_keywords):
            removed = set(original_keywords) - set(keywords)
            logger.info(f"Phase 64: 국가 키워드 제거됨 - {removed}, 남은 keywords: {keywords}")

        # Phase 99.4: 엔티티 타입 키워드 필터링
        # "특허", "과제", "장비" 등 엔티티 타입을 나타내는 단어는 검색 키워드가 아님
        # 이들은 entity_types에서 처리되므로 keywords에서 제외
        ENTITY_TYPE_STOPWORDS = {
            # 특허 관련
            "특허", "출원", "발명", "등록", "특허권", "지식재산", "명세서",
            # 과제 관련
            "과제", "연구과제", "프로젝트", "연구", "연구개발",
            # 장비 관련
            "장비", "기기", "설비", "인프라", "시설", "연구장비", "실험장비",
            # 공고 관련
            "공고", "사업공고", "입찰", "모집",
            # 제안서 관련
            "제안서", "제안", "사업계획",
            # 일반 지시어
            "검색", "조회", "목록", "리스트", "찾아", "알려"
        }

        pre_filter_keywords = keywords.copy()
        keywords = [kw for kw in keywords if kw not in ENTITY_TYPE_STOPWORDS]

        if len(keywords) < len(pre_filter_keywords):
            removed = set(pre_filter_keywords) - set(keywords)
            logger.info(f"Phase 99.4: 엔티티 타입 키워드 제거됨 - {removed}, 남은 keywords: {keywords}")

        # Phase 36.1: 복합 의도 분해 처리
        is_compound = result.get("is_compound", False)
        sub_queries = result.get("sub_queries", [])

        # is_compound와 query_subtype 동기화
        if is_compound and sub_queries:
            query_subtype = "compound"

        logger.info(f"쿼리 분석 결과: type={result.get('query_type')}, subtype={query_subtype}, is_aggregation={is_aggregation}, is_compound={is_compound}, intent={result.get('intent', '')[:50]}")
        if structured_keywords:
            logger.info(f"구조화된 키워드: tech={structured_keywords.get('tech', [])}, country={structured_keywords.get('country', [])}, region={structured_keywords.get('region', [])}")
        if is_compound and sub_queries:
            logger.info(f"복합 질의 분해: {len(sub_queries)}개 하위 질의")

        # Phase 96: entity_types는 비워두고 ES Scout에서 결정
        # 다만, 특정 패턴(배점표, 우대조건, 공고문)은 규칙 기반으로 설정
        # Phase 101: 초기 state에서 entity_types가 명시적으로 설정된 경우 유지 (공공 AX API용)
        initial_entity_types = state.get("entity_types", [])
        entity_types = result.get("entity_types", []) or initial_entity_types
        related_tables = result.get("related_tables", [])

        # Phase 100.1: 사용자가 명시적으로 엔티티를 언급한 경우 entity_types 설정
        # "특허" → patent, "과제" → project, "장비" → equip 등
        EXPLICIT_ENTITY_KEYWORDS = {
            "patent": ["특허", "출원", "발명", "등록특허"],
            "project": ["과제", "연구과제", "프로젝트", "R&D"],
            "equip": ["장비", "측정기", "시험기", "분석기", "현미경", "스캐너"],
            "proposal": ["제안서", "기업", "역량", "프로필"],
        }

        query_for_entity = query.lower()
        # Phase 104: 다중 엔티티 매칭 (break 제거)
        explicit_entities = []
        for entity, keywords_list in EXPLICIT_ENTITY_KEYWORDS.items():
            if any(kw in query_for_entity for kw in keywords_list):
                explicit_entities.append(entity)
                logger.info(f"Phase 104: 명시적 엔티티 감지 - '{entity}' (키워드 매칭)")
        # 하위 호환성: 단일 엔티티 변수
        explicit_entity = explicit_entities[0] if len(explicit_entities) == 1 else None

        # Phase 96: 특수 케이스에서만 entity_types 직접 설정
        # (evalp, evalp_pref, ancm 등 명확한 패턴)
        # 그 외 일반 검색은 entity_types를 비워두고 ES Scout에서 채움
        if query_subtype in ["evalp_score", "evalp_pref", "pref_task_search"]:
            # 배점표/우대조건은 특수 처리 필요
            logger.info(f"Phase 96: 특수 케이스 → entity_types 유지: {entity_types}")
        elif any(kw in query.lower() for kw in ["협업", "협력", "파트너", "공동연구"]):
            # 협업 추천은 명시적으로 표시만 하고, entity_types는 ES Scout에서 결정
            logger.info(f"Phase 96: 협업 키워드 감지 → ES Scout에서 entity_types 결정")
            # entity_types는 비워둠 - ES Scout에서 채움
            entity_types = []
        elif explicit_entities:
            # Phase 104: 다중 엔티티 지원 - 여러 엔티티가 매칭된 경우 모두 포함
            entity_types = explicit_entities
            logger.info(f"Phase 104: 명시적 엔티티 설정 → entity_types={entity_types}")

            # Phase 104: 다중 엔티티 + compound일 때 sub_queries 자동 생성
            if len(explicit_entities) >= 2 and (is_compound or query_subtype == "compound"):
                if not sub_queries:  # LLM이 sub_queries를 생성하지 않은 경우
                    sub_queries = []
                    for entity in explicit_entities:
                        sub_queries.append({
                            "intent": f"{entity} 검색",
                            "subtype": "list",
                            "keywords": keywords,
                            "entity_types": [entity]
                        })
                    is_compound = True
                    logger.info(f"Phase 104: 다중 엔티티 기반 sub_queries 자동 생성 - {len(sub_queries)}개")
        else:
            # Phase 96: 일반 케이스는 entity_types 비움 → ES Scout에서 결정
            # Phase 101: 단, 초기 state에서 명시적으로 설정된 경우 유지 (공공 AX API용)
            if initial_entity_types:
                entity_types = initial_entity_types
                logger.info(f"Phase 101: 초기 entity_types 유지 (API 명시) → {entity_types}")
            elif entity_types:
                logger.info(f"Phase 96: entity_types 제거 (ES Scout에서 결정) - 기존: {entity_types}")
                entity_types = []

        # Phase 89: SearchConfig 생성 (이후 노드에서 재사용)
        # Patent-AX: entity_types 강제 고정
        analysis_result = {
            **state,
            "query_type": result.get("query_type", "rag"),
            "query_subtype": query_subtype,
            "query_intent": result.get("intent", ""),
            "entity_types": ["patent"],  # Patent-AX: 특허만 고정
            "related_tables": ["f_patents", "f_patent_applicants"],  # Patent-AX: 특허 테이블만
            "keywords": keywords,  # Phase 64: 국가 키워드 제거된 버전 사용
            "structured_keywords": structured_keywords,  # Phase 34.5
            "is_aggregation": is_aggregation,
            "is_compound": is_compound,  # Phase 36.1
            "sub_queries": sub_queries,   # Phase 36.1
            "ranking_type": ranking_type,  # Phase 90.2: simple vs complex ranking
        }

        # Phase 89: SearchConfig 생성 및 저장
        from workflow.search_config import get_search_config
        search_config = get_search_config(analysis_result)
        analysis_result["search_config"] = search_config
        logger.info(f"Phase 89: SearchConfig 생성 - primary={[s.value for s in search_config.primary_sources]}, rag={search_config.graph_rag_strategy.value}, es={search_config.es_mode.value}")

        return analysis_result

    except Exception as e:
        import traceback
        logger.error(f"쿼리 분석 실패: {e}")
        logger.error(f"상세 스택트레이스:\n{traceback.format_exc()}")
        # 폴백: RAG로 처리
        return {
            **state,
            "query_type": "rag",
            "query_intent": query,
            "error": f"쿼리 분석 실패: {str(e)}"
        }


def _parse_classification_response(response: str) -> Dict[str, Any]:
    """LLM 응답에서 JSON 파싱 (개선된 버전)"""
    # 코드 블록 제거
    response = re.sub(r'```json\s*', '', response)
    response = re.sub(r'```\s*', '', response)
    response = response.strip()

    result = {}

    # 방법 1: 직접 JSON 파싱 시도
    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        pass

    # 방법 2: 중첩 JSON 객체 추출 (개선된 정규식)
    if not result:
        # 가장 바깥쪽 { } 찾기
        start_idx = response.find('{')
        if start_idx != -1:
            # 괄호 매칭으로 완전한 JSON 찾기
            brace_count = 0
            end_idx = start_idx
            for i, char in enumerate(response[start_idx:], start_idx):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i + 1
                        break

            json_str = response[start_idx:end_idx]
            try:
                result = json.loads(json_str)
            except json.JSONDecodeError:
                pass

    # 방법 3: 개별 필드 추출 (최후의 수단)
    if not result or "query_type" not in result:
        # query_type 추출
        type_match = re.search(r'"query_type"\s*:\s*"([^"]+)"', response)
        if type_match:
            result["query_type"] = type_match.group(1)

        # query_subtype 추출
        subtype_match = re.search(r'"query_subtype"\s*:\s*"([^"]+)"', response)
        if subtype_match:
            result["query_subtype"] = subtype_match.group(1)

        # intent 추출
        intent_match = re.search(r'"intent"\s*:\s*"([^"]+)"', response)
        if intent_match:
            result["intent"] = intent_match.group(1)

        # keywords 추출
        keywords_match = re.search(r'"keywords"\s*:\s*\[([^\]]*)\]', response)
        if keywords_match:
            keywords_str = keywords_match.group(1)
            keywords = re.findall(r'"([^"]+)"', keywords_str)
            result["keywords"] = keywords

    # 유효성 검증
    valid_types = ["sql", "rag", "hybrid", "simple"]
    if result.get("query_type") not in valid_types:
        result["query_type"] = "rag"

    return result
