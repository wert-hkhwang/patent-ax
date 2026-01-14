"""ES Scout 노드 - 동의어 확장 및 도메인 탐색

Phase 100: analyzer 직후 실행되어 동의어 확장 키워드로 ES 검색 수행

주요 기능:
1. 동의어 사전(synonyms.txt) 기반 키워드 확장
2. ES 검색으로 도메인별 doc_ids 수집
3. 활성 도메인(entity_types) 결정
"""

import os
import logging
from pathlib import Path
from typing import Dict, List, Any, Set, Optional

from workflow.state import AgentState

logger = logging.getLogger(__name__)

# 동의어 사전 캐시
_SYNONYM_CACHE: Optional[Dict[str, Set[str]]] = None


def _load_synonyms() -> Dict[str, Set[str]]:
    """동의어 사전 로드 및 캐싱

    synonyms.txt 형식:
    수소연료전지, hydrogen fuel cell, 연료전지, 수소전지

    Returns:
        양방향 동의어 매핑 딕셔너리
    """
    global _SYNONYM_CACHE
    if _SYNONYM_CACHE is not None:
        return _SYNONYM_CACHE

    synonyms_path = Path(__file__).parent.parent.parent / "config" / "elasticsearch" / "synonyms.txt"
    if not synonyms_path.exists():
        logger.warning(f"동의어 사전 파일 없음: {synonyms_path}")
        _SYNONYM_CACHE = {}
        return _SYNONYM_CACHE

    synonym_map: Dict[str, Set[str]] = {}
    try:
        with open(synonyms_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # 쉼표로 구분된 동의어 그룹
                terms = [t.strip() for t in line.split(",") if t.strip()]
                if len(terms) < 2:
                    continue

                term_set = set(terms)
                for term in terms:
                    term_lower = term.lower()
                    if term_lower in synonym_map:
                        synonym_map[term_lower].update(term_set)
                    else:
                        synonym_map[term_lower] = term_set.copy()

        logger.info(f"동의어 사전 로드 완료: {len(synonym_map)}개 키워드")
        _SYNONYM_CACHE = synonym_map
        return _SYNONYM_CACHE

    except Exception as e:
        logger.error(f"동의어 사전 로드 실패: {e}")
        _SYNONYM_CACHE = {}
        return _SYNONYM_CACHE


def expand_with_synonyms(keywords: List[str], max_per_keyword: int = 3) -> List[str]:
    """동의어 사전 기반 키워드 확장

    Args:
        keywords: 원본 키워드 목록
        max_per_keyword: 키워드당 최대 동의어 수

    Returns:
        확장된 키워드 목록 (중복 제거, 순서 유지)
    """
    if not keywords:
        return keywords

    synonym_map = _load_synonyms()
    if not synonym_map:
        return keywords

    expanded = list(keywords)  # 원본 키워드 먼저

    for kw in keywords:
        kw_lower = kw.lower()

        # 1. 정확 매칭
        if kw_lower in synonym_map:
            synonyms = list(synonym_map[kw_lower] - {kw, kw_lower})
            expanded.extend(synonyms[:max_per_keyword])

        # 2. 부분 매칭 (수소연료 → 수소연료전지)
        for key, values in synonym_map.items():
            if key != kw_lower and (kw_lower in key or key in kw_lower):
                synonyms = list(values - {kw, kw_lower})
                expanded.extend(synonyms[:2])  # 부분 매칭은 2개로 제한

    # 중복 제거 (순서 유지)
    seen = set()
    result = []
    for item in expanded:
        item_lower = item.lower()
        if item_lower not in seen:
            seen.add(item_lower)
            result.append(item)

    return result


def es_scout(state: AgentState) -> AgentState:
    """ES Scout 노드 - 동의어 확장 검색 및 doc_ids 수집

    Phase 100: analyzer 직후 실행

    1. 원본 키워드를 동의어 사전으로 확장
    2. ES 검색으로 도메인별 doc_ids 수집
    3. 활성 도메인 결정 (entity_types 업데이트)

    Args:
        state: 현재 에이전트 상태

    Returns:
        업데이트된 상태:
        - keywords: 동의어 포함 키워드
        - synonym_keywords: 추가된 동의어만
        - es_doc_ids: 도메인별 문서 ID
        - domain_hits: 도메인별 히트 수
        - entity_types: 활성 도메인
    """
    query = state.get("query", "")
    keywords = state.get("keywords", [])
    query_type = state.get("query_type", "")
    query_intent = state.get("query_intent", "search")

    print(f"[ES_SCOUT] Phase 100: 시작 - query_type={query_type}, keywords={keywords}")

    # simple 쿼리는 ES Scout 스킵
    if query_type == "simple" or not keywords:
        logger.info("ES Scout 스킵: simple 쿼리 또는 키워드 없음")
        return {
            **state,
            "synonym_keywords": [],
            "es_doc_ids": {},
            "domain_hits": {},
        }

    # 1. 동의어 확장
    expanded_keywords = expand_with_synonyms(keywords)
    synonym_only = [kw for kw in expanded_keywords if kw not in keywords]

    print(f"[ES_SCOUT] Phase 100: 동의어 확장 - 원본={keywords}, 동의어={synonym_only}")
    logger.info(f"Phase 100: 동의어 확장 - 원본={keywords}, 동의어={synonym_only}")

    # 2. ES 검색 (ES_ENABLED 체크)
    es_enabled = os.getenv("ES_ENABLED", "false").lower() == "true"
    if not es_enabled:
        # Phase 104: ES 비활성화 시 기본 entity_types 폴백
        fallback_entity_types = state.get("entity_types") or ["patent", "project"]
        logger.info(f"Phase 104: ES 비활성화 - 기본 entity_types={fallback_entity_types} 사용")
        print(f"[ES_SCOUT] Phase 104: ES 비활성화 - 기본 entity_types={fallback_entity_types} 사용")
        return {
            **state,
            "keywords": expanded_keywords,  # 동의어 포함 키워드로 업데이트
            "synonym_keywords": synonym_only,
            "es_doc_ids": {},
            "domain_hits": {},
            "entity_types": fallback_entity_types,  # Phase 104: 폴백 entity_types
        }

    # Phase 100.2: entity_types 기반 도메인 필터링
    original_entity_types = state.get("entity_types", [])

    # entity_type → ES domain 매핑
    ENTITY_TO_DOMAIN = {
        "patent": "patent",
        "project": "project",
        "equip": "equipment",
        "equipment": "equipment",
        "proposal": "proposal",
    }

    # 3. ES Scout 실행 (기존 함수 재사용)
    try:
        from workflow.nodes.vector_enhancer import _scout_all_domains, _scout_domains

        # Phase 100.3: 원본 키워드 전달 (동의어 확장 전 LLM 핵심 키워드)
        original_keywords = keywords  # 동의어 확장 전 원본

        # Phase 100.2: entity_types가 있으면 해당 도메인만 검색
        if original_entity_types:
            search_domains = [ENTITY_TO_DOMAIN.get(e, e) for e in original_entity_types]
            search_domains = list(set(search_domains))  # 중복 제거
            print(f"[ES_SCOUT] Phase 100.2: entity_types 기반 검색 - domains={search_domains}")
            logger.info(f"Phase 100.2: entity_types 기반 검색 도메인 제한 - {search_domains}")
            # Phase 100.3: original_keywords 추가
            scout_result = _scout_domains(expanded_keywords, query, search_domains, original_keywords=original_keywords)
        else:
            # entity_types 없으면 전체 도메인 검색
            # Phase 100.3: original_keywords 추가
            scout_result = _scout_all_domains(expanded_keywords, query, original_keywords=original_keywords)
    except Exception as e:
        logger.error(f"ES Scout 실행 실패: {e}")
        print(f"[ES_SCOUT] Phase 100: ES Scout 실패 - {e}")
        scout_result = {"hits": {}, "doc_ids": {}}

    # 4. entity_types 업데이트 (활성 도메인만)
    domain_hits = scout_result.get("hits", {})
    es_doc_ids = scout_result.get("doc_ids", {})

    # Phase 100.2: es_doc_ids도 entity_types로 필터링 (이중 안전장치)
    if original_entity_types:
        # domain → entity_type 매핑 (역방향)
        DOMAIN_TO_ENTITY = {
            "patent": "patent",
            "project": "project",
            "equipment": "equip",
            "proposal": "proposal",
        }
        filtered_doc_ids = {}
        filtered_hits = {}
        for domain, doc_ids in es_doc_ids.items():
            entity = DOMAIN_TO_ENTITY.get(domain, domain)
            if entity in original_entity_types:
                filtered_doc_ids[domain] = doc_ids
                filtered_hits[domain] = domain_hits.get(domain, 0)
        es_doc_ids = filtered_doc_ids
        domain_hits = filtered_hits
        print(f"[ES_SCOUT] Phase 100.2: entity_types 필터링 적용 - filtered_domains={list(es_doc_ids.keys())}")

    active_domains = [d for d, count in domain_hits.items() if count > 0]

    # 기존 entity_types가 있으면 유지, 없으면 활성 도메인 사용
    if original_entity_types:
        updated_entity_types = original_entity_types  # Phase 100.2: 원본 entity_types 유지
    else:
        updated_entity_types = active_domains or ["patent"]  # 기본값

    es_doc_counts = {k: len(v) for k, v in es_doc_ids.items()} if es_doc_ids else {}

    print(f"[ES_SCOUT] Phase 100: 완료 - domain_hits={domain_hits}, es_doc_counts={es_doc_counts}")
    logger.info(f"Phase 100: ES Scout 완료 - domain_hits={domain_hits}, entity_types={updated_entity_types}")

    return {
        **state,
        "keywords": expanded_keywords,  # 동의어 포함 키워드로 업데이트
        "synonym_keywords": synonym_only,
        "es_doc_ids": es_doc_ids,
        "domain_hits": domain_hits,
        "entity_types": updated_entity_types,
    }
