"""
SQL 실행 노드
- 기존 SQLAgent 래핑
- 자연어 → SQL 변환 및 실행
- Phase 19: 다중 엔티티 쿼리 시 각각 별도 실행
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import logging
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from workflow.state import AgentState, SQLQueryResult
from sql.sql_agent import get_sql_agent

logger = logging.getLogger(__name__)

# Phase 34.3: 현재 날짜 정보 (시간 조건 힌트용)
def _get_current_date_info() -> Dict[str, Any]:
    """현재 날짜 정보 반환 (시간 조건 SQL 힌트용)"""
    now = datetime.now()
    return {
        "current_year": now.year,
        "current_month": now.month,
        "current_date": now.strftime("%Y%m%d"),
        "recent_2_years": f"{now.year - 1} ~ {now.year}",
        "recent_5_years": f"{now.year - 4} ~ {now.year}",
        "year_minus_1": now.year - 1,
        "year_minus_2": now.year - 2,
        "year_minus_4": now.year - 4,
    }


def _build_query_subtype_hints(query_subtype: str, keywords: List[str], semantic_keywords: List[str] = None) -> str:
    """Phase 99.8: 쿼리 서브타입 별 SQL 힌트 생성 (동의어 OR 확장 패턴)

    Phase 67 AND+OR → Phase 99.8 단순 OR 변경
    - 핵심 키워드 + 동의어/확장 키워드를 모두 OR로 검색
    - 동의어 검색 범위 확대로 검색 재현율 향상

    Args:
        query_subtype: 쿼리 서브타입 (list, aggregation, ranking, concept, compound, recommendation, comparison)
        keywords: LLM 추출 핵심 키워드 (필수)
        semantic_keywords: 벡터 검색에서 확장된 의미론적 키워드 (선택, 동의어 포함)

    Returns:
        SQL 프롬프트에 포함할 힌트 문자열
    """
    # 핵심 키워드 (최대 3개)
    core_keywords = list(keywords or [])[:3]

    # 확장 키워드 중 핵심에 없는 것만 추출 (최대 3개로 확대 - 동의어 포함)
    expanded_only = []
    if semantic_keywords:
        expanded_only = [k for k in semantic_keywords if k not in (keywords or [])][:3]

    # Phase 99.8: 단순 OR 패턴 (동의어 포함)
    # 기존 AND+OR → 모든 키워드를 OR로 묶어 검색 범위 확대
    all_keywords = core_keywords + expanded_only
    keyword_clause = ""
    if all_keywords:
        keyword_clause = " OR ".join(f"conts_klang_nm ILIKE '%{kw}%'" for kw in all_keywords)

    # Phase 35: 간소화된 서브타입별 힌트
    if query_subtype == "aggregation":
        date_info = _get_current_date_info()
        return f"""## 통계/집계 쿼리
- 전체 데이터 대상 GROUP BY + COUNT/SUM 사용
- 날짜 컬럼은 TEXT (EXTRACT 금지, LEFT() 사용)
- 현재 연도: {date_info['current_year']}, 최근 5년: >= '{date_info['year_minus_4']}'
- WHERE ({keyword_clause}) GROUP BY [기준] ORDER BY [결과] DESC"""

    elif query_subtype == "ranking":
        return f"""## 랭킹 쿼리 (집계 필수!)
- **GROUP BY + COUNT() 후 ORDER BY DESC LIMIT 10**
- 전체 데이터에서 집계 (중간 LIMIT 금지)
- Phase 99.8: 핵심 + 동의어/확장 키워드 OR 조건 사용
- 패턴 예시:
  SELECT a.applicant_name as 출원인, COUNT(*) as 특허수
  FROM f_patents p
  JOIN f_patent_applicants a ON p.documentid = a.document_id
  WHERE ({keyword_clause})
  GROUP BY a.applicant_name
  ORDER BY 특허수 DESC
  LIMIT 10
- 특허 출원기관 순위: f_patent_applicants.applicant_name 기준 집계"""

    elif query_subtype == "list":
        return f"""## 목록 조회
- 키워드 ILIKE 조건, LIMIT 10 기본
- WHERE ({keyword_clause}) LIMIT 10"""

    elif query_subtype == "recommendation":
        return f"""## 추천 쿼리
- 키워드 검색 후 관련도순 정렬
- WHERE ({keyword_clause}) ORDER BY [관련도] DESC LIMIT 10"""

    elif query_subtype == "comparison":
        all_keywords = core_keywords + expanded_only
        return f"""## 비교 쿼리
- GROUP BY로 비교 대상 분리
- 국가 매핑: 자국='KR', 타국='KR' 아님
- 패턴: CASE WHEN applicant_country='KR' THEN '자국' ELSE '타국' END
- 키워드: {', '.join(all_keywords[:5]) if all_keywords else 'N/A'}"""

    elif query_subtype == "trend_analysis":
        date_info = _get_current_date_info()
        return f"""## 동향 분석 쿼리 - 연도별 추이 (1개 쿼리만 생성!)

### 연도별 추이 쿼리 (필수) - conts_ymd 사용
SELECT
  LEFT(conts_ymd, 4) as 연도,
  COUNT(*) as 건수
FROM "f_projects"
WHERE ({keyword_clause})
  AND LEFT(conts_ymd, 4) >= '{date_info['year_minus_4']}'
GROUP BY LEFT(conts_ymd, 4)
ORDER BY 연도 DESC

### 주의사항:
- 현재 연도: {date_info['current_year']}, 최근 5년: >= '{date_info['year_minus_4']}'
- 날짜 컬럼은 TEXT → LEFT() 사용 (EXTRACT 금지)
- 키워드 조건: ({keyword_clause})
- **반드시 1개의 SQL만 생성** (세미콜론 2개 금지)"""

    # concept, compound는 힌트 없음
    return ""


# Phase 51: 지역 코드 매핑 (전역 정의)
# PNU 코드 앞 2자리 기반 시도 코드
REGION_CODE_MAP = {
    "서울": "11", "부산": "21", "대구": "22", "인천": "23", "광주": "24",
    "대전": "25", "울산": "26", "세종": "29", "경기": "31", "강원": "32",
    "충북": "33", "충남": "34", "전북": "35", "전남": "36",
    "경북": "37", "경남": "38", "제주": "39"
}

# Phase 64: 국가 코드 매핑 (특허 검색용)
# 쿼리에서 국가 키워드를 인식하고 SQL 조건으로 변환
COUNTRY_CODE_MAP = {
    # 한국
    "한국": "KR", "국내": "KR", "대한민국": "KR", "자국": "KR", "kr": "KR", "KR": "KR",
    # 미국
    "미국": "US", "USA": "US", "us": "US", "US": "US",
    # 일본
    "일본": "JP", "jp": "JP", "JP": "JP",
    # 중국
    "중국": "CN", "cn": "CN", "CN": "CN",
    # 유럽
    "유럽": "EU", "eu": "EU", "EU": "EU",
    # 타국/해외
    "해외": "NOT_KR", "타국": "NOT_KR", "외국": "NOT_KR"
}


def _extract_country_filter_from_query(query: str) -> Optional[str]:
    """Phase 65: 쿼리에서 등록국가 필터 조건 추출

    사용자 쿼리에서 국가 키워드를 인식하고 SQL WHERE 조건으로 변환
    Phase 65: applicant_country (출원인 국적) → ntcd (등록국가)로 변경

    - "미국 특허" → 미국 특허청 등록 특허 (ntcd = 'US')
    - "한국 특허" → 한국 특허청 등록 특허 (ntcd = 'KR')
    - 출원인 국적 조회는 별도 질의로 처리 예정

    Args:
        query: 원본 사용자 질문

    Returns:
        SQL 조건 문자열 (예: "p.ntcd = 'KR'") 또는 None
    """
    if not query:
        return None

    # 쿼리에서 국가 키워드 검색
    detected_country_code = None
    for keyword, code in COUNTRY_CODE_MAP.items():
        if keyword in query:
            detected_country_code = code
            logger.info(f"Phase 65: 쿼리에서 국가 키워드 '{keyword}' 감지 → 등록국가 {code}")
            break

    if not detected_country_code:
        return None

    # Phase 65: 등록국가(ntcd) 기준 SQL 조건 생성
    if detected_country_code == "NOT_KR":
        return "p.ntcd != 'KR'"
    else:
        return f"p.ntcd = '{detected_country_code}'"


def _extract_regions_from_query(query: str, keywords: List[str] = None) -> List[str]:
    """Phase 51.2: 원본 쿼리 또는 keywords에서 지역명 자동 추출

    LLM이 structured_keywords.region에 지역을 추출하지 못했을 때 폴백으로 사용
    keywords보다 원본 query를 우선 검사 (LLM이 지역명을 keywords에서 제외하는 경향)

    Args:
        query: 원본 사용자 질문
        keywords: LLM이 추출한 일반 키워드 목록 (폴백용)

    Returns:
        감지된 지역명 목록
    """
    detected_regions = []

    # 1. 원본 쿼리에서 직접 검색 (우선)
    if query:
        for region_name in REGION_CODE_MAP.keys():
            if region_name in query:
                detected_regions.append(region_name)

    # 2. keywords에서도 검색 (폴백)
    if not detected_regions and keywords:
        for kw in keywords:
            # 정확한 매핑 먼저
            if kw in REGION_CODE_MAP:
                detected_regions.append(kw)
            else:
                # 부분 매칭 (예: "서울시" → "서울", "강원도" → "강원")
                for region_name in REGION_CODE_MAP.keys():
                    if region_name in kw or kw in region_name:
                        detected_regions.append(region_name)
                        break

    return list(set(detected_regions))  # 중복 제거


def _build_structured_keyword_hints(structured_keywords: Dict[str, List[str]], keywords: List[str] = None, query: str = None) -> str:
    """Phase 34.5: 구조화된 키워드 기반 SQL 힌트 생성

    Args:
        structured_keywords: {"tech": [...], "country": [...], "region": [...], "filter": [...], "metric": [...]}
        keywords: 일반 키워드 목록 (region 자동 추출 폴백용)
        query: 원본 사용자 질문 (Phase 51.2: 지역 직접 추출용)

    Returns:
        SQL 힌트 문자열
    """
    if not structured_keywords:
        structured_keywords = {}

    # Phase 51.2: region이 비어있으면 원본 쿼리/keywords에서 자동 추출
    region_keywords = structured_keywords.get("region", [])
    if not region_keywords:
        auto_detected = _extract_regions_from_query(query, keywords)
        if auto_detected:
            region_keywords = auto_detected
            logger.info(f"Phase 51.2: 쿼리에서 지역 자동 감지: {auto_detected}")

    if not structured_keywords and not region_keywords:
        return ""

    hints = []
    hints.append("## Phase 34.5: 구조화된 키워드 기반 조건")
    hints.append("")

    # tech 키워드 → 제목/내용 ILIKE
    tech_keywords = structured_keywords.get("tech", [])
    if tech_keywords:
        tech_conditions = " OR ".join(f"conts_klang_nm ILIKE '%{kw}%'" for kw in tech_keywords[:5])
        hints.append("### 기술 키워드 (제목 검색)")
        hints.append("```sql")
        hints.append(f"WHERE ({tech_conditions})")
        hints.append("```")
        hints.append("")

    # country 키워드 → applicant_country 조건
    country_keywords = structured_keywords.get("country", [])
    if country_keywords:
        hints.append("### 국가 필터")
        country_conditions = []
        for c in country_keywords:
            if c == "KR":
                country_conditions.append("applicant_country = 'KR'")
            elif c == "NOT_KR":
                country_conditions.append("applicant_country != 'KR'")
            elif c in ["US", "JP", "CN", "DE", "GB"]:
                country_conditions.append(f"applicant_country = '{c}'")

        if country_conditions:
            hints.append("```sql")
            hints.append(f"WHERE {' AND '.join(country_conditions)}")
            hints.append("```")
        hints.append("")

    # Phase 51: region 키워드 → region_code 필터 (f_equipments용)
    # region_keywords는 함수 시작 부분에서 auto-detect 포함하여 이미 설정됨
    if region_keywords:
        hints.append("### 지역 필터 (장비 검색용)")
        region_codes = []
        for r in region_keywords:
            # 정확한 매핑 먼저 시도
            if r in REGION_CODE_MAP:
                region_codes.append(REGION_CODE_MAP[r])
            else:
                # 부분 일치 검색 (예: "강원도" → "강원")
                for name, code in REGION_CODE_MAP.items():
                    if name in r or r in name:
                        region_codes.append(code)
                        break
        if region_codes:
            hints.append("```sql")
            hints.append(f"-- f_equipments.region_code 또는 f_gis.pnu 앞 2자리 사용")
            if len(region_codes) == 1:
                hints.append(f"WHERE region_code = '{region_codes[0]}'")
            else:
                hints.append(f"WHERE region_code IN ({', '.join(repr(c) for c in region_codes)})")
            hints.append("-- 또는 f_gis JOIN 사용:")
            hints.append(f"-- JOIN f_gis g ON e.conts_id = g.conts_id")
            hints.append(f"-- WHERE SUBSTRING(g.pnu, 1, 2) IN ({', '.join(repr(c) for c in region_codes)})")
            hints.append("```")
        hints.append("")

    # filter 키워드 → LIMIT, 날짜 조건
    filter_keywords = structured_keywords.get("filter", [])
    if filter_keywords:
        hints.append(f"### 필터 조건")
        hints.append(f"추출된 필터: {filter_keywords}")
        hints.append("- 'TOP N', '상위 N개' → LIMIT N")
        hints.append("- '최근 N년' → 현재 연도 기준 날짜 조건")
        hints.append("")

    # metric 키워드 → 분석 유형 힌트
    metric_keywords = structured_keywords.get("metric", [])
    if metric_keywords:
        hints.append(f"### 분석 유형")
        hints.append(f"분석 지표: {metric_keywords}")
        hints.append("- '추이', '변화' → 시계열 GROUP BY")
        hints.append("- '급증', '감소' → 연도별 비교 쿼리")
        hints.append("")

    return "\n".join(hints) if len(hints) > 2 else ""


def _build_table_hints(entity_types: List[str]) -> str:
    """엔티티 타입에 따른 테이블 힌트 생성

    다중 엔티티 타입 쿼리(예: "AI 특허와 관련 연구과제")에서
    SQL이 모든 관련 테이블을 조회하도록 힌트 제공

    Phase 34.4: org 엔티티가 포함된 경우 도메인별 테이블/컬럼 매핑 힌트 추가

    Args:
        entity_types: 엔티티 타입 목록 (예: ["patent", "project"])

    Returns:
        SQL 프롬프트에 포함할 테이블 힌트 문자열
    """
    from workflow.prompts.domain_mapping import ENTITY_TO_TABLE
    from workflow.prompts.schema_context import get_org_mapping_for_domain

    hints = []

    # Phase 34.4: org 엔티티가 있으면 도메인별 매핑 힌트 추가
    if "org" in entity_types:
        org_mapping = get_org_mapping_for_domain(entity_types)
        if org_mapping:
            hints.append("## 기관(org) 엔티티 테이블 매핑")
            hints.append(f"**{org_mapping['description']}** 테이블 사용:")
            hints.append(f"- 테이블: {org_mapping['table']}")
            hints.append(f"- 기관명 컬럼: {org_mapping['column']}")
            if org_mapping.get('country_column'):
                hints.append(f"- 국가 컬럼: {org_mapping['country_column']}")
            if org_mapping.get('join_table'):
                hints.append(f"- JOIN: {org_mapping['join_table']} ON {org_mapping['join_condition']}")
            hints.append("")

    if not entity_types or len(entity_types) < 2:
        # 단일 엔티티 타입이면 org 매핑만 반환
        return "\n".join(hints) if hints else ""

    tables = []
    for et in entity_types:
        if et in ENTITY_TO_TABLE:
            tables.extend(ENTITY_TO_TABLE[et])

    if not tables:
        return "\n".join(hints) if hints else ""

    # 중복 제거 (순서 유지)
    unique_tables = list(dict.fromkeys(tables))

    hints.append("## 다중 엔티티 타입 쿼리")
    hints.append("사용자 질문에서 아래 엔티티 타입들이 감지되었습니다:")
    for et in entity_types:
        hints.append(f"- {et}")
    hints.append("")
    hints.append("**⚠️ 중요: 아래 테이블들을 모두 조회하여 결과를 통합하세요:**")
    for table in unique_tables:
        hints.append(f"- {table}")
    hints.append("")
    hints.append("각 테이블에서 결과를 조회한 후, UNION ALL 또는 별도 쿼리로 통합된 결과를 반환하세요.")

    return "\n".join(hints)




def _execute_single_entity_sql(
    query: str,
    entity_type: str,
    keywords: List[str],
    vector_doc_ids: List[str] = None,
    expanded_keywords: List[str] = None,
    is_aggregation: bool = False,
    query_subtype: str = "list",  # Phase 72.2: ranking 쿼리 지원
    es_doc_ids: List[str] = None  # Phase 94.1: ES Scout에서 검색된 문서 ID
) -> Dict[str, Any]:
    """단일 엔티티 타입에 대한 SQL 실행

    Args:
        query: 원본 사용자 질문
        entity_type: 엔티티 타입 (patent, project 등)
        keywords: 검색 키워드
        vector_doc_ids: 벡터 검색 결과 문서 ID
        expanded_keywords: 확장 키워드
        is_aggregation: 통계/집계 쿼리 여부 (True면 벡터 doc_ids 미사용)
        es_doc_ids: Phase 94.1 ES Scout에서 검색된 문서 ID (높은 우선순위)

    Returns:
        {"sql_result": SQLQueryResult, "generated_sql": str, "entity_type": str}
    """
    from sql.sql_prompts import ENTITY_COLUMNS, ENTITY_LABELS

    entity_config = ENTITY_COLUMNS.get(entity_type)
    if not entity_config:
        return {
            "sql_result": SQLQueryResult(success=False, error=f"Unknown entity type: {entity_type}"),
            "generated_sql": None,
            "entity_type": entity_type
        }

    entity_label = ENTITY_LABELS.get(entity_type, entity_type)

    try:
        sql_agent = get_sql_agent()

        # LLM이 추출한 키워드 그대로 사용 (규칙 기반 필터링 제거 - Phase 20)
        keyword_str = " ".join(keywords) if keywords else ""

        # 키워드가 없으면 경고
        if not keyword_str:
            logger.warning(f"[{entity_type}] LLM 추출 키워드 없음 - SQL 에이전트가 질문에서 직접 추출")

        logger.info(f"[{entity_type}] 사용할 키워드: {keywords}, is_aggregation={is_aggregation}")

        # 엔티티 특화 질문 생성
        entity_query = f"{keyword_str} {entity_label}를 검색해줘" if keyword_str else f"{entity_label} 목록을 검색해줘"

        # 벡터 힌트 구성
        # Phase 27: 통계/집계 쿼리일 때는 벡터 doc_ids 사용 안함 (전체 데이터 대상)
        sql_hints = None
        entity_doc_ids = []  # 초기화 (바깥에서 접근 필요)

        # Phase 94.1: ES Scout doc_ids 우선 사용, 없으면 벡터 doc_ids
        use_es_doc_ids = False
        if es_doc_ids and not is_aggregation:
            entity_doc_ids = es_doc_ids
            use_es_doc_ids = True
            logger.info(f"[{entity_type}] Phase 94.1: ES Scout doc_ids 사용 - {len(es_doc_ids)}개")

        # 통계 쿼리면 벡터 doc_ids 무시
        effective_doc_ids = [] if is_aggregation else vector_doc_ids
        if is_aggregation:
            logger.info(f"[{entity_type}] 통계/집계 쿼리 - 벡터 doc_ids 무시, 전체 데이터 대상 쿼리")

        # Phase 94.1: ES doc_ids가 있으면 벡터 doc_ids 처리 스킵
        if use_es_doc_ids:
            # ES doc_ids 기반 SQL 힌트 생성
            from workflow.nodes.vector_enhancer import build_sql_hints

            # 엔티티별 ID 컬럼 매핑
            entity_id_columns = {
                "patent": "documentid",
                "project": "conts_id",
                "equip": "conts_id",
                "equipment": "conts_id",
                "proposal": "sbjt_id",
            }
            id_column = entity_id_columns.get(entity_type, "documentid")

            # SQL 힌트에 ES doc_ids 조건 추가
            es_ids_str = ", ".join(f"'{did}'" for did in entity_doc_ids[:50])  # 최대 50개
            es_filter_hint = f"""
