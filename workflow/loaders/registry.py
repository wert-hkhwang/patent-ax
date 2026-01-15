"""
Loader Registry
===============

query_subtype → Loader 클래스 매핑
- LLM 의도분류 결과를 기반으로 적절한 Loader 선택
- 매핑이 없으면 None 반환 (SQL Agent fallback)

Phase 87: RISE-GPT Loader 시스템 이식
"""

from typing import Optional, Dict, Any, Type, List
import logging

from workflow.loaders.base_loader import BaseLoader

# 구현된 Loader import (존재하는 모듈만)
from workflow.loaders.patent_ranking_loader import (
    PatentRankingLoader,
    PatentCitationLoader,
    PatentInfluenceLoader,
    PatentNationalityLoader,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Loader Registry: query_subtype → Loader 클래스 매핑
# ============================================================================

# Loader 클래스들은 나중에 동적으로 import
# 이 딕셔너리는 매핑 정보만 저장
LOADER_MAPPING = {
    # ===== 특허 순위 =====
    "ranking": "PatentRankingLoader",
    "citation_ranking": "PatentCitationLoader",
    "impact_ranking": "PatentInfluenceLoader",
    "nationality_ranking": "PatentNationalityLoader",

    # ===== 협업 기업 추천 =====
    "collaboration": "CollaborationLoader",
    "collaboration_patent": "CollaborationLoader",
    "collaboration_project": "CollaborationLoader",
    "collaboration_hybrid": "CollaborationLoader",
    "recommendation": "CollaborationLoader",  # Phase 89.7: SearchConfig에서 사용

    # ===== 장비 검색 =====
    "equipment_kpi": "EquipmentKPILoader",
    "equipment_by_name": "EquipmentByNameLoader",
    "equipment_by_org": "EquipmentByOrgLoader",
    "equipment_region": "EquipmentRegionLoader",

    # ===== 사업공고/배점표 =====
    "evalp_score": "AnnouncementScoringLoader",
    "evalp_pref": "AnnouncementAdvantageLoader",
    "pref_task_search": "PreferredAnnouncementLoader",

    # ===== 기술분류 추천 =====
    "tech_classification_6t": "TechClassification6TLoader",
    "tech_classification_industrial": "TechClassificationIndustrialLoader",
    "tech_classification_ntis": "TechClassificationNTISLoader",
    "tech_classification_ksic": "TechClassificationKSICLoader",
    "tech_classification_national": "TechClassificationNationalLoader",
    "tech_classification_10major": "TechClassification10MajorLoader",
    "tech_classification_key": "TechClassificationKeyLoader",
    "tech_classification_ntrm": "TechClassificationNTRMLoader",
    "tech_classification_application": "TechClassificationApplicationLoader",

    # ===== 정부과제 =====
    "project_kpi": "ProjectKPILoader",
    "project_program": "ProjectProgramLoader",
}

# 실제 Loader 인스턴스 캐시
_loader_cache: Dict[str, BaseLoader] = {}


def get_loader(
    query_subtype: str,
    entity_types: Optional[List[str]] = None,
    structured_keywords: Optional[Dict[str, Any]] = None
) -> Optional[BaseLoader]:
    """
    query_subtype에 맞는 Loader 인스턴스 반환

    Args:
        query_subtype: 쿼리 서브타입 (analyzer에서 결정)
        entity_types: 엔티티 타입 리스트 (fallback 매칭용)
        structured_keywords: 구조화된 키워드 (Loader 파라미터 전달용)

    Returns:
        Loader 인스턴스 또는 None (매핑 없을 경우)
    """
    # Phase 91: recommendation subtype에서 entity_types 기반으로 Loader 결정
    # 장비 추천은 CollaborationLoader가 아닌 EquipmentKPILoader 사용
    if query_subtype == "recommendation" and entity_types:
        entity_set = set(entity_types)
        if "equip" in entity_set:
            logger.info(f"Phase 91: recommendation + equip → EquipmentKPILoader 선택")
            loader_name = "EquipmentKPILoader"
            loader = _get_or_create_loader(loader_name, structured_keywords)
            if loader:
                logger.info(f"Loader 선택: {loader_name} (subtype={query_subtype}, entity_types={entity_types})")
            return loader

    # 1. query_subtype으로 직접 매핑
    loader_name = LOADER_MAPPING.get(query_subtype)

    # 2. 매핑이 없으면 entity_types 기반 fallback
    if not loader_name and entity_types:
        loader_name = _get_loader_by_entity(entity_types, query_subtype)

    if not loader_name:
        logger.debug(f"Loader 매핑 없음: subtype={query_subtype}, entity_types={entity_types}")
        return None

    # 3. Loader 인스턴스 생성 (캐시 사용)
    try:
        loader = _get_or_create_loader(loader_name, structured_keywords)
        if loader:
            logger.info(f"Loader 선택: {loader_name} (subtype={query_subtype})")
        return loader
    except Exception as e:
        logger.error(f"Loader 생성 실패: {loader_name} - {e}")
        return None


def _get_loader_by_entity(
    entity_types: List[str],
    query_subtype: str
) -> Optional[str]:
    """
    entity_types 기반 Loader 매핑 (fallback)

    Args:
        entity_types: 엔티티 타입 리스트
        query_subtype: 쿼리 서브타입

    Returns:
        Loader 클래스명 또는 None
    """
    # 엔티티 타입 + subtype 조합으로 매핑
    entity_set = set(entity_types)

    # 특허 관련
    if "patent" in entity_set:
        if query_subtype in ["list", "aggregation"]:
            return "PatentRankingLoader"  # 기본 특허 검색

    # 장비 관련
    if "equip" in entity_set:
        if "org" in entity_set:
            return "EquipmentByNameLoader"  # 장비 + 기관 = 장비명으로 기관 검색
        elif "gis" in entity_set:
            return "EquipmentRegionLoader"  # 장비 + 지역
        else:
            return "EquipmentKPILoader"  # 기본 장비 검색

    # 프로젝트 관련
    if "project" in entity_set:
        if query_subtype == "aggregation":
            return "ProjectKPILoader"

    # 배점표/공고 관련
    if "evalp" in entity_set:
        return "AnnouncementScoringLoader"

    return None


def _get_or_create_loader(
    loader_name: str,
    structured_keywords: Optional[Dict[str, Any]] = None
) -> Optional[BaseLoader]:
    """
    Loader 인스턴스 생성 또는 캐시에서 반환

    Args:
        loader_name: Loader 클래스명
        structured_keywords: 구조화된 키워드

    Returns:
        Loader 인스턴스 또는 None
    """
    # 현재는 구현된 Loader만 반환
    # 추후 Loader 구현 시 여기서 동적 import

    # 구현된 Loader 매핑 (존재하는 모듈만)
    implemented_loaders = {
        # 특허 순위
        "PatentRankingLoader": PatentRankingLoader,
        "PatentCitationLoader": PatentCitationLoader,
        "PatentInfluenceLoader": PatentInfluenceLoader,
        "PatentNationalityLoader": PatentNationalityLoader,
    }

    loader_class = implemented_loaders.get(loader_name)
    if loader_class:
        # 캐시에서 확인
        cache_key = f"{loader_name}_{hash(str(structured_keywords))}"
        if cache_key not in _loader_cache:
            _loader_cache[cache_key] = loader_class()
        return _loader_cache[cache_key]

    # 미구현 Loader는 로그만 남기고 None 반환 (SQL Agent fallback)
    logger.info(f"Loader 미구현: {loader_name} → SQL Agent fallback")
    return None


def list_available_loaders() -> Dict[str, str]:
    """
    사용 가능한 모든 Loader 매핑 반환

    Returns:
        {subtype: loader_name} 딕셔너리
    """
    return LOADER_MAPPING.copy()


def is_loader_available(query_subtype: str) -> bool:
    """
    특정 subtype에 대한 Loader 존재 여부 확인

    Args:
        query_subtype: 쿼리 서브타입

    Returns:
        Loader 존재 여부
    """
    return query_subtype in LOADER_MAPPING


def get_loader_class(loader_name: str) -> Optional[Type[BaseLoader]]:
    """
    Phase 89.7: Loader 클래스명으로 클래스 반환

    Args:
        loader_name: Loader 클래스명 (예: "CollaborationLoader")

    Returns:
        Loader 클래스 또는 None
    """
    implemented_loaders = {
        # 특허 순위 (존재하는 모듈만)
        "PatentRankingLoader": PatentRankingLoader,
        "PatentCitationLoader": PatentCitationLoader,
        "PatentInfluenceLoader": PatentInfluenceLoader,
        "PatentNationalityLoader": PatentNationalityLoader,
    }
    return implemented_loaders.get(loader_name)


# ============================================================================
# Loader Registry 초기화
# ============================================================================

# 모듈 로드 시 Registry 정보 로깅
logger.info(f"Loader Registry 초기화: {len(LOADER_MAPPING)}개 subtype 매핑")
