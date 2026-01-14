"""
Vector-Enhanced SQL 전처리 노드 (Phase 29)
- 벡터 검색으로 관련 문서 검색 (400개/컬렉션)
- Komoran 형태소 분석 기반 키워드 확장
- LLM 원본 키워드 + 벡터 확장 키워드 병합
- Phase 94: ES Scout - 전체 도메인 스캔으로 결과 있는 도메인 식별
- Phase 100: ES Scout가 별도 노드로 분리됨 (es_scout.py)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import logging
import re
from typing import Dict, Any, List, Set
from collections import Counter

from workflow.state import AgentState
from workflow.utils.keyword_extractor import get_keyword_extractor, KeywordExtractionResult
from graph.graph_rag import QdrantSearcher

logger = logging.getLogger(__name__)

# Phase 94: ES Scout 도메인 목록
ES_SCOUT_DOMAINS = ["patent", "project", "equipment", "proposal"]

# 엔티티 타입 → Qdrant 컬렉션 매핑 (리스트로 통일)
# Phase 32: 도메인 특화 벡터 검색
ENTITY_TO_COLLECTION = {
    # 기존 매핑
    "patent": ["patents_v3_collection"],
    "project": ["projects_v3_collection"],
    "equip": ["equipments_v3_collection"],
    "org": ["equipments_v3_collection"],
    "applicant": ["patents_v3_collection"],
    "tech": ["tech_classifications_v3_collection"],
    # Phase 32: 제안서/공고/평가 관련 추가
    "proposal": ["proposals_v3_collection"],
    "evalp": ["proposals_v3_collection"],  # 평가표 - 제안서 컬렉션에서 검색
    "evalp_detail": ["proposals_v3_collection"],  # Phase 48: 평가표 세부 항목
    "ancm": ["proposals_v3_collection"],   # 공고 - 제안서 컬렉션에서 검색
}

# 엔티티 타입 → SQL WHERE 절 컬럼 매핑 (Phase 18)
ENTITY_ID_COLUMNS = {
    "patent": "documentid",
    "applicant": "documentid",
    "ipc": "documentid",
    "project": "conts_id",
    "equip": "conts_id",
    "org": "conts_id",
    "proposal": "sbjt_id",
    "tech": "sbjt_id",
    "evalp": "id",
    "evalp_detail": "id",  # Phase 48
    "ancm": "id",
}

# Phase 29/31/96: 벡터 검색 설정
VECTOR_SEARCH_LIMIT = 100  # 컬렉션당 검색 수 (Phase 31: 100으로 최적화)
KEYWORD_MIN_FREQUENCY = 60  # Phase 96: 50 → 60 (60%) - 환각 방지 강화
KEYWORD_MAX_COUNT = 3  # Phase 96: 8 → 3 - 확장 키워드 수 제한


def enhance_with_vector(state: AgentState) -> AgentState:
    """SQL 쿼리 전 벡터 검색으로 키워드 확장 (Phase 29, 53, 100)

    Phase 53: 다중 엔티티 시 각 엔티티별로 독립 검색하여 키워드 희석 방지
    Phase 100: ES Scout가 별도 노드로 분리됨 - state에서 es_doc_ids, domain_hits 재사용

    Args:
        state: 현재 에이전트 상태

    Returns:
        expanded_keywords, entity_keywords, keyword_extraction_result가 추가된 상태
    """
    query = state.get("query", "")
    entity_types = state.get("entity_types", [])
    query_subtype = state.get("query_subtype", "list")
    query_type = state.get("query_type", "")

    # analyzer에서 LLM으로 추출한 키워드 (동의어 확장 포함 - es_scout에서 처리)
    llm_keywords = state.get("keywords", [])

    # Phase 100: es_scout 노드에서 이미 수집된 결과 재사용
    es_doc_ids = state.get("es_doc_ids", {})
    domain_hits = state.get("domain_hits", {})

    print(f"[VECTOR_ENHANCER] Phase 100: 시작 - es_doc_ids={bool(es_doc_ids)}, domain_hits={domain_hits}")

    if not query.strip():
        return state

    try:
        qdrant = QdrantSearcher()
        extractor = get_keyword_extractor()

        # Qdrant 벡터 검색으로 키워드 확장
        collections = _get_collections_for_entities(entity_types)
        logger.info(f"Vector Enhancement 시작: query={query[:50]}..., collections={collections}")

        # 다중 컬렉션 검색 (limit=100, 키워드 추출 품질 향상)
        vector_results = qdrant.multi_search(
            query=query,
            collections=collections,
            limit_per_collection=VECTOR_SEARCH_LIMIT
        )

        # Komoran 기반 키워드 추출 및 병합 (Phase 31: LLM 검토 활성화)
        extraction_result = extractor.extract_and_merge(
            llm_keywords=llm_keywords,
            vector_results=vector_results,
            min_frequency=KEYWORD_MIN_FREQUENCY,
            max_expanded=KEYWORD_MAX_COUNT,
            query=query,
            use_llm_review=True
        )

        logger.info(f"Vector Enhancement 완료:")
        logger.info(f"  - LLM 원본 (동의어 포함): {extraction_result.original_keywords}")
        logger.info(f"  - 벡터 확장: {extraction_result.expanded_keywords}")
        logger.info(f"  - 최종 키워드: {extraction_result.final_keywords}")

        # Phase 100: ES Scout 결과가 있으면 entity_types 업데이트
        scout_result = {"hits": domain_hits, "doc_ids": es_doc_ids}
        if domain_hits:
            entity_types = _update_entity_types_from_scout(
                original_entity_types=entity_types,
                scout_result=scout_result,
                query_subtype=query_subtype
            )

        # Phase 53: 다중 엔티티인 경우 엔티티별 독립 검색
        if len(entity_types) >= 2:
            return _enhance_multi_entity(
                state=state,
                query=query,
                entity_types=entity_types,
                llm_keywords=llm_keywords,
                qdrant=qdrant,
                extractor=extractor,
                scout_result=scout_result  # Phase 94.1: ES Scout 결과 전달 (hits + doc_ids)
            )

        # Phase 35: 벡터 결과 캐싱 (rag_retriever 재사용)
        # Phase 87: dict/object 양쪽 지원
        cached_results = {}
        for collection, results in vector_results.items():
            cached_results[collection] = [
                {
                    "id": str(r.get('id', '') if isinstance(r, dict) else getattr(r, 'id', '')),
                    "score": r.get('score', 0.0) if isinstance(r, dict) else getattr(r, 'score', 0.0),
                    "payload": r.get('payload', {}) if isinstance(r, dict) else getattr(r, 'payload', {})
                }
                for r in results
            ]

        return {
            **state,
            "expanded_keywords": extraction_result.final_keywords,
            "keyword_extraction_result": extraction_result.to_dict(),
            "cached_vector_results": cached_results,
            "entity_keywords": None,  # 단일 엔티티는 entity_keywords 불필요
            "entity_types": entity_types,  # Phase 94: ES Scout 결과 반영
            "domain_hits": scout_result.get("hits", {}),  # Phase 94: 도메인별 히트 수
            "es_doc_ids": scout_result.get("doc_ids", {}),  # Phase 94.1: 도메인별 문서 ID
            "vector_doc_ids": [],
            "vector_scores": {},
            "vector_result_count": extraction_result.source_doc_count
        }

    except Exception as e:
        logger.error(f"Vector Enhancement 실패: {e}", exc_info=True)
        # Phase 100: es_doc_ids, domain_hits는 es_scout 노드에서 이미 state에 설정됨
        return {
            **state,
            "expanded_keywords": llm_keywords,
            "keyword_extraction_result": None,
            "entity_keywords": None,
            "entity_types": entity_types,
            "domain_hits": domain_hits,  # Phase 100: state에서 재사용
            "es_doc_ids": es_doc_ids,    # Phase 100: state에서 재사용
            "vector_doc_ids": [],
            "vector_scores": {},
            "vector_result_count": 0
        }


def _enhance_multi_entity(
    state: AgentState,
    query: str,
    entity_types: List[str],
    llm_keywords: List[str],
    qdrant: QdrantSearcher,
    extractor,
    scout_result: Dict[str, Any] = None  # Phase 94.1: ES Scout 결과 (hits + doc_ids)
) -> AgentState:
    """Phase 53: 다중 엔티티 쿼리를 위한 독립 벡터 검색

    각 엔티티 타입별로 독립적으로 벡터 검색하여 키워드 추출.
    키워드 희석 문제 해결.

    Args:
        state: 현재 상태
        query: 사용자 질문
        entity_types: 엔티티 타입 목록 (2개 이상)
        llm_keywords: LLM 추출 키워드
        qdrant: Qdrant 검색기
        extractor: 키워드 추출기
        scout_result: Phase 94.1 ES Scout 결과 {"hits": {...}, "doc_ids": {...}}

    Returns:
        entity_keywords가 추가된 상태
    """
    scout_result = scout_result or {"hits": {}, "doc_ids": {}}
    logger.info(f"Phase 53: 다중 엔티티 독립 검색 시작 - entities={entity_types}")

    entity_keywords = {}  # {"patent": [...], "project": [...]}
    all_cached_results = {}
    all_expanded_keywords = list(llm_keywords)  # LLM 원본으로 시작
    total_doc_count = 0

    for entity_type in entity_types:
        # 엔티티별 컬렉션 가져오기
        collections = ENTITY_TO_COLLECTION.get(entity_type, [])
        if not collections:
            logger.warning(f"  - {entity_type}: 컬렉션 없음, 스킵")
            entity_keywords[entity_type] = list(llm_keywords)  # LLM 키워드 폴백
            continue

        logger.info(f"  - {entity_type}: 컬렉션={collections}")

        # 해당 엔티티 컬렉션만 검색
        vector_results = qdrant.multi_search(
            query=query,
            collections=collections,
            limit_per_collection=VECTOR_SEARCH_LIMIT
        )

        # 엔티티별 키워드 추출
        extraction_result = extractor.extract_and_merge(
            llm_keywords=llm_keywords,
            vector_results=vector_results,
            min_frequency=KEYWORD_MIN_FREQUENCY,
            max_expanded=KEYWORD_MAX_COUNT,
            query=query,
            use_llm_review=True
        )

        # 엔티티별 키워드 저장
        entity_keywords[entity_type] = extraction_result.final_keywords
        logger.info(f"  - {entity_type}: 키워드={extraction_result.final_keywords}")

        # 전체 확장 키워드에도 추가 (중복 제거)
        for kw in extraction_result.final_keywords:
            if kw not in all_expanded_keywords:
                all_expanded_keywords.append(kw)

        # 캐시 결과 저장 (Phase 87: dict/object 양쪽 지원)
        for collection, results in vector_results.items():
            all_cached_results[collection] = [
                {
                    "id": str(r.get('id', '') if isinstance(r, dict) else getattr(r, 'id', '')),
                    "score": r.get('score', 0.0) if isinstance(r, dict) else getattr(r, 'score', 0.0),
                    "payload": r.get('payload', {}) if isinstance(r, dict) else getattr(r, 'payload', {})
                }
                for r in results
            ]

        total_doc_count += extraction_result.source_doc_count

    logger.info(f"Phase 53: 다중 엔티티 독립 검색 완료")
    logger.info(f"  - entity_keywords: {entity_keywords}")
    logger.info(f"  - 통합 키워드: {all_expanded_keywords}")

    return {
        **state,
        "expanded_keywords": all_expanded_keywords,
        "entity_keywords": entity_keywords,  # Phase 53: 핵심 추가
        "entity_types": entity_types,  # Phase 94: ES Scout 결과 반영
        "domain_hits": scout_result.get("hits", {}),  # Phase 94: 도메인별 히트 수
        "es_doc_ids": scout_result.get("doc_ids", {}),  # Phase 94.1: 도메인별 문서 ID
        "keyword_extraction_result": {
            "type": "multi_entity",
            "entity_keywords": entity_keywords,
            "all_keywords": all_expanded_keywords
        },
        "cached_vector_results": all_cached_results,
        "vector_doc_ids": [],
        "vector_scores": {},
        "vector_result_count": total_doc_count
    }


def _get_collections_for_entities(entity_types: List[str]) -> List[str]:
    """엔티티 타입에 따른 컬렉션 목록 반환

    Args:
        entity_types: 엔티티 타입 목록 (예: ["patent", "project"])

    Returns:
        Qdrant 컬렉션 목록
    """
    if not entity_types:
        # 기본값: 특허와 과제 둘 다
        return ["patents_v3_collection", "projects_v3_collection"]

    collections = set()
    for et in entity_types:
        if et in ENTITY_TO_COLLECTION:
            # 리스트로 변경되었으므로 update 사용
            collections.update(ENTITY_TO_COLLECTION[et])

    # 폴백도 특허+과제 둘 다
    return list(collections) if collections else ["patents_v3_collection", "projects_v3_collection"]


def build_sql_hints(
    keywords: List[str],
    expanded_keywords: List[str] = None,
    entity_types: List[str] = None,
    query_subtype: str = "list"
) -> str:
    """키워드 기반 SQL 힌트 생성 (Phase 99.8: 동의어 OR 확장 패턴)

    Phase 67 AND+OR → Phase 99.8 단순 OR 변경
    - 핵심 키워드 + 확장 키워드(동의어 포함)를 모두 OR로 검색
    - 동의어 검색 범위 확대로 검색 재현율 향상

    Args:
        keywords: LLM 추출 핵심 키워드 (필수)
        expanded_keywords: 벡터 확장 키워드 (동의어/유사어 포함)
        entity_types: 엔티티 타입 목록
        query_subtype: 쿼리 유형 (list, aggregation, ranking 등)

    Returns:
        SQL 프롬프트에 포함할 힌트 문자열
    """
    hints = []

    if not keywords:
        return ""

    # 엔티티 타입 관련 단어 제외 (검색 키워드가 아님)
    entity_words = {"특허", "연구과제", "과제", "장비", "제안서", "공고", "출원인", "기관", "프로젝트"}

    # 핵심 키워드 필터링 (최대 3개)
    core_keywords = [kw for kw in keywords if kw not in entity_words][:3]
    if not core_keywords:
        core_keywords = keywords[:3]  # 폴백: 필터링 결과 없으면 원본 사용

    # 엔티티 타입에 따른 검색 컬럼 결정
    search_column = _get_search_column_for_entities(entity_types)

    # Phase 99.8: 동의어 OR 확장 패턴
    # 확장 키워드 중 핵심에 없는 것만 추출 (최대 3개)
    expanded_only = []
    if expanded_keywords:
        expanded_only = [kw for kw in expanded_keywords
                        if kw not in entity_words and kw not in core_keywords][:3]

    # 모든 키워드를 OR로 통합 (핵심 + 동의어/확장)
    all_keywords = list(core_keywords)
    if expanded_only:
        all_keywords.extend(expanded_only)

    # 단순 OR 조건 (동의어 포함)
    keyword_conditions = " OR ".join(
        f"{search_column} ILIKE '%{kw}%'" for kw in all_keywords
    )

    if expanded_only:
        hints.append("## 검색 조건 (Phase 99.8: 동의어 OR 확장)")
        hints.append(f"핵심 키워드: {core_keywords}")
        hints.append(f"동의어/확장: {expanded_only}")
    else:
        hints.append("## 검색 조건 (핵심 키워드)")
        hints.append(f"키워드: {core_keywords}")

    hints.append("")
    hints.append("```sql")
    hints.append(f"WHERE ({keyword_conditions})")
    hints.append("```")
    hints.append("")

    # 쿼리 유형별 추가 힌트
    if query_subtype in ["aggregation", "ranking"]:
        hints.append("## 통계/집계 쿼리 주의사항")
        hints.append("- 위 키워드 조건을 사용하여 전체 데이터에서 집계하세요")
        hints.append("- LIMIT 절 없이 전체 결과를 집계해야 정확한 통계가 됩니다")
        hints.append("")

    return "\n".join(hints)


def _get_search_column_for_entities(entity_types: List[str]) -> str:
    """엔티티 타입에 따른 검색 컬럼 반환

    Args:
        entity_types: 엔티티 타입 목록

    Returns:
        검색에 사용할 컬럼명
    """
    if not entity_types:
        return "title"  # 기본값

    # 엔티티 타입별 주요 텍스트 컬럼
    entity_search_columns = {
        "patent": "title",
        "applicant": "title",
        "project": "conts_klang_nm",
        "equip": "conts_klang_nm",
        "org": "conts_klang_nm",
        "proposal": "sbjt_nm",
        "tech": "sbjt_nm",
    }

    for et in entity_types:
        if et in entity_search_columns:
            return entity_search_columns[et]

    return "title"


def _scout_all_domains(keywords: List[str], query: str = "",
                       original_keywords: List[str] = None) -> Dict[str, Any]:
    """Phase 94/94.1/100.3: ES 전체 도메인 스캔으로 결과 있는 도메인 식별 및 문서 ID 수집

    LLM이 추측한 entity_types 대신 실제 데이터가 있는 도메인을 찾습니다.
    Phase 94.1: SQL 필터링을 위한 문서 ID도 수집합니다.
    Phase 94.3: "역량 보유" 검색 시 equipment 제외 (장비는 구매/보유일 뿐 기술 역량이 아님)
    Phase 100.3: original_keywords 추가 - 원본 키워드 기준 OR 매칭

    Args:
        keywords: 확장된 전체 키워드 목록 (원본 + 동의어)
        query: 원본 쿼리 (키워드가 없을 때 사용)
        original_keywords: LLM이 추출한 핵심 키워드 (Phase 100.3)

    Returns:
        {
            "hits": {"patent": 5, "project": 1, ...},
            "doc_ids": {"patent": ["id1", "id2"], "project": ["id3"], ...}
        }
    """
    # ES 비활성화 상태 체크
    es_enabled = os.getenv("ES_ENABLED", "false").lower() == "true"
    if not es_enabled:
        logger.info("Phase 94: ES Scout 스킵 - ES 비활성화 상태")
        return {"hits": {}, "doc_ids": {}}

    # Phase 94.3: "역량 보유" 검색 시 equipment 제외
    # 장비는 구매해서 보유하고 있는 것일 뿐, 기술을 개발/보유한 것이 아님
    capability_keywords = ["역량", "보유", "기술력", "전문성", "개발역량", "연구역량"]
    is_capability_search = any(kw in query for kw in capability_keywords)

    if is_capability_search:
        search_domains = ["patent", "project", "proposal"]  # equipment 제외
        logger.info("Phase 94.3: 역량 검색 - equipment 제외 (특허/과제/제안서만 검색)")
    else:
        search_domains = ES_SCOUT_DOMAINS

    search_text = " ".join(keywords) if keywords else query
    if not search_text.strip():
        logger.warning("Phase 94: ES Scout 스킵 - 검색 키워드 없음")
        return {"hits": {}, "doc_ids": {}}

    try:
        from search.es_client import ESSearchClient

        es_client = ESSearchClient()
        if not es_client.is_available():
            logger.warning("Phase 94: ES Scout 스킵 - ES 연결 실패")
            return {"hits": {}, "doc_ids": {}}

        domain_hits = {}
        domain_doc_ids = {}  # Phase 94.1: 도메인별 문서 ID

        # 도메인별 ID 필드 매핑
        domain_id_fields = {
            "patent": "documentid",
            "project": "conts_id",
            "equipment": "conts_id",
            "proposal": "sbjt_id",
        }

        # Phase 94.2: 도메인별 제목 필드
        domain_title_fields = {
            "patent": "conts_klang_nm",
            "project": "conts_klang_nm",
            "equipment": "conts_klang_nm",
            "proposal": "sbjt_nm",
        }

        for domain in search_domains:
            try:
                # Phase 94.2: 50개 검색 후 점수 기반 + 키워드 포함 필터링
                results = es_client.search_sync(
                    query=search_text,
                    entity_type=domain,
                    limit=50,
                    include_highlight=False
                )

                # Phase 100.3: 원본 키워드 기준 OR 매칭
                # 동의어는 보너스 점수로만 사용
                if results:
                    title_field = domain_title_fields.get(domain, "conts_klang_nm")
                    desc_field = "equip_desc" if domain == "equipment" else "conts_klang_nm"

                    keyword_filtered = []

                    # 원본 키워드와 동의어 분리
                    core_keywords = original_keywords if original_keywords else keywords[:2]
                    synonym_keywords = [k for k in keywords if k not in core_keywords] if original_keywords else []

                    for r in results:
                        title = r.source.get(title_field, "") or ""
                        desc = r.source.get(desc_field, "") or ""
                        combined_text = f"{title} {desc}".lower()

                        # Phase 100.3: 원본 키워드 중 최소 1개 매칭 (any)
                        core_match = any(
                            kw.lower() in combined_text
                            for kw in core_keywords if len(kw) >= 2
                        )

                        # 동의어 매칭 (보너스)
                        synonym_match = any(
                            syn.lower() in combined_text
                            for syn in synonym_keywords if len(syn) >= 2
                        ) if synonym_keywords else False

                        if core_match:
                            # 원본 키워드 매칭 + 동의어도 있으면 높은 점수
                            keyword_filtered.append((r, 3 if synonym_match else 2))
                        elif synonym_match:
                            # 동의어만 있어도 통과 (낮은 점수)
                            keyword_filtered.append((r, 1))
                        # else: 매칭 안 되면 제외

                    keyword_filtered.sort(key=lambda x: (-x[1], -x[0].score))
                    filtered_results = [r for r, _ in keyword_filtered]

                    logger.info(f"Phase 100.3: {domain} 필터링 - ES {len(results)}건 → 매칭 {len(filtered_results)}건 (core={core_keywords}, syn_cnt={len(synonym_keywords)})")
                else:
                    filtered_results = []

                hit_count = len(filtered_results)
                domain_hits[domain] = hit_count

                # Phase 94.1: 문서 ID 수집 (점수순 정렬 유지, 최대 20개)
                id_field = domain_id_fields.get(domain, "id")
                doc_ids = []
                for r in filtered_results[:20]:  # 상위 20개만
                    doc_id = r.source.get(id_field, r.id)
                    if doc_id:
                        doc_ids.append(doc_id)
                domain_doc_ids[domain] = doc_ids

                if hit_count > 0:
                    logger.info(f"Phase 94.2: ES Scout - {domain}: {hit_count}건 (상위 {len(doc_ids)}개 사용)")

            except Exception as e:
                logger.warning(f"Phase 94: ES Scout - {domain} 검색 실패: {e}")
                domain_hits[domain] = 0
                domain_doc_ids[domain] = []

        # 결과 요약 로그
        active_domains = [d for d, count in domain_hits.items() if count > 0]
        logger.info(f"Phase 94: ES Scout 완료 - 활성 도메인: {active_domains}, 상세: {domain_hits}")

        return {"hits": domain_hits, "doc_ids": domain_doc_ids}

    except ImportError:
        logger.warning("Phase 94: ES Scout 스킵 - es_client 모듈 없음")
        return {"hits": {}, "doc_ids": {}}
    except Exception as e:
        logger.error(f"Phase 94: ES Scout 실패: {e}", exc_info=True)
        return {"hits": {}, "doc_ids": {}}


def _scout_domains(keywords: List[str], query: str, domains: List[str],
                   original_keywords: List[str] = None) -> Dict[str, Any]:
    """Phase 100.2/100.3: 지정된 도메인만 검색 (동의어 OR 매칭)

    _scout_all_domains와 동일한 로직이지만, 지정된 도메인만 검색합니다.
    entity_types가 명시된 경우 해당 도메인만 검색하여 불필요한 검색을 줄입니다.

    Phase 100.3: original_keywords 추가 - 원본 키워드 기준 OR 매칭

    Args:
        keywords: 확장된 전체 키워드 목록 (원본 + 동의어)
        query: 원본 쿼리 (키워드가 없을 때 사용)
        domains: 검색할 도메인 목록 (예: ["patent"])
        original_keywords: LLM이 추출한 핵심 키워드 (Phase 100.3)

    Returns:
        {
            "hits": {"patent": 5, ...},
            "doc_ids": {"patent": ["id1", "id2"], ...}
        }
    """
    # ES 비활성화 상태 체크
    es_enabled = os.getenv("ES_ENABLED", "false").lower() == "true"
    if not es_enabled:
        logger.info("Phase 100.2: _scout_domains 스킵 - ES 비활성화 상태")
        return {"hits": {}, "doc_ids": {}}

    if not domains:
        logger.warning("Phase 100.2: _scout_domains 스킵 - 검색 도메인 없음")
        return {"hits": {}, "doc_ids": {}}

    search_text = " ".join(keywords) if keywords else query
    if not search_text.strip():
        logger.warning("Phase 100.2: _scout_domains 스킵 - 검색 키워드 없음")
        return {"hits": {}, "doc_ids": {}}

    logger.info(f"Phase 100.2: _scout_domains 시작 - domains={domains}, keywords={keywords[:3]}...")

    try:
        from search.es_client import ESSearchClient

        es_client = ESSearchClient()
        if not es_client.is_available():
            logger.warning("Phase 100.2: _scout_domains 스킵 - ES 연결 실패")
            return {"hits": {}, "doc_ids": {}}

        domain_hits = {}
        domain_doc_ids = {}

        # 도메인별 ID 필드 매핑
        domain_id_fields = {
            "patent": "documentid",
            "project": "conts_id",
            "equipment": "conts_id",
            "proposal": "sbjt_id",
        }

        # 도메인별 제목 필드
        domain_title_fields = {
            "patent": "conts_klang_nm",
            "project": "conts_klang_nm",
            "equipment": "conts_klang_nm",
            "proposal": "sbjt_nm",
        }

        for domain in domains:
            try:
                # 50개 검색 후 점수 기반 + 키워드 포함 필터링
                results = es_client.search_sync(
                    query=search_text,
                    entity_type=domain,
                    limit=50,
                    include_highlight=False
                )

                if results:
                    title_field = domain_title_fields.get(domain, "conts_klang_nm")
                    desc_field = "equip_desc" if domain == "equipment" else "conts_klang_nm"

                    # Phase 100.3: 원본 키워드 기준 OR 매칭
                    # 동의어는 보너스 점수로만 사용
                    keyword_filtered = []

                    # 원본 키워드와 동의어 분리
                    core_keywords = original_keywords if original_keywords else keywords[:2]
                    synonym_keywords = [k for k in keywords if k not in core_keywords] if original_keywords else []

                    for r in results:
                        title = r.source.get(title_field, "") or ""
                        desc = r.source.get(desc_field, "") or ""
                        combined_text = f"{title} {desc}".lower()

                        # Phase 100.3: 원본 키워드 중 최소 1개 매칭 (any)
                        core_match = any(
                            kw.lower() in combined_text
                            for kw in core_keywords if len(kw) >= 2
                        )

                        # 동의어 매칭 (보너스)
                        synonym_match = any(
                            syn.lower() in combined_text
                            for syn in synonym_keywords if len(syn) >= 2
                        ) if synonym_keywords else False

                        if core_match:
                            # 원본 키워드 매칭 + 동의어도 있으면 높은 점수
                            keyword_filtered.append((r, 3 if synonym_match else 2))
                        elif synonym_match:
                            # 동의어만 있어도 통과 (낮은 점수)
                            keyword_filtered.append((r, 1))
                        # else: 매칭 안 되면 제외

                    keyword_filtered.sort(key=lambda x: (-x[1], -x[0].score))
                    filtered_results = [r for r, _ in keyword_filtered]

                    logger.info(f"Phase 100.3: {domain} 필터링 - ES {len(results)}건 → 매칭 {len(filtered_results)}건 (core={core_keywords}, syn_cnt={len(synonym_keywords)})")
                else:
                    filtered_results = []

                hit_count = len(filtered_results)
                domain_hits[domain] = hit_count

                # 문서 ID 수집 (최대 20개)
                id_field = domain_id_fields.get(domain, "id")
                doc_ids = []
                for r in filtered_results[:20]:
                    doc_id = r.source.get(id_field, r.id)
                    if doc_id:
                        doc_ids.append(doc_id)
                domain_doc_ids[domain] = doc_ids

                if hit_count > 0:
                    logger.info(f"Phase 100.2: _scout_domains - {domain}: {hit_count}건 (상위 {len(doc_ids)}개 사용)")

            except Exception as e:
                logger.warning(f"Phase 100.2: _scout_domains - {domain} 검색 실패: {e}")
                domain_hits[domain] = 0
                domain_doc_ids[domain] = []

        logger.info(f"Phase 100.2: _scout_domains 완료 - {domain_hits}")
        return {"hits": domain_hits, "doc_ids": domain_doc_ids}

    except ImportError:
        logger.warning("Phase 100.2: _scout_domains 스킵 - es_client 모듈 없음")
        return {"hits": {}, "doc_ids": {}}
    except Exception as e:
        logger.error(f"Phase 100.2: _scout_domains 실패: {e}", exc_info=True)
        return {"hits": {}, "doc_ids": {}}


def _update_entity_types_from_scout(
    original_entity_types: List[str],
    scout_result: Dict[str, Any],
    query_subtype: str = ""
) -> List[str]:
    """Phase 94/96: ES Scout 결과로 entity_types 결정

    Phase 96: LLM이 entity_types를 비워두므로, ES Scout 결과가 주된 결정 기준.
    데이터가 실제로 존재하는 도메인만 검색 대상으로 채택.

    Args:
        original_entity_types: LLM이 분류한 entity_types (Phase 96: 대부분 빈 배열)
        scout_result: ES Scout 결과 {"hits": {...}, "doc_ids": {...}}
        query_subtype: 쿼리 유형

    Returns:
        ES Scout 기반 entity_types
    """
    if not scout_result or not scout_result.get("hits"):
        # Phase 96: ES Scout 결과 없으면 기본 도메인 사용
        if not original_entity_types:
            logger.info("Phase 96: ES Scout 결과 없음, 기본 entity_types=[patent, project] 사용")
            return ["patent", "project"]
        return original_entity_types

    domain_hits = scout_result.get("hits", {})

    # 결과가 있는 도메인 추출 (히트수 기준 정렬)
    active_domains = sorted(
        [(d, count) for d, count in domain_hits.items() if count > 0],
        key=lambda x: x[1],
        reverse=True
    )

    if not active_domains:
        # ES에서 결과 없으면 기본값
        if not original_entity_types:
            logger.info("Phase 96: ES Scout 결과 없음, 기본 entity_types=[patent, project] 사용")
            return ["patent", "project"]
        return original_entity_types

    # 도메인명 → entity_type 매핑
    domain_to_entity = {
        "patent": "patent",
        "project": "project",
        "equipment": "equip",
        "proposal": "proposal",
    }

    updated_entity_types = []
    for domain, count in active_domains:
        entity_type = domain_to_entity.get(domain)
        if entity_type and entity_type not in updated_entity_types:
            updated_entity_types.append(entity_type)

    # Phase 96: ES Scout 기반 결정이므로 로그에 명시
    if original_entity_types:
        logger.info(f"Phase 96: ES Scout 기반 entity_types 업데이트 - LLM: {original_entity_types} → ES: {updated_entity_types}")
    else:
        logger.info(f"Phase 96: ES Scout 기반 entity_types 결정 - {updated_entity_types} (hits: {dict(active_domains)})")

    return updated_entity_types if updated_entity_types else ["patent", "project"]