## Phase 94.1: ES Scout 검색 결과 (필수 적용!)
**반드시 아래 문서 ID 조건을 WHERE절에 포함하세요:**
```sql
WHERE {id_column} IN ({es_ids_str})
```
※ ES에서 검색된 {len(entity_doc_ids)}개 문서만 대상으로 상세 정보를 조회합니다.
"""
            sql_hints = es_filter_hint
            if keywords:
                # 키워드 힌트도 추가 (보조 참고용)
                sql_hints += build_sql_hints(keywords, None, [entity_type], "list")
            logger.info(f"[{entity_type}] Phase 94.1: ES doc_ids 기반 SQL 힌트 생성 ({len(entity_doc_ids)}개 ID)")

            # Phase 94.1: ES doc_ids가 있으면 직접 SQL 실행 (LLM agent 건너뛰기)
            # LLM이 ES doc_ids 힌트를 무시하는 경우가 있으므로 직접 실행
            try:
                # 엔티티별 테이블 및 컬럼 매핑
                entity_table_map = {
                    "patent": "f_patents",
                    "project": "f_projects",
                    "equip": "f_equipments",
                    "equipment": "f_equipments",
                    "proposal": "f_proposal_profile",
                }
                table_name = entity_table_map.get(entity_type, entity_config['table'])

                # 엔티티별 SELECT 컬럼
                entity_select_map = {
                    "patent": "documentid as 특허번호, conts_klang_nm as 특허명, ipc_main as IPC분류, LEFT(ptnaplc_ymd, 4) as 출원년도, ntcd as 등록국가, patent_frst_appn as 최초출원인",
                    "project": "conts_id as 과제ID, conts_klang_nm as 과제명, ancm_yy as 공고연도, tot_rsrh_blgn_amt as 연구비, bucl_nm as 사업분류",
                    "equip": "conts_id as 장비ID, conts_klang_nm as 장비명, org_nm as 보유기관, conts_mclas_nm as 분야, conts_sclas_nm as 장비분류",
                    "equipment": "conts_id as 장비ID, conts_klang_nm as 장비명, org_nm as 보유기관, conts_mclas_nm as 분야, conts_sclas_nm as 장비분류",
                    "proposal": "sbjt_id as 제안서ID, sbjt_nm as 제안서명, orgn_nm as 기관명, dvlp_gole as 개발목표",
                }
                select_cols = entity_select_map.get(entity_type, "*")

                # ID 필터 조건 생성 (최대 50개)
                es_ids_for_query = entity_doc_ids[:50]
                ids_str = ", ".join(f"'{did}'" for did in es_ids_for_query)

                direct_sql = f"""SELECT {select_cols}
FROM "{table_name}"
WHERE {id_column} IN ({ids_str})
LIMIT 20"""

                logger.info(f"[{entity_type}] Phase 94.1: ES doc_ids 기반 직접 SQL 실행")
                logger.debug(f"[{entity_type}] Direct SQL: {direct_sql[:200]}...")

                db_result = sql_agent.execute_raw(direct_sql)

                sql_result = SQLQueryResult(
                    success=db_result.success,
                    columns=db_result.columns,
                    rows=db_result.rows,
                    row_count=db_result.row_count,
                    error=db_result.error,
                    execution_time_ms=db_result.execution_time_ms if hasattr(db_result, 'execution_time_ms') else 0
                )

                logger.info(f"[{entity_type}] Phase 94.1 직접 실행 성공: {sql_result.row_count}행")
                return {
                    "sql_result": sql_result,
                    "generated_sql": direct_sql,
                    "entity_type": entity_type,
                    "search_source": "es_scout"
                }
            except Exception as e:
                logger.error(f"[{entity_type}] Phase 94.1 직접 실행 실패: {e}")
                # 폴백: 기존 LLM agent 사용
                pass

        elif effective_doc_ids or expanded_keywords:
            from workflow.nodes.vector_enhancer import build_sql_hints
            # 해당 엔티티의 doc_ids만 필터링
            # patent: us*, kr*, ep*, jp*, cn* 등 국가코드로 시작
            # project: S로 시작하는 과제번호
            entity_doc_ids = []
            for did in (effective_doc_ids or []):
                did_lower = did.lower()
                if entity_type == "patent":
                    # 특허 ID는 국가코드(us, kr, ep, jp, cn, wo 등)로 시작
                    if any(did_lower.startswith(prefix) for prefix in ["us", "kr", "ep", "jp", "cn", "wo", "de", "gb"]):
                        entity_doc_ids.append(did)
                elif entity_type == "project":
                    # 과제 ID는 S로 시작 또는 숫자로 시작
                    if did.startswith("S") or did[0].isdigit():
                        entity_doc_ids.append(did)
                else:
                    # 기타 엔티티는 모두 포함
                    entity_doc_ids.append(did)

            logger.info(f"[{entity_type}] 필터링된 doc_ids: {len(entity_doc_ids)}개 (전체: {len(effective_doc_ids or [])}개)")

            # Phase 67/72: 엔티티별 확장 키워드 정책
            # - patent/equip: 정확도 우선 → 핵심 키워드만 사용 (확장 키워드 미사용)
            # - 기타 엔티티: AND+OR 패턴 (핵심 필수 + 확장 옵션)
            if keywords:
                if entity_type in ["patent", "equip"]:
                    # Phase 66/72: patent/equip은 확장 키워드 미사용 (정확도 우선)
                    sql_hints = build_sql_hints(keywords, None, [entity_type], "list")
                    logger.info(f"[{entity_type}] Phase 66: 핵심 키워드만 사용={keywords} (확장 미사용)")
                else:
                    # 기타 엔티티: AND+OR 패턴
                    sql_hints = build_sql_hints(keywords, expanded_keywords, [entity_type], "list")
                    logger.info(f"[{entity_type}] Phase 67 AND+OR 패턴: 핵심={keywords}, 확장={expanded_keywords}")

        # 테이블 힌트에 사용할 키워드 결정
        # - 벡터 doc_ids가 있으면: 전체 키워드 사용 (doc_ids로 검색)
        # - 벡터 doc_ids가 없으면: 엔티티 단어 제외한 핵심 키워드만 사용
        entity_words = {"특허", "연구과제", "과제", "장비", "제안서", "공고", "출원인", "기관"}
        if entity_doc_ids:
            hint_keyword = keyword_str if keyword_str else "키워드"
        else:
            # 키워드 폴백 시 엔티티 단어 제외
            filtered_kw = [kw for kw in keywords if kw not in entity_words]
            hint_keyword = filtered_kw[0] if filtered_kw else (keywords[0] if keywords else "키워드")

        # Phase 72.2: query_subtype에 따른 SQL 템플릿 선택
        # ranking 쿼리는 GROUP BY 집계 필요 - LLM 건너뛰고 직접 실행

        # Phase 73: 영향력(피인용) 순위 쿼리 - impact_ranking
        if query_subtype == "impact_ranking" and entity_type == "patent":
            # 국가 필터 추출 (Phase 65)
            country_filter = _extract_country_filter_from_query(query)
            country_clause = f" AND {country_filter}" if country_filter else ""

            # 키워드 필터링 (기술분류 검색용)
            # Phase 73: "특허 영향력" 같은 복합 키워드도 제거
            impact_exclude_words = entity_words | {
                "출원기관", "출원인", "주요", "TOP", "KR", "US", "JP", "CN",
                "한국", "미국", "일본", "중국", "특허", "순위", "분야",
                "영향력", "피인용", "citation", "인용", "특허 영향력", "특허영향력"
            }
            search_keywords = [kw for kw in keywords if kw not in impact_exclude_words and len(kw) > 1]
            # 추가 필터: "영향력", "피인용" 등이 포함된 키워드 제거
            search_keywords = [kw for kw in search_keywords if not any(ex in kw for ex in ["영향력", "피인용", "인용"])]
            if not search_keywords:
                search_keywords = keywords[:3] if keywords else ["키워드"]

            # Phase 73: 기술분류 기반 검색 (conts_mclas_nm, conts_sclas_nm)
            # 영향력 순위는 기술분야 기반으로 검색해야 정확함
            keyword_conditions = " OR ".join(
                f"(p.conts_mclas_nm ILIKE '%{kw}%' OR p.conts_sclas_nm ILIKE '%{kw}%' OR p.conts_klang_nm ILIKE '%{kw}%')"
                for kw in search_keywords[:5]
            )

            # Phase 73: 영향력 순위 CTE 쿼리
            # 출원기관별: 특허수, 총피인용, 평균피인용(0포함), 평균피인용(1이상), 피인용max, 대표특허
            direct_sql = f"""WITH patent_stats AS (
    SELECT
        p.patent_frst_appn as 출원기관,
        p.patent_frst_appn_ntnlty as 국적,
        COUNT(*) as 대상특허수,
        SUM(CAST(NULLIF(p.citation_cnt, '') AS INTEGER)) as 총피인용,
        AVG(CAST(NULLIF(p.citation_cnt, '') AS FLOAT)) as 평균피인용_0포함,
        AVG(CASE WHEN CAST(NULLIF(p.citation_cnt, '') AS INTEGER) >= 1
            THEN CAST(p.citation_cnt AS FLOAT) END) as 평균피인용_1이상,
        MAX(CAST(NULLIF(p.citation_cnt, '') AS INTEGER)) as 피인용max
    FROM f_patents p
    WHERE ({keyword_conditions}){country_clause}
      AND p.patent_frst_appn IS NOT NULL
    GROUP BY p.patent_frst_appn, p.patent_frst_appn_ntnlty
    HAVING COUNT(*) >= 2
),
max_citation_patent AS (
    SELECT DISTINCT ON (p.patent_frst_appn)
        p.patent_frst_appn,
        p.conts_klang_nm as 대표특허명
    FROM f_patents p
    WHERE ({keyword_conditions}){country_clause}
      AND p.patent_frst_appn IS NOT NULL
    ORDER BY p.patent_frst_appn, CAST(NULLIF(p.citation_cnt, '') AS INTEGER) DESC NULLS LAST
)
SELECT
    ps.출원기관,
    ps.국적,
    ps.대상특허수,
    COALESCE(ps.총피인용, 0) as 총피인용,
    ROUND(COALESCE(ps.평균피인용_0포함, 0)::numeric, 2) as "평균피인용(0포함)",
    ROUND(ps.평균피인용_1이상::numeric, 2) as "평균피인용(1이상)",
    COALESCE(ps.피인용max, 0) as 피인용max,
    LEFT(mp.대표특허명, 40) as "대표특허명(피인용max)"
FROM patent_stats ps
LEFT JOIN max_citation_patent mp ON ps.출원기관 = mp.patent_frst_appn
ORDER BY ps.평균피인용_0포함 DESC NULLS LAST
LIMIT 10"""
            logger.info(f"[{entity_type}] Phase 73: impact_ranking 쿼리 → 직접 SQL 실행")
            logger.info(f"[{entity_type}] Direct SQL (impact): {direct_sql[:300]}...")

            # 직접 SQL 실행
            try:
                db_result = sql_agent.execute_raw(direct_sql)

                sql_result = SQLQueryResult(
                    success=db_result.success,
                    columns=db_result.columns,
                    rows=db_result.rows,
                    row_count=db_result.row_count,
                    error=db_result.error,
                    execution_time_ms=db_result.execution_time_ms if hasattr(db_result, 'execution_time_ms') else 0
                )
                logger.info(f"[{entity_type}] Phase 73 직접 실행 성공: {sql_result.row_count}행")
                return {
                    "sql_result": sql_result,
                    "generated_sql": direct_sql,
                    "entity_type": entity_type
                }
            except Exception as e:
                logger.error(f"[{entity_type}] Phase 73 직접 실행 실패: {e}")
                # 폴백: 일반 ranking 쿼리로 전환
                query_subtype = "ranking"

        # Phase 73.1: 국적별 분리 순위 쿼리 - nationality_ranking
        if query_subtype == "nationality_ranking" and entity_type == "patent":
            # 국가 필터 추출 (Phase 65)
            country_filter = _extract_country_filter_from_query(query)
            country_clause = f" AND {country_filter}" if country_filter else ""

            # 키워드 필터링 (기술분류 검색용)
            nationality_exclude_words = entity_words | {
                "출원기관", "출원인", "주요", "TOP", "KR", "US", "JP", "CN",
                "한국", "미국", "일본", "중국", "특허", "순위", "분야",
                "국적별", "자국", "타국", "국내외", "구분해서", "국적으로", "구분"
            }
            search_keywords = [kw for kw in keywords if kw not in nationality_exclude_words and len(kw) > 1]
            if not search_keywords:
                search_keywords = keywords[:3] if keywords else ["키워드"]

            # 기술분류 기반 검색
            keyword_conditions = " OR ".join(
                f"(p.conts_mclas_nm ILIKE '%{kw}%' OR p.conts_sclas_nm ILIKE '%{kw}%' OR p.conts_klang_nm ILIKE '%{kw}%')"
                for kw in search_keywords[:5]
            )

            # Phase 73.1: 자국기업 (KR) TOP 10
            domestic_sql = f"""WITH domestic_stats AS (
    SELECT
        p.patent_frst_appn as 기관명,
        p.patent_frst_appn_ntnlty as 국적,
        COUNT(*) as 대상특허수,
        MAX(CAST(NULLIF(p.citation_cnt, '') AS INTEGER)) as 최대피인용수,
        ROUND(AVG(CAST(NULLIF(p.citation_cnt, '') AS FLOAT))::numeric, 2) as 평균피인용수,
        ROUND(AVG(CAST(NULLIF(p.claim_cnt, '') AS FLOAT))::numeric, 1) as 평균청구항수,
        MAX(p.ptnaplc_ymd) as 최근출원일
    FROM f_patents p
    WHERE ({keyword_conditions}){country_clause}
      AND p.patent_frst_appn_ntnlty = 'KR'
      AND p.patent_frst_appn IS NOT NULL
    GROUP BY p.patent_frst_appn, p.patent_frst_appn_ntnlty
    HAVING COUNT(*) >= 2
),
domestic_representative AS (
    SELECT DISTINCT ON (p.patent_frst_appn)
        p.patent_frst_appn,
        p.conts_klang_nm as 대표특허명
    FROM f_patents p
    WHERE ({keyword_conditions}){country_clause}
      AND p.patent_frst_appn_ntnlty = 'KR'
      AND p.patent_frst_appn IS NOT NULL
    ORDER BY p.patent_frst_appn, CAST(NULLIF(p.citation_cnt, '') AS INTEGER) DESC NULLS LAST
)
SELECT ds.기관명, ds.국적, ds.대상특허수,
       COALESCE(ds.최대피인용수, 0) as 최대피인용수,
       COALESCE(ds.평균피인용수, 0) as 평균피인용수,
       COALESCE(ds.평균청구항수, 0) as 평균청구항수,
       ds.최근출원일,
       LEFT(dr.대표특허명, 40) as "대표특허명(피인용max)"
FROM domestic_stats ds
LEFT JOIN domestic_representative dr ON ds.기관명 = dr.patent_frst_appn
ORDER BY ds.대상특허수 DESC
LIMIT 10"""

            # Phase 73.1: 타국기업 (NOT KR) TOP 10
            foreign_sql = f"""WITH foreign_stats AS (
    SELECT
        p.patent_frst_appn as 기관명,
        p.patent_frst_appn_ntnlty as 국적,
        COUNT(*) as 대상특허수,
        MAX(CAST(NULLIF(p.citation_cnt, '') AS INTEGER)) as 최대피인용수,
        ROUND(AVG(CAST(NULLIF(p.citation_cnt, '') AS FLOAT))::numeric, 2) as 평균피인용수,
        ROUND(AVG(CAST(NULLIF(p.claim_cnt, '') AS FLOAT))::numeric, 1) as 평균청구항수,
        MAX(p.ptnaplc_ymd) as 최근출원일
    FROM f_patents p
    WHERE ({keyword_conditions}){country_clause}
      AND p.patent_frst_appn_ntnlty != 'KR'
      AND p.patent_frst_appn IS NOT NULL
    GROUP BY p.patent_frst_appn, p.patent_frst_appn_ntnlty
    HAVING COUNT(*) >= 2
),
foreign_representative AS (
    SELECT DISTINCT ON (p.patent_frst_appn)
        p.patent_frst_appn,
        p.conts_klang_nm as 대표특허명
    FROM f_patents p
    WHERE ({keyword_conditions}){country_clause}
      AND p.patent_frst_appn_ntnlty != 'KR'
      AND p.patent_frst_appn IS NOT NULL
    ORDER BY p.patent_frst_appn, CAST(NULLIF(p.citation_cnt, '') AS INTEGER) DESC NULLS LAST
)
SELECT fs.기관명, fs.국적, fs.대상특허수,
       COALESCE(fs.최대피인용수, 0) as 최대피인용수,
       COALESCE(fs.평균피인용수, 0) as 평균피인용수,
       COALESCE(fs.평균청구항수, 0) as 평균청구항수,
       fs.최근출원일,
       LEFT(fr.대표특허명, 40) as "대표특허명(피인용max)"
FROM foreign_stats fs
LEFT JOIN foreign_representative fr ON fs.기관명 = fr.patent_frst_appn
ORDER BY fs.대상특허수 DESC
LIMIT 10"""

            logger.info(f"[{entity_type}] Phase 73.1: nationality_ranking 쿼리 → 자국/타국 2개 쿼리 실행")

            # 자국/타국 쿼리 실행
            try:
                domestic_result = sql_agent.execute_raw(domestic_sql)
                foreign_result = sql_agent.execute_raw(foreign_sql)

                # 결과 병합 (자국 + 타국)
                combined_columns = ["구분"] + (domestic_result.columns if domestic_result.success else [])
                combined_rows = []

                if domestic_result.success and domestic_result.rows:
                    for row in domestic_result.rows:
                        combined_rows.append(["자국기업"] + list(row))

                if foreign_result.success and foreign_result.rows:
                    for row in foreign_result.rows:
                        combined_rows.append(["타국기업"] + list(row))

                sql_result = SQLQueryResult(
                    success=True,
                    columns=combined_columns,
                    rows=combined_rows,
                    row_count=len(combined_rows),
                    error=None,
                    execution_time_ms=0
                )
                logger.info(f"[{entity_type}] Phase 73.1 직접 실행 성공: 자국 {domestic_result.row_count}행, 타국 {foreign_result.row_count}행")
                return {
                    "sql_result": sql_result,
                    "generated_sql": f"-- 자국기업\n{domestic_sql}\n\n-- 타국기업\n{foreign_sql}",
                    "entity_type": entity_type
                }
            except Exception as e:
                logger.error(f"[{entity_type}] Phase 73.1 직접 실행 실패: {e}")
                # 폴백: 일반 ranking 쿼리로 전환
                query_subtype = "ranking"

        if query_subtype == "ranking" and entity_type == "patent":
            # 국가 필터 추출 (Phase 65)
            country_filter = _extract_country_filter_from_query(query)
            country_clause = f" AND {country_filter}" if country_filter else ""

            # Phase 90.1: 키워드 필터링 완화 - 기술 키워드 유지
            # 메타 단어만 제외, entity_words(특허, 논문 등)도 별도 제외
            ranking_exclude_words = {
                "출원기관", "출원인", "주요", "TOP", "순위", "분야", "기관"
            }
            # entity_words는 별도로 제외 (특허, 논문 등 엔티티 타입 단어)
            search_keywords = [
                kw for kw in keywords
                if kw not in ranking_exclude_words
                and kw not in entity_words
                and len(kw) > 1
            ]
            if not search_keywords:
                search_keywords = keywords[:3] if keywords else ["키워드"]

            # Phase 90.1: 검색 필드 확장 - 제목 + 요약 검색
            # 참고: patent_abstc_ko가 실제 컬럼명 (conts_klang_abst 아님)
            field_conditions = []
            for kw in search_keywords[:5]:
                field_conditions.append(
                    f"(p.conts_klang_nm ILIKE '%{kw}%' OR p.patent_abstc_ko ILIKE '%{kw}%')"
                )
            keyword_conditions = " OR ".join(field_conditions)

            # Phase 72.3: 특허 출원기관 순위 - 기관명 정규화 (끝 마침표 제거)
            # Phase 72.4: 대표 특허 (최근 특허) 추가
            # "마이크론 테크놀로지, 인크." vs "마이크론 테크놀로지, 인크" 중복 방지
            # applicant_code는 동일 기관도 다른 코드를 가지므로 문자열 정규화 사용
            direct_sql = f"""WITH org_stats AS (
    SELECT
        RTRIM(REGEXP_REPLACE(a.applicant_name, '[.]+$', '')) as 출원기관,
        COUNT(DISTINCT p.documentid) as 특허수
    FROM "f_patents" p
    JOIN "f_patent_applicants" a ON p.documentid = a.document_id
    WHERE ({keyword_conditions}){country_clause}
    GROUP BY RTRIM(REGEXP_REPLACE(a.applicant_name, '[.]+$', ''))
),
representative_patent AS (
    SELECT DISTINCT ON (RTRIM(REGEXP_REPLACE(a.applicant_name, '[.]+$', '')))
        RTRIM(REGEXP_REPLACE(a.applicant_name, '[.]+$', '')) as 출원기관,
        LEFT(p.conts_klang_nm, 40) as 대표특허
    FROM "f_patents" p
    JOIN "f_patent_applicants" a ON p.documentid = a.document_id
    WHERE ({keyword_conditions}){country_clause}
    ORDER BY RTRIM(REGEXP_REPLACE(a.applicant_name, '[.]+$', '')), p.ptnaplc_ymd DESC
)
SELECT os.출원기관, os.특허수, rp.대표특허
FROM org_stats os
LEFT JOIN representative_patent rp ON os.출원기관 = rp.출원기관
ORDER BY os.특허수 DESC
LIMIT 10"""
            logger.info(f"[{entity_type}] Phase 72.2: ranking 쿼리 → 직접 SQL 실행 (LLM 건너뜀)")
            logger.info(f"[{entity_type}] Direct SQL: {direct_sql[:200]}...")

            # 직접 SQL 실행 (기존 sql_agent 재사용)
            try:
                db_result = sql_agent.execute_raw(direct_sql)

                sql_result = SQLQueryResult(
                    success=db_result.success,
                    columns=db_result.columns,
                    rows=db_result.rows,
                    row_count=db_result.row_count,
                    error=db_result.error,
                    execution_time_ms=db_result.execution_time_ms if hasattr(db_result, 'execution_time_ms') else 0
                )
                logger.info(f"[{entity_type}] Phase 72.2 직접 실행 성공: {sql_result.row_count}행")

                # Phase 90.1: SQL 결과 0건 시 ES 폴백
                if sql_result.row_count == 0:
                    logger.warning(f"[{entity_type}] SQL 결과 0건 → ES 폴백 시도")
                    es_result = _fallback_to_es_ranking(query, search_keywords, entity_type)
                    if es_result and es_result.row_count > 0:
                        logger.info(f"[{entity_type}] ES 폴백 성공: {es_result.row_count}행")
                        return {
                            "sql_result": es_result,
                            "generated_sql": f"-- ES fallback for: {direct_sql[:100]}...",
                            "entity_type": entity_type,
                            "search_source": "elasticsearch"
                        }

                return {
                    "sql_result": sql_result,
                    "generated_sql": direct_sql,
                    "entity_type": entity_type
                }
            except Exception as e:
                logger.error(f"[{entity_type}] Phase 72.2 직접 실행 실패: {e}")
                # 폴백: ES 시도 후 LLM 에이전트
                es_result = _fallback_to_es_ranking(query, search_keywords, entity_type)
                if es_result and es_result.row_count > 0:
                    logger.info(f"[{entity_type}] ES 폴백 성공: {es_result.row_count}행")
                    return {
                        "sql_result": es_result,
                        "generated_sql": f"-- ES fallback due to SQL error: {e}",
                        "entity_type": entity_type,
                        "search_source": "elasticsearch"
                    }
                # 최종 폴백: LLM 에이전트 사용
                sql_template = entity_config['sql_template'].format(keyword=hint_keyword)

        # Phase 104.3: project ranking 쿼리 - 기관별 과제 수행 집계
        elif query_subtype == "ranking" and entity_type == "project":
            # 키워드 필터링 - 메타 단어 제외
            ranking_exclude_words = {
                "수행기관", "참여기관", "주요", "TOP", "순위", "분야", "기관", "역량"
            }
            search_keywords = [
                kw for kw in keywords
                if kw not in ranking_exclude_words
                and kw not in entity_words
                and len(kw) > 1
            ]
            if not search_keywords:
                search_keywords = keywords[:3] if keywords else ["키워드"]

            # 키워드 조건 생성 (과제명 + 키워드 검색)
            field_conditions = []
            for kw in search_keywords[:5]:
                field_conditions.append(
                    f"(pp.sbjt_nm ILIKE '%{kw}%')"
                )
            keyword_conditions = " OR ".join(field_conditions) if field_conditions else "1=1"

            # Phase 104.5: 기관별 과제 수행 집계 SQL
            # - 기관명 + 과제수 + 대표과제(수행연도 포함)
            # - ptcp_orgn_role_se는 코드(MK20XX)이므로 역할 필터 제거
            direct_sql = f"""WITH org_stats AS (
    SELECT
        po.orgn_nm as 기관명,
        COUNT(DISTINCT po.sbjt_id) as 과제수
    FROM "f_proposal_orgn" po
    JOIN "f_proposal_profile" pp ON po.sbjt_id = pp.sbjt_id
    WHERE ({keyword_conditions})
      AND po.orgn_nm IS NOT NULL AND po.orgn_nm <> ''
    GROUP BY po.orgn_nm
),
representative_project AS (
    SELECT DISTINCT ON (po.orgn_nm)
        po.orgn_nm as 기관명,
        LEFT(pp.sbjt_nm, 50) || ' (' || COALESCE(pp.ancm_yy, '') || ')' as 대표과제
    FROM "f_proposal_orgn" po
    JOIN "f_proposal_profile" pp ON po.sbjt_id = pp.sbjt_id
    WHERE ({keyword_conditions})
      AND po.orgn_nm IS NOT NULL AND po.orgn_nm <> ''
    ORDER BY po.orgn_nm, pp.ancm_yy DESC NULLS LAST, pp.sbjt_id DESC
)
SELECT os.기관명, os.과제수, rp.대표과제
FROM org_stats os
LEFT JOIN representative_project rp ON os.기관명 = rp.기관명
ORDER BY os.과제수 DESC
LIMIT 20"""
            logger.info(f"[{entity_type}] Phase 104.3: project ranking 쿼리 → 직접 SQL 실행")
            logger.info(f"[{entity_type}] Direct SQL: {direct_sql[:200]}...")

            # 직접 SQL 실행
            try:
                db_result = sql_agent.execute_raw(direct_sql)

                sql_result = SQLQueryResult(
                    success=db_result.success,
                    columns=db_result.columns,
                    rows=db_result.rows,
                    row_count=db_result.row_count,
                    error=db_result.error,
                    execution_time_ms=db_result.execution_time_ms if hasattr(db_result, 'execution_time_ms') else 0
                )
                logger.info(f"[{entity_type}] Phase 104.3 직접 실행 성공: {sql_result.row_count}행")

                return {
                    "sql_result": sql_result,
                    "generated_sql": direct_sql,
                    "entity_type": entity_type
                }
            except Exception as e:
                logger.error(f"[{entity_type}] Phase 104.3 직접 실행 실패: {e}")
                # 폴백: LLM 에이전트 사용
                sql_template = entity_config['sql_template'].format(keyword=hint_keyword)

        else:
            sql_template = entity_config['sql_template'].format(keyword=hint_keyword)

        # 엔티티별 테이블 힌트 추가
        table_hint = f"""## 검색 대상 엔티티: {entity_label}
사용할 테이블: {entity_config['table']}
반환할 컬럼: {', '.join(entity_config['aliases'])}

표준 SQL 패턴:
{sql_template}
"""
        # Phase 51.2: equip 엔티티일 때 지역 필터 힌트 추가
        if entity_type == "equip":
            detected_regions = _extract_regions_from_query(query, keywords)
            if detected_regions:
                region_codes = [REGION_CODE_MAP[r] for r in detected_regions if r in REGION_CODE_MAP]
                if region_codes:
                    logger.info(f"[equip] 지역 필터 감지: {detected_regions} → region_codes={region_codes}")
                    region_hint = f"""
## 지역 필터 (Phase 51.2)
**반드시 region_code 조건을 WHERE절에 포함하세요:**
```sql
WHERE region_code = '{region_codes[0]}'{' AND (' + hint_keyword + ' 조건)' if hint_keyword else ''}
```
"""
                    table_hint = table_hint + "\n" + region_hint

        # Phase 65: patent 엔티티일 때 등록국가 필터 힌트 추가
        if entity_type == "patent":
            country_filter_sql = _extract_country_filter_from_query(query)
            if country_filter_sql:
                logger.info(f"[patent] 등록국가 필터 감지: {country_filter_sql}")
                country_hint = f"""
## 등록국가 필터 (Phase 65 - 필수!)
**반드시 WHERE절에 등록국가(ntcd) 조건을 포함하세요:**
```sql
SELECT p.documentid as 특허번호, p.conts_klang_nm as 특허명,
       p.ipc_main as IPC분류, p.ptnaplc_ymd as 출원일,
       p.ntcd as 등록국가, p.patent_frst_appn as 최초출원인
FROM "f_patents" p
WHERE p.conts_klang_nm ILIKE '%키워드%'
  AND {country_filter_sql}
LIMIT 10
```
※ 등록국가(ntcd)는 특허청 국가 (KR=한국특허청, US=미국특허청)
※ 출원인 국적 조회가 필요하면 f_patent_applicants JOIN 사용
"""
                table_hint = table_hint + "\n" + country_hint

        if sql_hints:
            sql_hints = sql_hints + "\n\n" + table_hint
        else:
            sql_hints = table_hint

        # SQL 실행
        response = sql_agent.query(
            question=entity_query,
            interpret_result=False,
            max_tokens=1024,
            temperature=0.3,
            sql_hints=sql_hints
        )

        sql_result = SQLQueryResult(
            success=response.result.success,
            columns=response.result.columns,
            rows=response.result.rows,
            row_count=response.result.row_count,
            error=response.result.error,
            execution_time_ms=response.result.execution_time_ms
        )

        logger.info(f"[{entity_type}] SQL 실행 성공: {response.result.row_count}행")

        return {
            "sql_result": sql_result,
            "generated_sql": response.generated_sql,
            "entity_type": entity_type
        }

    except Exception as e:
        logger.error(f"[{entity_type}] SQL 실행 실패: {e}")
        return {
            "sql_result": SQLQueryResult(success=False, error=str(e)),
            "generated_sql": None,
            "entity_type": entity_type
        }


def _execute_multi_entity_sql(
    query: str,
    entity_types: List[str],
    keywords: List[str],
    vector_doc_ids: List[str] = None,
    expanded_keywords: List[str] = None,
    is_aggregation: bool = False,
    entity_keywords: Dict[str, List[str]] = None,  # Phase 53: 엔티티별 키워드
    query_subtype: str = "list",  # Phase 72.2: ranking 쿼리 지원
    es_doc_ids: Dict[str, List[str]] = None  # Phase 94.1: ES Scout 도메인별 문서 ID
) -> Dict[str, SQLQueryResult]:
    """다중 엔티티 타입에 대해 병렬로 SQL 실행

    Phase 53: 엔티티별 독립 키워드 지원
    Phase 94.1: ES Scout 도메인별 문서 ID 지원

    Args:
        query: 원본 사용자 질문
        entity_types: 엔티티 타입 목록
        keywords: 검색 키워드 (폴백용)
        vector_doc_ids: 벡터 검색 결과 문서 ID
        expanded_keywords: 확장 키워드 (폴백용)
        is_aggregation: 통계/집계 쿼리 여부
        entity_keywords: Phase 53 - 엔티티별 키워드 {"patent": [...], "project": [...]}
        es_doc_ids: Phase 94.1 - 도메인별 ES 문서 ID {"patent": [...], "project": [...]}

    Returns:
        엔티티별 SQLQueryResult 딕셔너리
    """
    results = {}

    # 병렬 실행
    with ThreadPoolExecutor(max_workers=len(entity_types)) as executor:
        futures = {}
        for entity_type in entity_types:
            # Phase 53: 엔티티별 키워드 사용 (없으면 공통 키워드 폴백)
            if entity_keywords and entity_type in entity_keywords:
                specific_keywords = entity_keywords[entity_type]
                specific_expanded = entity_keywords[entity_type]  # 확장 키워드도 동일
                logger.info(f"[{entity_type}] Phase 53 엔티티별 키워드 사용: {specific_keywords}")
            else:
                specific_keywords = keywords
                specific_expanded = expanded_keywords
                logger.info(f"[{entity_type}] 공통 키워드 폴백 사용: {specific_keywords}")

            # Phase 94.1: 도메인별 ES doc_ids 추출
            # entity_type과 ES 도메인 매핑
            entity_to_domain = {
                "patent": "patent",
                "project": "project",
                "equip": "equipment",
                "equipment": "equipment",
                "proposal": "proposal",
            }
            domain = entity_to_domain.get(entity_type, entity_type)
            entity_es_doc_ids = es_doc_ids.get(domain, []) if es_doc_ids else []

            if entity_es_doc_ids:
                logger.info(f"[{entity_type}] Phase 94.1: ES doc_ids {len(entity_es_doc_ids)}개 전달")

            future = executor.submit(
                _execute_single_entity_sql,
                query,
                entity_type,
                specific_keywords,
                vector_doc_ids,
                specific_expanded,
                is_aggregation,
                query_subtype,  # Phase 72.2: ranking 쿼리 지원
                entity_es_doc_ids  # Phase 94.1: ES Scout 도메인별 문서 ID
            )
            futures[future] = entity_type

        for future in as_completed(futures):
            entity_type = futures[future]
            try:
                result = future.result(timeout=30)
                results[entity_type] = result["sql_result"]
                logger.info(f"[{entity_type}] 결과 수신: {result['sql_result'].row_count}행")
            except Exception as e:
                logger.error(f"[{entity_type}] 실행 오류: {e}")
                results[entity_type] = SQLQueryResult(success=False, error=str(e))

    return results


def _execute_tech_classification_recommendation(
    keywords: List[str],
    classification_type: str = "SAF006"
) -> Dict[str, Any]:
    """Phase 62: 기술분류 추천을 위한 통계 쿼리 실행

    제안서 키워드 검색 → 사용된 분류코드 통계 → TOP N 추천

    Args:
        keywords: 검색 키워드 목록 (예: ["전력반도체"])
        classification_type: 분류체계 유형 (SAF006=신산업기술분류, SAF002=6T 등)

    Returns:
        {"sql_result": SQLQueryResult, "generated_sql": str, "classification_label": str}
    """
    from sql.sql_prompts import CLASSIFICATION_TYPE_LABELS

    # 분류체계 한글 라벨 가져오기
    classification_label = CLASSIFICATION_TYPE_LABELS.get(classification_type, classification_type)

    if not keywords:
        return {
            "sql_result": SQLQueryResult(
                success=False,
                error="검색 키워드가 없습니다."
            ),
            "generated_sql": None,
            "classification_label": classification_label
        }

    # 키워드 OR 조건 생성
    keyword_conditions = " OR ".join(f"p.sbjt_nm ILIKE '%{kw}%'" for kw in keywords[:3])

    # Phase 63: 기술분류 통계 쿼리 (비율 계산 포함)
    # LIMIT 전에 전체 합계를 계산해서 정확한 비율 산출
    sql = f"""
WITH stats AS (
    SELECT t.tecl_cd, t.tecl_nm, COUNT(*) as cnt
    FROM f_proposal_techclsf t
    JOIN f_proposal_profile p ON t.sbjt_id = p.sbjt_id
    WHERE ({keyword_conditions})
      AND t.tecl_tp_se = '{classification_type}'
      AND t.tecl_nm IS NOT NULL
      AND t.tecl_nm <> ''
      AND t.tecl_nm <> '기타'
    GROUP BY t.tecl_cd, t.tecl_nm
)
SELECT tecl_cd as 기술코드, tecl_nm as 기술명, cnt as 사용건수,
       ROUND(cnt * 100.0 / SUM(cnt) OVER(), 1) as 비율
FROM stats
ORDER BY cnt DESC
LIMIT 10
"""

    logger.info(f"Phase 62: 기술분류 추천 쿼리 실행 - keywords={keywords}, classification_type={classification_type}")

    try:
        from sql.db_connector import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        cur.close()
        conn.close()

        sql_result = SQLQueryResult(
            success=True,
            columns=columns,
            rows=[list(row) for row in rows],
            row_count=len(rows)
        )

        logger.info(f"Phase 62: 기술분류 추천 결과 - {len(rows)}건 (분류체계: {classification_label})")

        return {
            "sql_result": sql_result,
            "generated_sql": sql,
            "classification_label": classification_label
        }

    except Exception as e:
        logger.error(f"Phase 62: 기술분류 추천 쿼리 실패 - {e}")
        return {
            "sql_result": SQLQueryResult(success=False, error=str(e)),
            "generated_sql": sql,
            "classification_label": classification_label
        }


def _detect_classification_type_from_query(query: str) -> str:
    """Phase 62: 질문에서 분류체계 유형 자동 감지

    Args:
        query: 사용자 질문

    Returns:
        분류체계 SAF 코드 (기본값: SAF006 = 신산업기술분류코드)
    """
    from sql.sql_prompts import CLASSIFICATION_TYPE_MAPPING

    # 질문에서 분류체계 키워드 탐지
    for keyword, saf_code in CLASSIFICATION_TYPE_MAPPING.items():
        if keyword.lower() in query.lower():
            logger.info(f"Phase 62: 분류체계 감지 - '{keyword}' → {saf_code}")
            return saf_code

    # 기본값: 신산업기술분류코드 (가장 많이 사용)
    return "SAF006"


def _query_proposal_orgs(keywords: List[str]) -> Dict[str, Any]:
    """Phase 71: 과제 수행기관 조회 (역할별 집계 + 최근 과제명)

    Args:
        keywords: 검색 키워드 목록

    Returns:
        {"rows": List, "columns": List, "sql": str}
    """
    keyword_conditions = " OR ".join(
        f"p.sbjt_nm ILIKE '%{kw}%'"
        for kw in keywords[:3]
    )

    # Phase 71: 서브쿼리 패턴 (CTE 대신) - SQL validation 통과용
    sql = f"""
SELECT
    os.orgn_nm as 기관명,
    os.수행횟수,
    os.주관,
    os.참여,
    os.협력,
    (
        SELECT p2.sbjt_nm
        FROM f_proposal_profile p2
        JOIN f_proposal_orgn po2 ON p2.sbjt_id = po2.sbjt_id
        WHERE po2.orgn_nm = os.orgn_nm AND ({keyword_conditions.replace('p.sbjt_nm', 'p2.sbjt_nm')})
        ORDER BY p2.sbjt_id DESC
        LIMIT 1
    ) as 최근과제명
FROM (
    SELECT
        po.orgn_nm,
        COUNT(DISTINCT p.sbjt_id) as 수행횟수,
        SUM(CASE WHEN po.ptcp_orgn_role_se = 'MK2002' THEN 1 ELSE 0 END) as 주관,
        SUM(CASE WHEN po.ptcp_orgn_role_se = 'MK2003' THEN 1 ELSE 0 END) as 참여,
        SUM(CASE WHEN po.ptcp_orgn_role_se = 'MK2004' THEN 1 ELSE 0 END) as 협력
    FROM f_proposal_profile p
    JOIN f_proposal_orgn po ON p.sbjt_id = po.sbjt_id
    WHERE ({keyword_conditions})
      AND po.orgn_nm IS NOT NULL
      AND LENGTH(po.orgn_nm) > 1
      AND po.ptcp_orgn_role_se IN ('MK2002', 'MK2003', 'MK2004')
    GROUP BY po.orgn_nm
    HAVING COUNT(DISTINCT p.sbjt_id) >= 1
) os
ORDER BY os.수행횟수 DESC
LIMIT 15;
"""
    try:
        from sql.sql_agent import SQLAgent
        sql_agent = SQLAgent()
        result = sql_agent.execute_raw(sql)
        if result.success:
            return {"rows": result.rows, "columns": result.columns, "sql": sql, "success": True}
        return {"rows": [], "columns": [], "sql": sql, "success": False, "error": result.error}
    except Exception as e:
        return {"rows": [], "columns": [], "sql": sql, "success": False, "error": str(e)}


def _query_patent_orgs(keywords: List[str]) -> Dict[str, Any]:
    """Phase 71: 특허 기반 협업 기관 조회 (출원인 + 대표특허)

    Args:
        keywords: 검색 키워드 목록

    Returns:
        {"rows": List, "columns": List, "sql": str}
    """
    keyword_conditions = " OR ".join(
        f"p.conts_klang_nm ILIKE '%{kw}%'"
        for kw in keywords[:3]
    )

    # Phase 71: 서브쿼리 패턴 (CTE 대신) - SQL validation 통과용
    sql = f"""
SELECT
    ps.applicant_name as 기관명,
    ps.applicant_country as 국가,
    ps.특허수,
    (
        SELECT p2.conts_klang_nm
        FROM f_patents p2
        JOIN f_patent_applicants a2 ON p2.documentid = a2.document_id
        WHERE a2.applicant_name = ps.applicant_name AND ({keyword_conditions.replace('p.conts_klang_nm', 'p2.conts_klang_nm')})
        ORDER BY p2.documentid DESC
        LIMIT 1
    ) as 대표특허명
FROM (
    SELECT
        a.applicant_name,
        a.applicant_country,
        COUNT(DISTINCT p.documentid) as 특허수
    FROM f_patents p
    JOIN f_patent_applicants a ON p.documentid = a.document_id
    WHERE ({keyword_conditions})
      AND a.applicant_name IS NOT NULL
      AND LENGTH(a.applicant_name) > 1
    GROUP BY a.applicant_name, a.applicant_country
    HAVING COUNT(DISTINCT p.documentid) >= 1
) ps
ORDER BY ps.특허수 DESC
LIMIT 15;
"""
    try:
        from sql.sql_agent import SQLAgent
        sql_agent = SQLAgent()
        result = sql_agent.execute_raw(sql)
        if result.success:
            return {"rows": result.rows, "columns": result.columns, "sql": sql, "success": True}
        return {"rows": [], "columns": [], "sql": sql, "success": False, "error": result.error}
    except Exception as e:
        return {"rows": [], "columns": [], "sql": sql, "success": False, "error": str(e)}


def _get_org_community_info(org_names: List[str]) -> Dict[str, int]:
    """Phase 75.2: 기관명으로 cuGraph 커뮤니티 정보 조회

    Args:
        org_names: 기관명 목록

    Returns:
        {"기관명": 커뮤니티ID} 딕셔너리
    """
    community_map = {}
    try:
        from graph.graph_builder import get_knowledge_graph
        from graph.cugraph_client import get_cugraph_helper

        helper = get_cugraph_helper()
        # 커뮤니티 캐시 로드 (이미 로드되어 있으면 빠름)
        if not helper._community_cache.get("713365bb"):
            result = helper.client.community_detection("713365bb", top_k=50000)
            for item in result.get("results", []):
                vertex = item.get("vertex", "")
                if vertex.startswith("org_"):
                    community_map[vertex] = item.get("partition")
            helper._community_cache["713365bb"] = community_map
        else:
            # 캐시에서 org_ 노드만 추출
            cached = helper._community_cache.get("713365bb", {})
            for vertex, partition in cached.items():
                if vertex.startswith("org_"):
                    community_map[vertex] = partition

        logger.info(f"Phase 75.2: 커뮤니티 정보 로드 - {len(community_map)}개 기관 노드")

    except Exception as e:
        logger.warning(f"Phase 75.2: 커뮤니티 정보 조회 실패 - {e}")

    return community_map


# ============================================================================
# Phase 99: 장비 검색 ES/Qdrant → SQL 확장 헬퍼 함수
# ============================================================================

def _search_equipment_es(keywords: List[str], region: str = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Phase 99: 장비 전용 ES 검색 (다중 필드)

    ES 인덱스 ax_equipments에서 검색:
    - conts_klang_nm (장비명) - 가중치 3
    - equip_desc (설명) - 가중치 2
    - equip_spec (스펙)
    - kpi_nm_list (KPI 목록)
    - org_nm (기관명)

    Args:
        keywords: 검색 키워드 목록
        region: 지역 필터 (예: "경기도")
        limit: 최대 결과 수

    Returns:
        [{"conts_id": str, "name": str, "score": float, "source": "es"}, ...]
    """
    try:
        from search.es_client import ESSearchClient
        es_client = ESSearchClient()
        if not es_client.is_available():
            logger.warning("Phase 99: ES 클라이언트 연결 불가")
            return []
    except Exception as e:
        logger.warning(f"Phase 99: ES 클라이언트 초기화 실패 - {e}")
        return []

    query_text = " ".join(keywords)

    # 다중 필드 검색 쿼리 구성
    should_clauses = [
        {"match": {"conts_klang_nm": {"query": query_text, "boost": 3}}},
        {"match": {"equip_desc": {"query": query_text, "boost": 2}}},
        {"match": {"equip_spec": {"query": query_text}}},
        {"match": {"kpi_nm_list": {"query": query_text, "boost": 2}}},
        {"match": {"org_nm": {"query": query_text}}},
    ]

    # 지역 필터
    filter_clauses = []
    if region:
        filter_clauses.append({"match": {"address_dosi": region}})

    body = {
        "query": {
            "bool": {
                "should": should_clauses,
                "filter": filter_clauses,
                "minimum_should_match": 1
            }
        },
        "size": limit
    }

    try:
        response = es_client.client.search(index="ax_equipments", body=body)
        results = []
        for hit in response["hits"]["hits"]:
            results.append({
                "conts_id": hit["_source"].get("conts_id"),
                "name": hit["_source"].get("conts_klang_nm"),
                "score": hit["_score"],
                "source": "es"
            })
        logger.info(f"Phase 99: ES 장비 검색 - {len(results)}건 (query={query_text[:30]})")
        return results
    except Exception as e:
        logger.warning(f"Phase 99: ES 장비 검색 실패 - {e}")
        return []


def _search_equipment_qdrant(keywords: List[str], limit: int = 30) -> List[Dict[str, Any]]:
    """Phase 99: 장비 Qdrant 벡터 검색

    equipments_v3_collection에서 벡터 유사도 검색

    Args:
        keywords: 검색 키워드 목록
        limit: 최대 결과 수

    Returns:
        [{"conts_id": str, "name": str, "score": float, "source": "qdrant"}, ...]
    """
    try:
        from graph.graph_rag import get_graph_rag
        graph_rag = get_graph_rag()
        if not graph_rag or not graph_rag.qdrant:
            logger.warning("Phase 99: Qdrant 클라이언트 미초기화")
            return []
    except Exception as e:
        logger.warning(f"Phase 99: Qdrant 초기화 실패 - {e}")
        return []

    query_text = " ".join(keywords)

    try:
        # GraphRAG의 qdrant.search() 사용
        search_results = graph_rag.qdrant.search(
            query=query_text,
            collection="equipments_v3_collection",
            limit=limit
        )

        results = []
        for hit in search_results:
            # SearchResult 또는 dict 형태 처리
            if hasattr(hit, 'metadata'):
                conts_id = hit.metadata.get("conts_id") if hit.metadata else None
                name = hit.name
                score = hit.score
            else:
                conts_id = hit.get("conts_id")
                name = hit.get("name") or hit.get("conts_klang_nm")
                score = hit.get("score", 0.0)

            results.append({
                "conts_id": conts_id,
                "name": name,
                "score": score,
                "source": "qdrant"
            })
        logger.info(f"Phase 99: Qdrant 장비 검색 - {len(results)}건")
        return results
    except Exception as e:
        logger.warning(f"Phase 99: Qdrant 장비 검색 실패 - {e}")
        return []


# Phase 99.2: PNU 지역 코드 매핑 (앞 2자리)
PNU_REGION_MAP = {
    '11': '서울', '26': '부산', '27': '대구', '28': '인천',
    '29': '광주', '30': '대전', '31': '울산', '36': '세종',
    '41': '경기', '42': '강원', '43': '충북', '44': '충남',
    '45': '전북', '46': '전남', '47': '경북', '48': '경남',
    '49': '제주', '50': '강원', '51': '충북', '52': '전북',
}

# 역방향 매핑 (지역명 → PNU 코드)
REGION_TO_PNU = {}
for code, name in PNU_REGION_MAP.items():
    if name not in REGION_TO_PNU:
        REGION_TO_PNU[name] = []
    REGION_TO_PNU[name].append(code)

# 지역명 alias (사용자 입력 → 정규화)
REGION_ALIAS = {
    "서울특별시": "서울", "서울시": "서울",
    "부산광역시": "부산", "부산시": "부산",
    "대구광역시": "대구", "대구시": "대구",
    "인천광역시": "인천", "인천시": "인천",
    "광주광역시": "광주", "광주시": "광주",
    "대전광역시": "대전", "대전시": "대전",
    "울산광역시": "울산", "울산시": "울산",
    "세종특별자치시": "세종", "세종시": "세종",
    "경기도": "경기", "강원도": "강원", "강원특별자치도": "강원",
    "충청북도": "충북", "충청남도": "충남",
    "전라북도": "전북", "전북특별자치도": "전북",
    "전라남도": "전남", "경상북도": "경북", "경상남도": "경남",
    "제주특별자치도": "제주", "제주도": "제주",
}


def _get_pnu_codes_for_region(region: str) -> List[str]:
    """Phase 99.2: 지역명에 해당하는 PNU 코드 목록 반환

    Args:
        region: 지역명 (예: "경기", "경기도", "서울")

    Returns:
        PNU 코드 목록 (예: ["41"])
    """
    if not region:
        return []

    # 정규화
    normalized = REGION_ALIAS.get(region, region)

    # 직접 매핑 확인
    if normalized in REGION_TO_PNU:
        return REGION_TO_PNU[normalized]

    # 부분 매칭 시도
    for key, codes in REGION_TO_PNU.items():
        if key in normalized or normalized in key:
            return codes

    return []


def _build_equipment_sql_by_ids(conts_ids: List[str], region: str = None) -> str:
    """Phase 99/99.2: 후보 ID 기반 장비 SQL 빌드

    ES/Qdrant에서 찾은 conts_id 목록으로 상세 정보 조회
    Phase 99.2: PNU 기반 지역 필터 추가

    Args:
        conts_ids: 장비 ID 목록
        region: 지역 필터 (선택)

    Returns:
        SQL 쿼리 문자열
    """
    # ID 목록을 SQL IN 절로
    id_list = ", ".join(f"'{cid}'" for cid in conts_ids if cid)

    # Phase 99.2: PNU 기반 지역 필터
    region_condition = ""
    if region:
        pnu_codes = _get_pnu_codes_for_region(region)
        if pnu_codes:
            # f_gis JOIN으로 PNU 기반 필터
            pnu_like_conditions = " OR ".join(f"g.pnu LIKE '{code}%'" for code in pnu_codes)
            region_condition = f"AND EXISTS (SELECT 1 FROM f_gis g WHERE g.conts_id = e.conts_id AND ({pnu_like_conditions}))"
            logger.info(f"Phase 99.2: PNU 기반 지역 필터 - {region} → codes={pnu_codes}")
        else:
            # 폴백: address_dosi 기반
            region_condition = f"AND e.address_dosi ILIKE '%{region}%'"

    sql = f"""
    SELECT DISTINCT
        e.conts_id as 장비ID,
        e.conts_klang_nm as 장비명,
        e.org_nm as 보유기관,
        COALESCE(e.address_dosi, '') as 지역,
        e.equip_grp_lv1_nm as 대분류,
        e.kpi_nm_list as 측정항목
    FROM f_equipments e
    WHERE e.conts_id IN ({id_list})
    {region_condition}
    ORDER BY e.org_nm, e.conts_klang_nm
    LIMIT 20
    """
    return sql


def _build_equipment_sql_direct(keywords: List[str], region: str = None) -> str:
    """Phase 99/99.2: 키워드 기반 장비 SQL 직접 검색 (폴백)

    ES/Qdrant 결과 없을 때 기존 SQL 방식 사용
    Phase 99.2: PNU 기반 지역 필터 추가

    Args:
        keywords: 검색 키워드 목록
        region: 지역 필터 (선택)

    Returns:
        SQL 쿼리 문자열
    """
    keyword_conditions = " OR ".join(
        f"(e.conts_klang_nm ILIKE '%{kw}%' OR e.kpi_nm_list ILIKE '%{kw}%' OR e.equip_spec ILIKE '%{kw}%')"
        for kw in keywords[:3]
    )

    # Phase 99.2: PNU 기반 지역 필터
    region_condition = ""
    if region:
        pnu_codes = _get_pnu_codes_for_region(region)
        if pnu_codes:
            pnu_like_conditions = " OR ".join(f"g.pnu LIKE '{code}%'" for code in pnu_codes)
            region_condition = f"AND EXISTS (SELECT 1 FROM f_gis g WHERE g.conts_id = e.conts_id AND ({pnu_like_conditions}))"
            logger.info(f"Phase 99.2: PNU 기반 지역 필터 - {region} → codes={pnu_codes}")
        else:
            region_condition = f"AND e.address_dosi ILIKE '%{region}%'"

    sql = f"""
    SELECT DISTINCT
        e.conts_id as 장비ID,
        e.conts_klang_nm as 장비명,
        e.org_nm as 보유기관,
        COALESCE(e.address_dosi, '') as 지역,
        e.equip_grp_lv1_nm as 대분류,
        e.kpi_nm_list as 측정항목
    FROM f_equipments e
    WHERE ({keyword_conditions})
    {region_condition}
    ORDER BY e.org_nm, e.conts_klang_nm
    LIMIT 20
    """
    return sql


def _execute_equipment_recommendation(
    keywords: List[str],
    query: str,
    region: str = None
) -> Dict[str, Any]:
    """Phase 85/86/99: 장비 추천

    Phase 99: ES/Qdrant → SQL 확장 패턴 적용
    1. ES에서 다중 필드 키워드 검색 (장비명, 설명, 스펙, KPI, 기관명)
    2. Qdrant에서 벡터 유사도 검색
    3. ES/Qdrant 결과에서 conts_id 추출
    4. SQL로 상세 정보 조회 (후보 ID 기반)
    5. 폴백: ES/Qdrant 결과 없으면 기존 SQL 직접 검색

    Args:
        keywords: 검색 키워드 목록 (예: ["마찰견뢰도", "측정"])
        query: 원본 쿼리 (키워드 폴백용)
        region: 지역 필터 (예: "전남", "경기")

    Returns:
        {"sql_result": SQLQueryResult, "generated_sql": str}
    """
    import re

    # Phase 86: 장비 추천에서 제외할 일반 키워드
    EXCLUDE_EQUIPMENT_KEYWORDS = {
        "장비", "추천", "측정", "분석", "시험", "검사", "기기", "기자재",
        "관련", "알려줘", "해줘", "위한", "지역", "위해", "가능한", "목록",
        "equipment", "recommend"
    }

    # Phase 86.2: 복합 키워드 분리 및 일반 단어 제외
    if keywords:
        expanded_keywords = []
        for kw in keywords:
            parts = kw.split()
            for part in parts:
                part = part.strip()
                if part and len(part) >= 2 and part not in EXCLUDE_EQUIPMENT_KEYWORDS:
                    expanded_keywords.append(part)
        filtered_keywords = list(dict.fromkeys(expanded_keywords))
        if filtered_keywords:
            keywords = filtered_keywords
            logger.info(f"Phase 86.2: 장비 검색 키워드 분리/필터링 - {keywords}")

    # 키워드 폴백
    if not keywords:
        words = re.findall(r'[가-힣]+|[a-zA-Z0-9]+', query)
        keywords = [w for w in words if len(w) >= 2 and w not in EXCLUDE_EQUIPMENT_KEYWORDS][:3]
        logger.info(f"Phase 86: 장비 추천 키워드 폴백 - {keywords}")

    if not keywords:
        return {
            "sql_result": SQLQueryResult(
                success=False,
                error="검색 키워드가 없습니다."
            ),
            "generated_sql": None
        }

    logger.info(f"Phase 99: 장비 추천 ES→SQL 확장 패턴 시작 - keywords={keywords}")

    # 지역 alias 설정
    REGION_ALIAS = {
        "광주": "광주광역시", "부산": "부산광역시", "대구": "대구광역시",
        "인천": "인천광역시", "대전": "대전광역시", "울산": "울산광역시",
        "세종": "세종특별자치시"
    }
    region_search = REGION_ALIAS.get(region, region) if region else None

    # Phase 99: 1단계 - ES에서 다중 필드 검색
    candidate_ids = set()
    es_results = _search_equipment_es(keywords, region_search, limit=50)
    for r in es_results:
        if r.get("conts_id"):
            candidate_ids.add(r["conts_id"])
    logger.info(f"Phase 99: ES 검색 완료 - {len(es_results)}건, 후보 ID {len(candidate_ids)}개")

    # Phase 99: 2단계 - Qdrant 벡터 검색
    qdrant_results = _search_equipment_qdrant(keywords, limit=30)
    for r in qdrant_results:
        if r.get("conts_id"):
            candidate_ids.add(r["conts_id"])
    logger.info(f"Phase 99: Qdrant 검색 완료 - {len(qdrant_results)}건, 총 후보 ID {len(candidate_ids)}개")

    # Phase 99: 3단계 - SQL로 상세 정보 조회
    if candidate_ids:
        # 후보 ID 기반 SQL 조회
        sql = _build_equipment_sql_by_ids(list(candidate_ids)[:30], region_search)
        search_method = "ES+Qdrant→SQL"
    else:
        # 폴백: 기존 SQL 직접 검색
        logger.info("Phase 99: ES/Qdrant 결과 없음 - SQL 직접 검색 폴백")
        sql = _build_equipment_sql_direct(keywords, region_search)
        search_method = "SQL직접"

    try:
        from sql.db_connector import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        columns = ["장비ID", "장비명", "보유기관", "지역", "대분류", "측정항목"]
        cur.close()
        conn.close()

        logger.info(f"Phase 99: 장비 추천 완료 - {len(rows)}건 ({search_method}, region={region})")

        return {
            "sql_result": SQLQueryResult(
                success=True,
                columns=columns,
                rows=[list(row) for row in rows],
                row_count=len(rows)
            ),
            "generated_sql": sql
        }

    except Exception as e:
        logger.error(f"Phase 99: 장비 추천 쿼리 실패 - {e}")
        return {
            "sql_result": SQLQueryResult(
                success=False,
                error=str(e)
            ),
            "generated_sql": sql
        }


def _execute_collaboration_recommendation(
    keywords: List[str],
    query: str
) -> Dict[str, Any]:
    """Phase 70: 다중 도메인 협업 기관 추천

    제안서 + 특허 도메인에서 협업 기관 검색 후 통합 결과 반환

    Phase 75.2: cuGraph 커뮤니티 정보 추가

    Args:
        keywords: 검색 키워드 목록 (예: ["인공지능"])
        query: 원본 쿼리 (키워드 폴백용)

    Returns:
        {"sql_result": SQLQueryResult, "domain_results": Dict, "generated_sql": str, "community_info": Dict}
    """
    # 키워드 폴백: keywords가 비어있으면 query에서 추출
    if not keywords:
        import re
        exclude_patterns = ["협업", "협력", "기관", "추천", "파트너", "공동연구", "관련", "알려줘", "해줘"]
        words = re.findall(r'[가-힣]+|[a-zA-Z0-9]+', query)
        keywords = [w for w in words if len(w) >= 2 and w not in exclude_patterns][:3]
        logger.info(f"Phase 70: 협업 기관 키워드 폴백 - {keywords}")

    if not keywords:
        return {
            "sql_result": SQLQueryResult(
                success=False,
                error="검색 키워드가 없습니다."
            ),
            "domain_results": {},
            "generated_sql": None
        }

    # Phase 71: 다중 도메인 병렬 조회 (과제 수행기관 + 특허 보유기관)
    logger.info(f"Phase 71: 다중 도메인 협업 기관 조회 시작 - keywords={keywords}")

    # 1. 과제 수행기관 조회 (역할별 집계 + 최근 과제명)
    proposal_result = _query_proposal_orgs(keywords)
    logger.info(f"Phase 71: 과제 수행기관 - {len(proposal_result.get('rows', []))}건")

    # 2. 특허 보유기관 조회 (대표 특허 포함)
    patent_result = _query_patent_orgs(keywords)
    logger.info(f"Phase 71: 특허 보유기관 - {len(patent_result.get('rows', []))}건")

    # 3. 통합 결과 구성 (도메인별 결과 유지)
    domain_results = {
        "proposal": proposal_result,
        "patent": patent_result
    }

    # 4. Phase 92: 분리된 SQL 결과 (과제 테이블 + 특허 테이블)
    # 과제 수행기관 SQLQueryResult
    proposal_columns = ["기관명", "수행횟수", "주관", "참여", "협력", "최근 수행과제"]
    proposal_rows = []
    for row in proposal_result.get("rows", [])[:10]:
        proposal_rows.append([
            row[0],  # 기관명
            row[1],  # 수행횟수
            row[2],  # 주관
            row[3] if len(row) > 3 else 0,  # 참여
            row[4] if len(row) > 4 else 0,  # 협력
            row[5] if len(row) > 5 else ""  # 최근과제명
        ])

    proposal_sql_result = SQLQueryResult(
        success=True,
        columns=proposal_columns,
        rows=proposal_rows,
        row_count=len(proposal_rows)
    )

    # 특허 보유기관 SQLQueryResult
    patent_columns = ["기관명", "국가", "특허수", "대표 특허"]
    patent_rows = []
    for row in patent_result.get("rows", [])[:10]:
        patent_rows.append([
            row[0],  # 기관명
            row[1] if len(row) > 1 else "",  # 국가
            row[2] if len(row) > 2 else 0,  # 특허수
            row[3] if len(row) > 3 else ""  # 대표특허명
        ])

    patent_sql_result = SQLQueryResult(
        success=True,
        columns=patent_columns,
        rows=patent_rows,
        row_count=len(patent_rows)
    )

    # Phase 92: multi_sql_results 형태로 분리 전달
    multi_sql_results = {
        "proposal": proposal_sql_result,
        "patent": patent_sql_result
    }

    # 기존 combined 형식도 유지 (호환성)
    combined_rows = proposal_rows + patent_rows
    sql_result = SQLQueryResult(
        success=True,
        columns=["기관명", "수행/특허수", "주관/국가", "참여", "협력", "최근과제/대표특허"],
        rows=combined_rows,
        row_count=len(combined_rows)
    )

    combined_sql = f"""
-- Phase 71: 다중 도메인 협업 기관 조회
-- 1. 과제 수행기관 (역할별 집계 + 최근 과제명)
{proposal_result.get('sql', '')}

-- 2. 특허 보유기관 (대표 특허 포함)
{patent_result.get('sql', '')}
"""

    logger.info(f"Phase 71: 협업 기관 추천 완료 - 총 {len(combined_rows)}건 (과제: {len(proposal_result.get('rows', []))}건, 특허: {len(patent_result.get('rows', []))}건)")

    # Phase 75.2: 커뮤니티 정보 조회 (선택적)
    community_info = {}
    try:
        # 모든 기관명 수집
        all_org_names = []
        for row in proposal_result.get("rows", []):
            if row and len(row) > 0:
                all_org_names.append(row[0])  # 기관명
        for row in patent_result.get("rows", []):
            if row and len(row) > 0:
                all_org_names.append(row[0])  # 기관명

        # 커뮤니티 정보 조회
        org_community_map = _get_org_community_info(all_org_names)

        # 커뮤니티별 기관 그룹핑
        community_groups = {}
        for org_name in all_org_names:
            # org_ 해시 ID를 찾기 어려우므로 일단 스킵
            # 향후 개선: PostgreSQL에서 org_nm → org_hash 매핑 테이블 사용
            pass

        community_info = {
            "total_orgs": len(all_org_names),
            "community_available": len(org_community_map) > 0,
            "note": "Phase 75.2: 커뮤니티 기반 협업 시너지 분석 지원"
        }
        logger.info(f"Phase 75.2: 커뮤니티 정보 수집 완료 - {len(all_org_names)}개 기관")

    except Exception as e:
        logger.warning(f"Phase 75.2: 커뮤니티 정보 수집 실패 - {e}")
        community_info = {"error": str(e)}

    return {
        "sql_result": sql_result,
        "multi_sql_results": multi_sql_results,  # Phase 92: 분리된 과제/특허 결과
        "domain_results": domain_results,
        "generated_sql": combined_sql,
        "community_info": community_info  # Phase 75.2 추가
    }


def execute_sql(state: AgentState) -> AgentState:
    """SQL 실행 노드

    자연어 질문을 SQL로 변환하고 실행.
    벡터 검색 결과가 있으면 SQL 생성에 힌트로 활용.

    Phase 19: 다중 엔티티 타입 (특허+과제 등)일 경우 각각 별도 쿼리 실행

    Args:
        state: 현재 에이전트 상태

    Returns:
        업데이트된 상태 (sql_result 또는 multi_sql_results, generated_sql, sources)
    """
    query = state.get("query", "")
    related_tables = state.get("related_tables", [])

    # 벡터 강화 정보 가져오기
    vector_doc_ids = state.get("vector_doc_ids", [])
    expanded_keywords = state.get("expanded_keywords", [])  # Phase 36: 통합 키워드 필드
    entity_types = state.get("entity_types", [])
    keywords = state.get("keywords", [])
    structured_keywords = state.get("structured_keywords")  # Phase 34.5
    is_aggregation = state.get("is_aggregation", False)  # Phase 27: 통계/집계 쿼리 플래그
    query_subtype = state.get("query_subtype", "list")  # Phase 28: 쿼리 서브타입

    # Phase 99.10: es_doc_ids 디버깅 로그
    es_doc_ids_early = state.get("es_doc_ids", {})
    es_counts = {k: len(v) for k, v in es_doc_ids_early.items()} if es_doc_ids_early else {}
    print(f"[SQL_EXECUTOR] Phase 99.10: es_doc_ids 확인 - keys={list(es_doc_ids_early.keys()) if es_doc_ids_early else []}, counts={es_counts}")

    # Phase 100.2: es_doc_ids와 entity_types 교차 검증
    # entity_types가 명시된 경우, 해당 도메인의 es_doc_ids만 사용
    if es_doc_ids_early and entity_types:
        DOMAIN_TO_ENTITY_MAP = {
            "patent": "patent",
            "project": "project",
            "equipment": "equip",
            "proposal": "proposal",
        }
        filtered_es_doc_ids = {
            domain: doc_ids
            for domain, doc_ids in es_doc_ids_early.items()
            if DOMAIN_TO_ENTITY_MAP.get(domain, domain) in entity_types
        }
        if filtered_es_doc_ids != es_doc_ids_early:
            print(f"[SQL_EXECUTOR] Phase 100.2: entity_types 필터링 - before={list(es_doc_ids_early.keys())}, after={list(filtered_es_doc_ids.keys())}")
            # state의 es_doc_ids를 필터링된 버전으로 업데이트하지 않음 (원본 유지)
            # 대신 이후 로직에서 entity_types를 기준으로 사용

    # Phase 99.6: crosstab_analysis는 ES nested aggregations로 처리
    # 출원기관별 연도별 크로스탭 통계
    print(f"[SQL_EXECUTOR] Phase 99.6 조건 확인: query_subtype={query_subtype}, keywords={keywords}")
    if query_subtype == "crosstab_analysis" and keywords:
        print(f"[SQL_EXECUTOR] Phase 99.6: crosstab_analysis 조건 진입!")
        try:
            import requests
            import os
            import re
            from datetime import datetime

            print(f"[SQL_EXECUTOR] Phase 99.6: imports 완료, ES nested aggregations 시작")

            # 국가 필터 추출
            countries = None
            if structured_keywords and structured_keywords.get("country"):
                countries = structured_keywords.get("country")
            elif any(kw in query.upper() for kw in ["KR", "한국", "국내"]):
                countries = ["KR"]

            # TOP N 추출 (기본값 10)
            top_n = 10
            top_match = re.search(r'top\s*(\d+)', query.lower())
            if top_match:
                top_n = int(top_match.group(1))

            # 기간 설정 (최근 6년)
            current_year = datetime.now().year
            start_year = current_year - 6
            end_year = current_year

            ES_HOST = os.getenv("ES_HOST", "localhost")
            ES_PORT = int(os.getenv("ES_PORT", "9200"))
            es_url = f"http://{ES_HOST}:{ES_PORT}"

            keyword_str = " ".join(keywords) if keywords else None
            print(f"[SQL_EXECUTOR] Phase 99.6: keyword_str={keyword_str}, countries={countries}, top_n={top_n}")

            # 필터 조건
            filter_clauses = [{
                "range": {
                    "ptnaplc_ymd": {
                        "gte": f"{start_year}0101",
                        "lte": f"{end_year}1231",
                        "format": "yyyyMMdd"
                    }
                }
            }]

            if countries:
                filter_clauses.append({"terms": {"ntcd": countries}})

            # 키워드 검색
            if keyword_str:
                must_clause = {
                    "multi_match": {
                        "query": keyword_str,
                        "fields": ["conts_klang_nm", "keyvalue", "objectko", "tmsc_nm"],
                        "type": "best_fields",
                        "operator": "or"
                    }
                }
            else:
                must_clause = {"match_all": {}}

            # ES nested aggregation 쿼리
            body = {
                "query": {
                    "bool": {
                        "must": [must_clause],
                        "filter": filter_clauses
                    }
                },
                "size": 0,
                "aggs": {
                    "top_applicants": {
                        "terms": {
                            "field": "patent_frst_appn.keyword",
                            "size": top_n,
                            "min_doc_count": 3  # 최소 3건 이상
                        },
                        "aggs": {
                            "by_year": {
                                "date_histogram": {
                                    "field": "ptnaplc_ymd",
                                    "calendar_interval": "year",
                                    "format": "yyyy",
                                    "min_doc_count": 0  # 0건도 표시
                                }
                            },
                            "nationality": {
                                "terms": {
                                    "field": "patent_frst_appn_ntnlty",
                                    "size": 1
                                }
                            }
                        }
                    }
                }
            }

            response = requests.post(
                f"{es_url}/ax_patents/_search",
                json=body,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            total = data["hits"]["total"]["value"]
            applicant_buckets = data.get("aggregations", {}).get("top_applicants", {}).get("buckets", [])

            # 연도 목록 생성
            years = list(range(start_year, end_year + 1))

            # 크로스탭 데이터 구성
            rows = []
            for rank, bucket in enumerate(applicant_buckets, 1):
                applicant_name = bucket.get("key", "")
                total_count = bucket.get("doc_count", 0)

                # 국적 추출
                nationality_buckets = bucket.get("nationality", {}).get("buckets", [])
                nationality = nationality_buckets[0].get("key", "-") if nationality_buckets else "-"

                # 연도별 건수
                year_buckets = bucket.get("by_year", {}).get("buckets", [])
                by_year = {}
                for yb in year_buckets:
                    year_str = yb.get("key_as_string", "")
                    if year_str:
                        by_year[year_str] = yb.get("doc_count", 0)

                rows.append({
                    "rank": rank,
                    "name": applicant_name,
                    "nationality": nationality,
                    "by_year": by_year,
                    "total": total_count
                })

            stats_results = {
                "patent": {
                    "crosstab_type": "applicant_year",
                    "keywords": keyword_str,
                    "countries": countries,
                    "period": f"{start_year}-{end_year}",
                    "total": total,
                    "years": years,
                    "rows": rows
                }
            }

            print(f"[SQL_EXECUTOR] Phase 99.6: crosstab 완료 - total={total}, applicants={len(rows)}")
            logger.info(f"[SQL_EXECUTOR] Phase 99.6: crosstab 완료 - total={total}, applicants={len(rows)}")

            # 소스 정보
            sources = [{
                "type": "es_crosstab",
                "entity_type": "patent",
                "total": total,
                "period": f"{start_year}-{end_year}",
                "applicant_count": len(rows)
            }]

            result_state = {
                **state,
                "es_statistics": stats_results,
                "statistics_type": "crosstab_analysis",
                "sources": sources,
            }
            print(f"[SQL_EXECUTOR] Phase 99.6: 반환 state keys: {list(result_state.keys())}")
            return result_state

        except Exception as e:
            import traceback
            logger.warning(f"[SQL_EXECUTOR] Phase 99.6: ES nested aggregations 실패 - {e}")
            logger.warning(f"[SQL_EXECUTOR] Phase 99.6: traceback: {traceback.format_exc()}")
            # 실패 시 기존 SQL 로직으로 fallback

    # Phase 99.5: trend_analysis는 ES aggregations로 처리 (빠르고 정확)
    print(f"[SQL_EXECUTOR] Phase 99.5 조건 확인: query_subtype={query_subtype}, keywords={keywords}")
    if query_subtype == "trend_analysis" and keywords:
        print(f"[SQL_EXECUTOR] Phase 99.5: trend_analysis 조건 진입!")
        try:
            import requests
            import os
            from datetime import datetime

            print(f"[SQL_EXECUTOR] Phase 99.5: imports 완료, ES aggregations 시작 - keywords={keywords}")

            # 국가 필터 추출
            countries = None
            if structured_keywords and structured_keywords.get("country"):
                countries = structured_keywords.get("country")
            elif any(kw in query.upper() for kw in ["KR", "한국", "국내"]):
                countries = ["KR"]

            # 엔티티 타입 결정 (특허 또는 과제)
            target_entities = []
            if any(e in entity_types for e in ["patent", "특허"]) or "특허" in query:
                target_entities.append("patent")
            if any(e in entity_types for e in ["project", "과제"]) or "과제" in query or "연구" in query:
                target_entities.append("project")
            if not target_entities:
                target_entities = ["patent"]

            # Phase 99.5 fix: requests로 직접 ES 호출 (이벤트 루프 문제 완전 회피)
            ES_HOST = os.getenv("ES_HOST", "localhost")
            ES_PORT = int(os.getenv("ES_PORT", "9200"))
            es_url = f"http://{ES_HOST}:{ES_PORT}"

            INDEX_MAP = {"patent": "ax_patents", "project": "ax_projects"}
            DATE_FIELDS = {"patent": "ptnaplc_ymd", "project": "rsrh_bgnv_ymd"}
            SEARCH_FIELDS = {
                "patent": ["conts_klang_nm", "tmsc_nm", "fst_aplc_nm", "ipc_cd"],
                "project": ["prj_nm", "kwd_nm_lst", "rsch_org_nm"]
            }

            current_year = datetime.now().year
            start_year = current_year - 10
            end_year = current_year

            stats_results = {}
            keyword_str = " ".join(keywords) if keywords else None

            print(f"[SQL_EXECUTOR] Phase 99.5: target_entities={target_entities}, keyword_str={keyword_str}")

            for entity_type in target_entities:
                try:
                    index = INDEX_MAP.get(entity_type, "ax_patents")
                    date_field = DATE_FIELDS.get(entity_type, "ptnaplc_ymd")
                    search_fields = SEARCH_FIELDS.get(entity_type, ["*"])

                    # 필터 조건
                    filter_clauses = [{
                        "range": {
                            date_field: {
                                "gte": f"{start_year}0101",
                                "lte": f"{end_year}1231",
                                "format": "yyyyMMdd"
                            }
                        }
                    }]

                    if countries and entity_type == "patent":
                        filter_clauses.append({"terms": {"ntcd": countries}})

                    # 키워드 검색
                    if keyword_str:
                        must_clause = {
                            "multi_match": {
                                "query": keyword_str,
                                "fields": search_fields,
                                "type": "best_fields",
                                "operator": "or"
                            }
                        }
                    else:
                        must_clause = {"match_all": {}}

                    body = {
                        "query": {
                            "bool": {
                                "must": [must_clause],
                                "filter": filter_clauses
                            }
                        },
                        "size": 0,
                        "aggs": {
                            "by_group": {
                                "date_histogram": {
                                    "field": date_field,
                                    "calendar_interval": "year",
                                    "format": "yyyy",
                                    "min_doc_count": 1
                                }
                            }
                        }
                    }

                    response = requests.post(
                        f"{es_url}/{index}/_search",
                        json=body,
                        headers={"Content-Type": "application/json"},
                        timeout=30
                    )
                    response.raise_for_status()
                    data = response.json()

                    total = data["hits"]["total"]["value"]
                    buckets = []
                    for bucket in data.get("aggregations", {}).get("by_group", {}).get("buckets", []):
                        buckets.append({
                            "key": bucket.get("key_as_string") or str(bucket.get("key")),
                            "count": bucket["doc_count"]
                        })

                    stats_results[entity_type] = {
                        "entity_type": entity_type,
                        "keywords": keyword_str,
                        "period": f"{start_year}-{end_year}",
                        "total": total,
                        "buckets": buckets
                    }
                    print(f"[SQL_EXECUTOR] Phase 99.5: {entity_type} 통계 완료 - total={total}, buckets={len(buckets)}")
                    logger.info(f"[SQL_EXECUTOR] Phase 99.5: {entity_type} 통계 완료 - total={total}, buckets={len(buckets)}")

                except Exception as e:
                    logger.warning(f"[SQL_EXECUTOR] Phase 99.5: {entity_type} 통계 실패 - {e}")
                    stats_results[entity_type] = {"total": 0, "buckets": []}

            # 결과를 state에 저장
            state["es_statistics"] = stats_results
            state["statistics_type"] = "trend_analysis"

            # 소스 정보 생성
            sources = []
            for entity_type, result in stats_results.items():
                if result.get("buckets"):
                    sources.append({
                        "type": "es_statistics",
                        "entity_type": entity_type,
                        "total": result.get("total", 0),
                        "period": result.get("period", ""),
                    })

            print(f"[SQL_EXECUTOR] Phase 99.5: trend_analysis 완료 - {len(stats_results)}개 엔티티, sources={sources}")
            logger.info(f"[SQL_EXECUTOR] Phase 99.5: trend_analysis 완료 - {len(stats_results)}개 엔티티, sources={sources}")

            result_state = {
                **state,
                "es_statistics": stats_results,
                "statistics_type": "trend_analysis",
                "sources": sources,
            }
            print(f"[SQL_EXECUTOR] Phase 99.5: 반환 state keys: {list(result_state.keys())}")
            print(f"[SQL_EXECUTOR] Phase 99.5: es_statistics in result_state: {bool(result_state.get('es_statistics'))}")
            logger.info(f"[SQL_EXECUTOR] Phase 99.5: 반환 state keys: {list(result_state.keys())}")
            return result_state

        except Exception as e:
            import traceback
            logger.warning(f"[SQL_EXECUTOR] Phase 99.5: ES aggregations 실패 - {e}, SQL fallback")
            logger.warning(f"[SQL_EXECUTOR] Phase 99.5: traceback: {traceback.format_exc()}")
            # 실패 시 기존 SQL 로직으로 fallback

    # Phase 94.1: ES Scout doc_ids 디버깅
    es_doc_ids = state.get("es_doc_ids", {})
    domain_hits = state.get("domain_hits", {})
    logger.info(f"[SQL_EXECUTOR] Phase 94.1 상태 확인: entity_types={entity_types}, es_doc_ids keys={list(es_doc_ids.keys()) if es_doc_ids else []}, domain_hits={domain_hits}")

    # Phase 94.2: es_doc_ids가 없고 list 쿼리일 때 직접 ES Scout 수행
    # (vector_enhancer를 거치지 않은 경우)
    # Phase 104.7: entity_types가 단일 엔티티면 ES Scout 스킵 → 개별 엔티티 처리로 진행
    if not es_doc_ids and query_subtype in ("list", "recommendation") and keywords:
        # Phase 104.7: 단일 엔티티 sub_query에서는 ES Scout 스킵
        # sub_query 실행 시 entity_types=['project'] 처럼 단일 엔티티면
        # ES Scout로 모든 도메인을 검색하지 않고 해당 엔티티 처리로 직행
        if len(entity_types) == 1:
            logger.info(f"[SQL_EXECUTOR] Phase 104.7: 단일 엔티티 sub_query - ES Scout 스킵, 개별 처리로 진행 ({entity_types})")
            print(f"[SQL_EXECUTOR] Phase 104.7: 단일 엔티티 {entity_types} - ES Scout 스킵")
        else:
            try:
                from workflow.nodes.vector_enhancer import _scout_all_domains
                logger.info(f"[SQL_EXECUTOR] Phase 94.2: ES Scout 직접 수행 - keywords={keywords}")
                scout_result = _scout_all_domains(keywords, query)
                es_doc_ids = scout_result.get("doc_ids", {})
                domain_hits = scout_result.get("hits", {})
                logger.info(f"[SQL_EXECUTOR] Phase 94.2: ES Scout 완료 - domain_hits={domain_hits}, es_doc_ids keys={list(es_doc_ids.keys())}")
            except Exception as e:
                logger.warning(f"[SQL_EXECUTOR] Phase 94.2: ES Scout 실패 - {e}")
                es_doc_ids = {}
                domain_hits = {}

    # Phase 94.1: ES Scout doc_ids가 있으면 다중 엔티티 처리로 직행
    # (Loader, 개별 처리 로직 건너뛰기)
    if es_doc_ids and len(es_doc_ids) > 0:
        # ES 도메인 → entity_type 매핑
        domain_to_entity = {
            "patent": "patent",
            "project": "project",
            "equipment": "equip",
            "proposal": "proposal",
        }

        # ES Scout에서 결과가 있는 도메인만 처리
        active_domains = [d for d, count in domain_hits.items() if count > 0] if domain_hits else list(es_doc_ids.keys())

        # Phase 100.2: entity_types가 명시된 경우, 해당 도메인만 사용
        if entity_types:
            filtered_domains = [
                d for d in active_domains
                if domain_to_entity.get(d, d) in entity_types
            ]
            if filtered_domains:
                logger.info(f"[SQL_EXECUTOR] Phase 100.2: entity_types 필터링 적용 - before={active_domains}, after={filtered_domains}")
                print(f"[SQL_EXECUTOR] Phase 100.2: entity_types 필터링 - {active_domains} → {filtered_domains}")
                active_domains = filtered_domains

        if active_domains:
            logger.info(f"[SQL_EXECUTOR] Phase 94.1: ES Scout 결과 기반 직접 처리 시작 - 활성 도메인: {active_domains}")

            es_entity_types = [domain_to_entity.get(d, d) for d in active_domains]

            # 다중 엔티티 SQL 직접 실행
            multi_results = _execute_multi_entity_sql(
                query=query,
                entity_types=es_entity_types,
                keywords=keywords,
                vector_doc_ids=vector_doc_ids,
                expanded_keywords=expanded_keywords,
                is_aggregation=is_aggregation,
                entity_keywords=state.get("entity_keywords"),
                query_subtype=query_subtype,
                es_doc_ids=es_doc_ids
            )

            # 소스 정보 생성
            sources = []
            total_rows = 0
            for entity_type, result in multi_results.items():
                if result.success and result.rows:
                    sources.append({
                        "type": "sql",
                        "entity_type": entity_type,
                        "row_count": result.row_count,
                        "source": "es_scout"  # Phase 94.1: ES Scout 기반임을 표시
                    })
                    total_rows += result.row_count

            logger.info(f"[SQL_EXECUTOR] Phase 94.1 완료: {len(multi_results)}개 도메인, 총 {total_rows}행")

            return {
                **state,
                "multi_sql_results": multi_results,
                "sql_result": None,
                "generated_sql": f"-- Phase 94.1 ES Scout 기반: {', '.join(es_entity_types)}",
                "domain_hits": domain_hits,
                "sources": state.get("sources", []) + sources
            }

    # Phase 20: 규칙 기반 폴백 제거 - LLM 키워드가 없으면 경고만 출력
    if not keywords:
        logger.warning(f"LLM analyzer가 키워드를 추출하지 못함: {query[:50]}...")

    if not query.strip():
        return {
            **state,
            "sql_result": SQLQueryResult(success=False, error="질문이 비어있습니다."),
            "generated_sql": None
        }

    # === Phase 88/89: Loader 기반 라우팅 (SearchConfig 또는 subtype 기반) ===
    # SearchConfig.use_loader=True이면 우선 Loader 사용
    from workflow.loaders import get_loader, is_loader_available
    from workflow.search_config import get_search_config

    # Phase 89: SearchConfig 가져오기
    search_config = state.get("search_config")
    if not search_config:
        search_config = get_search_config(state)

    # Phase 89: SearchConfig에서 Loader 사용 여부 확인
    use_loader = search_config.use_loader if search_config else is_loader_available(query_subtype)
    loader_name = search_config.loader_name if search_config else None

    if use_loader:
        loader = get_loader(query_subtype, entity_types, structured_keywords)
        if loader:
            logger.info(f"Phase 89: Loader 사용 - loader={loader.__class__.__name__} (config.loader_name={loader_name})")

            # Loader context 구성
            loader_context = {
                "technology_field": keywords[0] if keywords else None,
                "keywords": keywords,
                "top_n": 10,
            }

            # 배점표 검색용 특별 처리: "배점표" 제외한 키워드를 사업명으로 사용
            # Phase 88.1: 전체 키워드를 연결하여 정확한 사업명 매칭 (예: "중소기업기술혁신개발사업" + "소부장일반")
            # Phase 86: 일반 키워드 더 많이 제외 (상세, 평가항목, 과제 등)
            if query_subtype in ("evalp_score", "evalp_pref", "pref_task_search"):
                EXCLUDE_EVALP_KEYWORDS = {"배점표", "배점", "평가표", "우대", "가점", "관련", "알려줘", "상세", "평가항목", "목록", "과제", "사업", "정보", "내용"}
                non_evalp_keywords = []
                for kw in keywords:
                    # "TIPS과제" → "TIPS" 로 변환, 공백 포함 키워드도 분리
                    for part in kw.replace("과제", "").replace("사업", "").split():
                        cleaned_part = part.strip()
                        if cleaned_part and cleaned_part not in EXCLUDE_EVALP_KEYWORDS:
                            non_evalp_keywords.append(cleaned_part)
                # 중복 제거 후 첫 번째 유효 키워드 사용 (사업명은 보통 하나)
                unique_keywords = list(dict.fromkeys(non_evalp_keywords))
                combined_business_name = unique_keywords[0] if unique_keywords else (keywords[0] if keywords else None)
                loader_context["business_name"] = combined_business_name
                loader_context["technology_field"] = combined_business_name
                logger.info(f"Phase 86: 배점표 검색 - business_name={loader_context['business_name']} (keywords={unique_keywords})")

            # structured_keywords에서 추가 정보 추출
            if structured_keywords:
                if structured_keywords.get("country"):
                    # Phase 85: list인 경우 첫 번째 값을 string으로 변환
                    country_val = structured_keywords["country"]
                    if isinstance(country_val, list):
                        country_val = country_val[0] if country_val else None
                    loader_context["nationality"] = country_val
                if structured_keywords.get("region"):
                    # Phase 85: region도 list인 경우 string으로 변환
                    region_val = structured_keywords["region"]
                    if isinstance(region_val, list):
                        region_val = region_val[0] if region_val else None
                    loader_context["region"] = region_val

            try:
                # Loader는 async 함수이므로 asyncio.run() 사용
                import asyncio
                loader_result = asyncio.run(loader.load(query, keywords, loader_context))

                if loader_result and loader_result.get("data"):
                    # Loader 결과를 SQLQueryResult로 변환
                    data = loader_result["data"]
                    metadata = loader_result.get("metadata", {})

                    # 배점표의 경우 특별 처리: 항목 리스트를 rows로 변환
                    if query_subtype == "evalp_score" and data:
                        first_item = data[0]
                        items = first_item.get("items", [])
                        columns = ["평가항목", "배점"]
                        rows = [[item.get("eval_item", "-"), item.get("score", 0)] for item in items]

                        sql_result = SQLQueryResult(
                            success=True,
                            columns=columns,
                            rows=rows,
                            row_count=len(rows)
                        )

                        # 메타데이터 저장
                        loader_metadata = {
                            "loader_used": loader.__class__.__name__,
                            "announcement_name": first_item.get("announcement_name", ""),
                            "total_score": first_item.get("total_score", 0),
                            **metadata
                        }

                    # Phase 90: 우대/감점 정보 특별 처리
                    elif query_subtype == "evalp_pref" and data:
                        first_item = data[0]

                        # 우대/감점 항목 없음
                        if not first_item.get("has_preference"):
                            sql_result = SQLQueryResult(
                                success=True,
                                columns=["안내"],
                                rows=[[first_item.get("message", "우대/감점 항목을 찾을 수 없습니다.")]],
                                row_count=1
                            )
                            loader_metadata = {
                                "loader_used": loader.__class__.__name__,
                                "announcement_name": first_item.get("announcement_name", ""),
                                "has_preference": False,
                                "suggestion": first_item.get("suggestion", ""),
                                **metadata
                            }
                        else:
                            # 우대/감점 항목 있음 - 우대, 감점 분리 출력
                            plus_items = first_item.get("plus_items", [])
                            minus_items = first_item.get("minus_items", [])

                            # Phase 90.1: f_ancm_prcnd 테이블 필드명에 맞게 수정
                            # condition_name: 조건명, detail_content: 세부내용, score: 점수
                            columns = ["구분", "조건명", "배점", "세부내용"]
                            rows = []

                            for item in plus_items:
                                cond_name = item.get("condition_name", "-")
                                detail = item.get("detail_content", "-")
                                # 세부내용이 너무 길면 축약
                                if len(detail) > 60:
                                    detail = detail[:60] + "..."
                                rows.append(["🟢 우대", cond_name, f"+{item.get('score', 0)}점", detail])
                            for item in minus_items:
                                cond_name = item.get("condition_name", "-")
                                detail = item.get("detail_content", "-")
                                if len(detail) > 60:
                                    detail = detail[:60] + "..."
                                rows.append(["🔴 감점", cond_name, f"-{abs(item.get('score', 0))}점", detail])

                            sql_result = SQLQueryResult(
                                success=True,
                                columns=columns,
                                rows=rows,
                                row_count=len(rows)
                            )

                            loader_metadata = {
                                "loader_used": loader.__class__.__name__,
                                "announcement_name": first_item.get("announcement_name", ""),
                                "year": first_item.get("year", ""),
                                "has_preference": True,
                                "plus_count": first_item.get("plus_count", 0),
                                "minus_count": first_item.get("minus_count", 0),
                                **metadata
                            }

                        logger.info(f"Phase 90: 우대/감점 정보 - 우대 {loader_metadata.get('plus_count', 0)}개, 감점 {loader_metadata.get('minus_count', 0)}개")

                    else:
                        # 일반 Loader 결과
                        if data and isinstance(data[0], dict):
                            columns = list(data[0].keys())
                            rows = [list(item.values()) for item in data]
                        else:
                            columns = []
                            rows = []

                        sql_result = SQLQueryResult(
                            success=True,
                            columns=columns,
                            rows=rows,
                            row_count=len(rows)
                        )
                        loader_metadata = {"loader_used": loader.__class__.__name__, **metadata}

                    sources = [{
                        "type": "loader",
                        "loader": loader.__class__.__name__,
                        "row_count": sql_result.row_count
                    }]

                    logger.info(f"Phase 88: Loader 실행 성공 - {sql_result.row_count}행")

                    # Phase 91: 실제 SQL 쿼리를 generated_sql에 저장 (loader.last_query 사용)
                    actual_sql = getattr(loader, 'last_query', None) or f"-- Loader: {loader.__class__.__name__}"
                    return {
                        **state,
                        "sql_result": sql_result,
                        "generated_sql": actual_sql,
                        "loader_used": loader.__class__.__name__,
                        "loader_metadata": loader_metadata,
                        "sources": state.get("sources", []) + sources
                    }
                else:
                    logger.warning(f"Phase 88: Loader 결과 없음 - SQL Agent fallback")
            except Exception as e:
                logger.error(f"Phase 88: Loader 실행 실패 - {e}")
                import traceback
                logger.error(traceback.format_exc())
                # SQL Agent fallback (아래 코드 계속 진행)

    # === Phase 86.1: 장비 검색 (entity_type 기반 우선 처리) ===
    # "equip" 엔티티 타입이면 subtype에 관계없이 장비 검색 로직 사용
    # Phase 94: 다중 엔티티(2개 이상)인 경우 개별 처리 스킵 → 멀티 엔티티 SQL로
    if "equip" in entity_types and len(entity_types) == 1:
        # 지역 정보 추출
        region = None
        if structured_keywords and structured_keywords.get("region"):
            region_val = structured_keywords["region"]
            region = region_val[0] if isinstance(region_val, list) else region_val

        logger.info(f"Phase 86.1: 장비 검색 쿼리 감지 (entity_type=equip, subtype={query_subtype}, region={region})")

        result = _execute_equipment_recommendation(
            keywords=keywords,
            query=query,
            region=region
        )

        sql_result = result["sql_result"]
        sources = []
        if sql_result.success and sql_result.rows:
            sources.append({
                "type": "equipment",
                "row_count": sql_result.row_count
            })

        logger.info(f"Phase 86.1: 장비 검색 완료 - {sql_result.row_count}건")

        return {
            **state,
            "sql_result": sql_result,
            "generated_sql": result.get("generated_sql"),
            "recommendation_type": "equipment",
            "sources": state.get("sources", []) + sources
        }

    # === Phase 87/104.5: 프로젝트 검색 (entity_type 기반 우선 처리) ===
    # entity_type이 'project'이면 subtype에 관계없이 프로젝트 목록 검색
    # Phase 94: 다중 엔티티(2개 이상)인 경우 개별 처리 스킵 → 멀티 엔티티 SQL로
    # Phase 104.5: ranking 쿼리도 추가 (기관 역량 검색)
    if "project" in entity_types and len(entity_types) == 1 and query_subtype in ("recommendation", "list", "ranking"):
        logger.info(f"Phase 87: 프로젝트 목록 쿼리 감지 (entity_type=project, subtype={query_subtype})")

        result = _execute_single_entity_sql(
            query=query,
            entity_type="project",
            keywords=keywords,
            vector_doc_ids=vector_doc_ids,
            expanded_keywords=expanded_keywords,
            is_aggregation=is_aggregation,
            query_subtype=query_subtype
        )

        sql_result = result["sql_result"]
        sources = []
        if sql_result.success and sql_result.rows:
            sources.append({
                "type": "sql",
                "entity_type": "project",
                "row_count": sql_result.row_count
            })

        logger.info(f"Phase 87: 프로젝트 목록 검색 완료 - {sql_result.row_count}건")

        return {
            **state,
            "sql_result": sql_result,
            "generated_sql": result.get("generated_sql"),
            "sources": state.get("sources", []) + sources
        }

    # === Phase 69: 추천 쿼리 처리 (협업 기관 vs 기술분류) ===
    if query_subtype == "recommendation":
        # Phase 69: 협업 기관 추천 키워드 감지
        COLLABORATION_KEYWORDS = {"협업", "협력", "파트너", "공동연구", "협력기관", "협업기관"}
        is_collaboration = any(kw in query for kw in COLLABORATION_KEYWORDS)
        is_tech_classification = "분류" in query or "tech" in entity_types

        # === Phase 69: 협업 기관 추천 ===
        if is_collaboration and not is_tech_classification:
            logger.info(f"Phase 69: 협업 기관 추천 쿼리 감지")

            result = _execute_collaboration_recommendation(
                keywords=keywords,
                query=query
            )

            sql_result = result["sql_result"]
            sources = []
            if sql_result.success and sql_result.rows:
                sources.append({
                    "type": "collaboration",
                    "row_count": sql_result.row_count
                })

            logger.info(f"Phase 69: 협업 기관 추천 완료 - {sql_result.row_count}건")

            return {
                **state,
                "sql_result": sql_result,
                "generated_sql": result.get("generated_sql"),
                "recommendation_type": "collaboration",
                "sources": state.get("sources", []) + sources
            }

        # Note: 장비 검색은 Phase 86.1에서 entity_type='equip' 기반으로 먼저 처리됨
        # recommendation 블록에서 제거하여 중복 방지

        # === Phase 62: 기술분류코드 추천 ===
        # 질문에서 분류체계 유형 자동 감지
        classification_type = _detect_classification_type_from_query(query)
        logger.info(f"Phase 62: 기술분류 추천 쿼리 감지 - classification_type={classification_type}")

        # Phase 62: 키워드 폴백 로직
        tech_keywords = keywords.copy() if keywords else []
        if not tech_keywords:
            exclude_patterns = [
                "신산업기술분류", "신산업", "기술분류", "분류코드", "추천",
                "6T", "6t", "K12", "k12", "관련", "연구제안서", "제안서",
                "합리적인", "적합한", "알려줘", "해줘"
            ]
            import re
            words = re.findall(r'[가-힣]+|[a-zA-Z0-9]+', query)
            for word in words:
                if len(word) >= 2 and word not in exclude_patterns:
                    tech_keywords.append(word)
            tech_keywords = tech_keywords[:3]
            logger.info(f"Phase 62: 원본 쿼리에서 키워드 폴백 추출 - {tech_keywords}")

        # 기술분류 추천 쿼리 실행
        result = _execute_tech_classification_recommendation(
            keywords=tech_keywords,
            classification_type=classification_type
        )

        sql_result = result["sql_result"]
        classification_label = result["classification_label"]

        sources = []
        if sql_result.success and sql_result.rows:
            sources.append({
                "type": "tech_classification",
                "classification_type": classification_type,
                "classification_label": classification_label,
                "row_count": sql_result.row_count
            })

        logger.info(f"Phase 62: 기술분류 추천 완료 - {sql_result.row_count}건 ({classification_label})")

        return {
            **state,
            "sql_result": sql_result,
            "generated_sql": result.get("generated_sql"),
            "classification_type": classification_type,
            "classification_label": classification_label,
            "sources": state.get("sources", []) + sources
        }

    # === Phase 44/48: 특수 엔티티(evalp, evalp_detail, ancm 등) 단일 처리 ===
    # sql_prompts.py의 ENTITY_COLUMNS에 정의된 엔티티는 전용 템플릿 사용
    # Phase 64: "patent" 추가 - 국가 필터 힌트 적용을 위해
    SPECIAL_ENTITIES = {"evalp", "evalp_detail", "ancm", "proposal", "equip", "patent"}
    if len(entity_types) == 1 and entity_types[0] in SPECIAL_ENTITIES:
        logger.info(f"특수 엔티티 단일 처리: {entity_types[0]}, query_subtype={query_subtype}")
        result = _execute_single_entity_sql(
            query=query,
            entity_type=entity_types[0],
            keywords=keywords,
            vector_doc_ids=vector_doc_ids,
            expanded_keywords=expanded_keywords,
            is_aggregation=is_aggregation,
            query_subtype=query_subtype  # Phase 72.2: ranking 쿼리 지원
        )

        sql_result = result["sql_result"]
        sources = []
        if sql_result.success and sql_result.rows:
            sources.append({
                "type": "sql",
                "entity_type": entity_types[0],
                "row_count": sql_result.row_count
            })

        return {
            **state,
            "sql_result": sql_result,
            "generated_sql": result.get("generated_sql"),
            "sources": state.get("sources", []) + sources
        }

    # Phase 94: domain_hits 기반 멀티 도메인 검색 정보 추가
    domain_hits = state.get("domain_hits", {})
    if domain_hits:
        active_domains = [d for d, count in domain_hits.items() if count > 0]
        logger.info(f"Phase 94: ES Scout 활성 도메인 - {active_domains} (상세: {domain_hits})")

    # === Phase 19/53/94: 다중 엔티티 타입 처리 ===
    if len(entity_types) >= 2:
        # Phase 53: 엔티티별 독립 키워드 가져오기
        entity_keywords = state.get("entity_keywords")  # {"patent": [...], "project": [...]}
        logger.info(f"다중 엔티티 쿼리 감지: {entity_types}, is_aggregation={is_aggregation}")
        if entity_keywords:
            logger.info(f"Phase 53: 엔티티별 키워드 사용 - {list(entity_keywords.keys())}")
        if domain_hits:
            logger.info(f"Phase 94: ES Scout 결과 기반 멀티 도메인 SQL 실행")

        # Phase 94.1: ES doc_ids 가져오기
        es_doc_ids = state.get("es_doc_ids", {})
        if es_doc_ids:
            logger.info(f"Phase 94.1: ES Scout doc_ids 사용 - {list(es_doc_ids.keys())}")

        multi_results = _execute_multi_entity_sql(
            query=query,
            entity_types=entity_types,
            keywords=keywords,
            vector_doc_ids=vector_doc_ids,
            expanded_keywords=expanded_keywords,
            is_aggregation=is_aggregation,
            entity_keywords=entity_keywords,  # Phase 53: 엔티티별 키워드 전달
            query_subtype=query_subtype,  # Phase 72.2: ranking 쿼리 지원
            es_doc_ids=es_doc_ids  # Phase 94.1: ES Scout 도메인별 문서 ID
        )

        # 소스 정보 생성
        sources = []
        total_rows = 0
        for entity_type, result in multi_results.items():
            if result.success and result.rows:
                sources.append({
                    "type": "sql",
                    "entity_type": entity_type,
                    "row_count": result.row_count
                })
                total_rows += result.row_count

        logger.info(f"다중 엔티티 SQL 완료: {len(multi_results)}개 타입, 총 {total_rows}행")

        # Phase 94: domain_hits 정보도 함께 반환
        return {
            **state,
            "multi_sql_results": multi_results,
            "sql_result": None,  # 다중 결과 사용 시 단일 결과는 None
            "generated_sql": f"-- 다중 엔티티 쿼리: {', '.join(entity_types)}",
            "domain_hits": domain_hits,  # Phase 94: ES Scout 결과 전달
            "sources": state.get("sources", []) + sources
        }

    # === 기존 단일 엔티티 처리 ===
    try:
        sql_agent = get_sql_agent()

        # Phase 27: 통계/집계 쿼리면 벡터 doc_ids 무시
        effective_doc_ids = [] if is_aggregation else vector_doc_ids
        if is_aggregation:
            logger.info(f"통계/집계 쿼리 - 벡터 doc_ids 무시, 전체 데이터 대상 쿼리")

        # Phase 29: 키워드 기반 SQL 힌트 생성 (doc_ids 제거)
        sql_hints = None
        if expanded_keywords:
            from workflow.nodes.vector_enhancer import build_sql_hints
            sql_hints = build_sql_hints(expanded_keywords, entity_types, query_subtype)
            logger.info(f"Keyword hints 적용: {len(expanded_keywords)} keywords, subtype={query_subtype}")

        # 다중 엔티티 타입 힌트 추가 (특허+과제 등) - 단일 엔티티에서도 폴백
        table_hints = _build_table_hints(entity_types)
        if table_hints:
            if sql_hints:
                sql_hints = sql_hints + "\n\n" + table_hints
            else:
                sql_hints = table_hints
            logger.info(f"Table hints 적용: entity_types={entity_types}")

        # Phase 28: 쿼리 서브타입 힌트 추가 (Phase 36: expanded_keywords 사용)
        subtype_hints = _build_query_subtype_hints(query_subtype, keywords, expanded_keywords)
        if subtype_hints:
            if sql_hints:
                sql_hints = subtype_hints + "\n\n" + sql_hints
            else:
                sql_hints = subtype_hints
            logger.info(f"Query subtype hints 적용: subtype={query_subtype}")

        # Phase 99.8 Debug: 실제 전달되는 키워드 확인
        print(f"[SQL_EXECUTOR] Phase 99.8 Debug: keywords={keywords}, expanded_keywords={expanded_keywords}")

        # Phase 34.5: 구조화된 키워드 힌트 추가
        # Phase 51.2: keywords와 query 전달하여 지역 자동 감지 활성화
        struct_hints = _build_structured_keyword_hints(structured_keywords, keywords, query)
        if struct_hints:
            if sql_hints:
                sql_hints = sql_hints + "\n\n" + struct_hints
            else:
                sql_hints = struct_hints
            logger.info(f"Structured keyword hints 적용: {structured_keywords}")

        # SQL 에이전트 실행
        response = sql_agent.query(
            question=query,
            interpret_result=False,  # 해석은 generator 노드에서 수행
            max_tokens=1024,
            temperature=0.3,
            sql_hints=sql_hints  # 벡터 힌트 전달
        )

        # 결과 변환
        sql_result = SQLQueryResult(
            success=response.result.success,
            columns=response.result.columns,
            rows=response.result.rows,
            row_count=response.result.row_count,
            error=response.result.error,
            execution_time_ms=response.result.execution_time_ms
        )

        # 소스 정보
        sources = []
        if response.result.success and response.result.rows:
            sources.append({
                "type": "sql",
                "sql": response.generated_sql,
                "tables": response.related_tables,
                "row_count": response.result.row_count
            })

        logger.info(f"SQL 실행 성공: {response.result.row_count}행")

        return {
            **state,
            "sql_result": sql_result,
            "multi_sql_results": None,
            "generated_sql": response.generated_sql,
            "sources": state.get("sources", []) + sources
        }

    except Exception as e:
        logger.error(f"SQL 실행 실패: {e}")
        return {
            **state,
            "sql_result": SQLQueryResult(success=False, error=str(e)),
            "multi_sql_results": None,
            "generated_sql": None,
            "error": f"SQL 실행 실패: {str(e)}"
        }


def _format_cell(cell, max_length: int = 200) -> str:
    """Phase 52/54/92: 셀 값을 답변생성전략 가이드라인에 맞게 포맷팅

    - 정수: 천 단위 쉼표 (1,234)
    - 소수: 소수점 1자리 (88.5)
    - 문자열: max_length자 제한 (Phase 92: 100→200 확대하여 과제명/특허명 전체 보존)
    """
    if cell is None:
        return ""
    if isinstance(cell, int):
        return f"{cell:,}"
    if isinstance(cell, float):
        if cell == int(cell):
            return f"{int(cell):,}"
        return f"{cell:,.1f}"
    text = str(cell)
    if len(text) > max_length:
        return text[:max_length-3] + "..."
    return text


def format_sql_result_for_llm(sql_result: SQLQueryResult, max_rows: int = 10) -> str:
    """SQL 결과를 LLM 컨텍스트용으로 포맷팅

    Phase 52: 답변생성전략 가이드라인 반영
    - 천 단위 쉼표 적용
    - 소수점 1자리 포맷팅
    """
    if not sql_result.success:
        return f"SQL 실행 오류: {sql_result.error}"

    if not sql_result.rows:
        return "조회된 데이터가 없습니다."

    lines = []
    lines.append(f"총 {sql_result.row_count:,}행 조회됨")
    lines.append("")

    # 헤더
    if sql_result.columns:
        header = " | ".join(str(col) for col in sql_result.columns)
        lines.append(header)
        lines.append("-" * len(header))

    # 데이터 (Phase 52: 숫자 포맷팅 적용)
    for row in sql_result.rows[:max_rows]:
        row_str = " | ".join(_format_cell(cell) for cell in row)
        lines.append(row_str)

    if sql_result.row_count > max_rows:
        lines.append(f"... 외 {sql_result.row_count - max_rows:,}행")

    return "\n".join(lines)


# === Phase 90.1: ES 폴백 함수 ===

def _fallback_to_es_ranking(
    query: str,
    keywords: List[str],
    entity_type: str = "patent"
) -> Optional[SQLQueryResult]:
    """SQL 결과 0건 시 ES ranking 폴백

    Args:
        query: 원본 질문
        keywords: 검색 키워드 목록
        entity_type: 엔티티 타입 (기본값: patent)

    Returns:
        SQLQueryResult 또는 None
    """
    try:
        import asyncio
        from search.es_client import ESSearchClient, ES_ENABLED

        if not ES_ENABLED:
            logger.info("Phase 90.1: ES 비활성화 상태 - 폴백 스킵")
            return None

        es_client = ESSearchClient()

        # 특허 출원기관 랭킹용 그룹 필드
        group_field_map = {
            "patent": "patent_frst_appn.keyword",
            "project": "conts_rspns_nm.keyword",
            "proposal": "orgn_nm.keyword",
            "equipment": "org_nm.keyword",
        }

        group_field = group_field_map.get(entity_type, "patent_frst_appn.keyword")
        search_query = " ".join(keywords[:3]) if keywords else query[:50]

        # 동기/비동기 환경 처리
        async def _do_es_ranking():
            return await es_client.ranking(
                query=search_query,
                entity_type=entity_type,
                group_field=group_field,
                limit=10
            )

        # 이벤트 루프 확인
        try:
            loop = asyncio.get_running_loop()
            # 이미 실행 중인 루프가 있으면 직접 실행 불가 - nest_asyncio 필요
            import nest_asyncio
            nest_asyncio.apply()
            es_results = asyncio.run(_do_es_ranking())
        except RuntimeError:
            # 실행 중인 루프가 없으면 새로 생성
            es_results = asyncio.run(_do_es_ranking())

        if not es_results:
            logger.info("Phase 90.1: ES ranking 결과 없음")
            return None

        # ES 결과를 SQLQueryResult 형태로 변환
        columns = ["출원기관", "특허수", "대표특허"]
        rows = []
        for result in es_results[:10]:
            rows.append([
                result.key,  # 출원기관명
                result.doc_count,  # 특허 수
                f"(ES 검색 결과 - {result.doc_count}건)"  # 대표특허 대신 설명
            ])

        logger.info(f"Phase 90.1: ES ranking 결과 변환 - {len(rows)}행")

        return SQLQueryResult(
            success=True,
            columns=columns,
            rows=rows,
            row_count=len(rows)
        )

    except Exception as e:
        logger.error(f"Phase 90.1: ES 폴백 실패 - {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None
