"""
스키마 컨텍스트 생성
- LLM에 DB 스키마 정보 제공
- 테이블/컬럼 설명 포맷팅
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import logging
from typing import Dict, List, Optional
from functools import lru_cache

logger = logging.getLogger(__name__)

# 테이블 설명 (한글)
TABLE_DESCRIPTIONS = {
    "f_projects": {
        "description": "연구과제 정보",
        "key_columns": {
            "conts_id": "과제 고유 ID",
            "conts_klang_nm": "과제명 (한글)",
            "tot_rsrh_blgn_amt": "총 연구비 (원)",
            "ancm_yy": "공고 연도",
            "bucl_nm": "사업 분류명",
            "ancm_tl_nm": "공고명"
        },
        "examples": [
            "예산이 가장 큰 과제 → ORDER BY tot_rsrh_blgn_amt DESC",
            "특정 연도 과제 → WHERE ancm_yy = '2024'"
        ]
    },
    "f_patents": {
        "description": "특허 정보",
        "key_columns": {
            "documentid": "특허 문서 ID",
            "conts_klang_nm": "특허 제목 (한글)",
            "objectko": "기술 목적",
            "solutionko": "기술 해결책",
            "ipc_main": "IPC 분류코드"
        },
        "examples": [
            "특허 개수 → SELECT COUNT(*) FROM f_patents",
            "IPC 분류별 → GROUP BY ipc_main"
        ]
    },
    "f_patent_applicants": {
        "description": "특허 출원인 정보",
        "key_columns": {
            "document_id": "특허 문서 ID (FK)",
            "applicant_name": "출원인 이름",
            "applicant_country": "출원인 국가"
        },
        "examples": [
            "출원인별 특허 수 → GROUP BY applicant_name"
        ]
    },
    "f_proposal_profile": {
        "description": "연구제안서 정보",
        "key_columns": {
            "sbjt_id": "제안서 ID",
            "sbjt_nm": "과제명",
            "orgn_nm": "수행기관",
            "dvlp_gole": "개발 목표"
        },
        "examples": [
            "특정 기관 제안서 → WHERE orgn_nm = '기관명'"
        ]
    },
    "f_equipments": {
        "description": "연구장비 정보",
        "key_columns": {
            "conts_id": "장비 ID (PK)",
            "conts_klang_nm": "장비명",
            "equip_mdel_nm": "장비 모델명",
            "equip_spec": "장비 사양/스펙",
            "org_nm": "보유기관명",
            "org_addr": "보유기관 주소",
            "address_dosi": "설치지역 (시/도) - 지역 필터용",
            "kpi_nm_list": "측정 가능한 KPI 목록"
        },
        "examples": [
            "기관별 장비 수 → GROUP BY org_nm",
            "지역별 장비 현황 → GROUP BY address_dosi",
            "특정 KPI 측정 장비 → WHERE kpi_nm_list ILIKE '%KPI명%'"
        ]
    },
    "f_gis": {
        "description": "지리정보 (GIS) - 장비/프로젝트 등과 conts_id로 연결",
        "key_columns": {
            "conts_id": "연계 ID (f_equipments.conts_id 등과 JOIN)",
            "pnu": "필지고유번호 (앞 2자리가 지역코드: 11=서울, 26=부산, 41=경기 등)",
            "x_coord": "X 좌표 (경도)",
            "y_coord": "Y 좌표 (위도)",
            "admin_dong_name": "행정동 이름",
            "legal_dong_name": "법정동 이름",
            "std_new_addr": "도로명 주소"
        },
        "examples": [
            "지역별 분포 → GROUP BY admin_dong_name",
            "경기도 장비 검색 → JOIN f_gis g ON e.conts_id = g.conts_id WHERE g.pnu LIKE '41%'",
            "서울 장비 검색 → WHERE g.pnu LIKE '11%'"
        ]
    },
    # 기획지원 관련 (공고/평가) - Phase 45/99 개선: 평가 내용 포함
    "f_ancm_evalp": {
        "description": "사업공고 배점표/평가기준 정보 (평가지표, 배점 포함)",
        "key_columns": {
            "evalp_id": "평가표 ID",
            "bucl_cd": "사업분류코드",
            "bucl_nm": "사업분류명",
            "eval_idx_nm": "평가항목명 (실제 평가 항목 내용) - 핵심!",
            "eval_score_num": "배점 (숫자) - 핵심!",
            "eval_note": "평가항목 설명",
            "vlid_srt_ymd": "시작일/연도 (최신순 정렬용)",
            "ancm_nm": "연결된 공고명",
            "evalp_tp_se_nm": "평가유형 (정성/정량)"
        },
        "examples": [
            "특정 사업 평가표 → WHERE bucl_nm ILIKE '%사업명%' AND eval_idx_nm IS NOT NULL",
            "평가항목+배점 조회 → SELECT evalp_id, eval_idx_nm, eval_score_num FROM f_ancm_evalp",
            "최신 평가표 → ORDER BY vlid_srt_ymd DESC"
        ]
    },
    "f_ancm_prcnd": {
        "description": "공고 신청조건/자격조건",
        "key_columns": {
            "ancm_id": "공고 ID",
            "prcnd_se_nm": "조건 구분명",
            "prcnd_cn": "조건 내용"
        },
        "examples": [
            "특정 공고 신청조건 → WHERE ancm_id = '공고ID'",
            "여성기업 우대 조건 → WHERE prcnd_cn LIKE '%여성%'"
        ]
    },
    "f_proposal_techclsf": {
        "description": "제안서 기술분류",
        "key_columns": {
            "sbjt_id": "제안서 ID",
            "tecl_cd": "기술분류코드",
            "tecl_nm": "기술분류명"
        },
        "examples": [
            "특정 기술분류 제안서 → WHERE tecl_nm LIKE '%기술명%'"
        ]
    }
}

# 테이블 간 관계
TABLE_RELATIONSHIPS = """
## 테이블 관계
- f_patents ↔ f_patent_applicants: document_id로 연결
- f_proposal_profile ↔ f_proposal_orgn: sbjt_id로 연결
- f_proposal_profile ↔ f_proposal_kpi: sbjt_id로 연결
- f_proposal_profile ↔ f_proposal_techclsf: sbjt_id로 연결
- f_projects ↔ f_gis: conts_id로 연결
- f_ancm_evalp ↔ f_ancm_prcnd: ancm_id로 연결 (공고-평가표-신청조건)
"""

# 엔티티 타입 매핑 (12종 - Phase 19.5 확장)
ENTITY_TYPE_MAPPING = {
    # 주요 엔티티
    "project": ["f_projects"],
    "patent": ["f_patents", "f_patent_applicants"],
    "equip": ["f_equipments"],
    "org": ["f_proposal_orgn", "f_patent_applicants"],
    "applicant": ["f_patent_applicants"],
    "ipc": ["f_patents"],
    "gis": ["f_gis", "f_equipments"],
    "tech": ["f_proposal_techclsf"],
    # 기획지원 관련
    "ancm": ["f_ancm_evalp", "f_ancm_prcnd"],
    "evalp": ["f_ancm_evalp"],
    "proposal": ["f_proposal_profile", "f_proposal_orgn", "f_proposal_kpi", "f_ancm_prcnd"],
    # 분류 체계
    "k12": ["f_proposal_techclsf"],
    "6t": ["f_proposal_techclsf"],
    # 하위 호환성
    "equipment": ["f_equipments"],
    "organization": ["f_proposal_orgn", "f_patent_applicants"]
}

# Phase 34.4: 도메인별 org 매핑
# org 엔티티가 다른 도메인과 함께 사용될 때 적절한 테이블/컬럼 결정
DOMAIN_ORG_MAPPING = {
    # (도메인, org) 조합에 따른 테이블/컬럼 매핑
    "patent": {
        "table": "f_patent_applicants",
        "column": "applicant_name",
        "country_column": "applicant_country",
        "join_table": "f_patents",
        "join_condition": "document_id = documentid",
        "description": "특허 출원인"
    },
    "project": {
        "table": "f_projects",
        "column": "orgn_nm",
        "country_column": None,
        "join_table": None,
        "join_condition": None,
        "description": "연구과제 수행기관"
    },
    "equip": {
        "table": "f_equipments",
        "column": "org_nm",
        "country_column": None,
        "join_table": None,
        "join_condition": None,
        "description": "장비 보유기관"
    },
    "proposal": {
        "table": "f_proposal_profile",
        "column": "orgn_nm",
        "country_column": None,
        "join_table": None,
        "join_condition": None,
        "description": "제안서 수행기관"
    },
}


def get_org_mapping_for_domain(entity_types: List[str]) -> Optional[Dict]:
    """entity_types에서 org와 함께 있는 도메인에 따라 org 테이블/컬럼 결정

    Args:
        entity_types: 엔티티 타입 목록 (예: ["patent", "org"])

    Returns:
        DOMAIN_ORG_MAPPING에서 해당 도메인의 org 정보, 없으면 None
    """
    if "org" not in entity_types:
        return None

    # 우선순위: patent > equip > project > proposal
    priority_order = ["patent", "equip", "project", "proposal"]

    for domain in priority_order:
        if domain in entity_types:
            return DOMAIN_ORG_MAPPING.get(domain)

    # org만 있는 경우 기본값 (특허 출원인)
    return DOMAIN_ORG_MAPPING.get("patent")


def get_schema_context(
    tables: Optional[List[str]] = None,
    include_examples: bool = True,
    include_relationships: bool = True
) -> str:
    """스키마 컨텍스트 생성

    Args:
        tables: 포함할 테이블 목록 (None이면 전체)
        include_examples: 예시 쿼리 포함 여부
        include_relationships: 테이블 관계 포함 여부

    Returns:
        LLM에 전달할 스키마 컨텍스트 문자열
    """
    lines = ["## 데이터베이스 스키마", ""]

    target_tables = tables or list(TABLE_DESCRIPTIONS.keys())

    for table_name in target_tables:
        if table_name not in TABLE_DESCRIPTIONS:
            continue

        info = TABLE_DESCRIPTIONS[table_name]
        lines.append(f"### {table_name}")
        lines.append(f"설명: {info['description']}")
        lines.append("")
        lines.append("주요 컬럼:")

        for col, desc in info["key_columns"].items():
            lines.append(f"  - {col}: {desc}")

        if include_examples and "examples" in info:
            lines.append("")
            lines.append("예시:")
            for ex in info["examples"]:
                lines.append(f"  - {ex}")

        lines.append("")

    if include_relationships:
        lines.append(TABLE_RELATIONSHIPS)

    return "\n".join(lines)


def get_tables_for_entity_types(entity_types: List[str]) -> List[str]:
    """엔티티 타입에 해당하는 테이블 목록 반환

    Args:
        entity_types: 엔티티 타입 목록 ["project", "patent", ...]

    Returns:
        관련 테이블 목록
    """
    tables = set()
    for etype in entity_types:
        if etype in ENTITY_TYPE_MAPPING:
            tables.update(ENTITY_TYPE_MAPPING[etype])
    return list(tables)


def get_compact_schema_context() -> str:
    """간략한 스키마 컨텍스트 (토큰 절약용)"""
    lines = ["## DB 스키마 (주요 테이블)", ""]

    for table_name, info in TABLE_DESCRIPTIONS.items():
        cols = ", ".join(info["key_columns"].keys())
        lines.append(f"- {table_name}: {info['description']} ({cols})")

    return "\n".join(lines)


@lru_cache(maxsize=1)
def get_full_schema_context() -> str:
    """전체 스키마 컨텍스트 (캐싱)"""
    return get_schema_context(
        tables=None,
        include_examples=True,
        include_relationships=True
    )


# 동적 스키마 로드 (DB에서 실시간 조회)
def load_schema_from_db() -> Dict:
    """DB에서 실시간 스키마 정보 로드

    Returns:
        테이블별 컬럼 정보
    """
    try:
        from sql.schema_analyzer import get_schema_analyzer
        analyzer = get_schema_analyzer()

        schema = {}
        for table in analyzer.get_tables():
            info = analyzer.get_table_info(table)
            if info:
                schema[table] = {
                    "description": info.description,
                    "columns": [
                        {"name": c.name, "type": c.data_type}
                        for c in info.columns
                    ],
                    "row_count": info.row_count
                }
        return schema

    except Exception as e:
        logger.error(f"스키마 로드 실패: {e}")
        return {}


def get_dynamic_schema_context(query_hint: str = "") -> str:
    """쿼리 힌트 기반 동적 스키마 컨텍스트

    Args:
        query_hint: 질문에서 추출한 힌트 (테이블 추론용)

    Returns:
        관련 테이블의 스키마 컨텍스트
    """
    # 키워드 기반 테이블 추론
    hint_lower = query_hint.lower()

    relevant_tables = []
    if any(kw in hint_lower for kw in ["과제", "연구", "예산"]):
        relevant_tables.append("f_projects")
    if any(kw in hint_lower for kw in ["특허", "출원", "ipc"]):
        relevant_tables.extend(["f_patents", "f_patent_applicants"])
    if any(kw in hint_lower for kw in ["제안", "제안서"]):
        relevant_tables.append("f_proposal_profile")
    if any(kw in hint_lower for kw in ["장비", "기기"]):
        relevant_tables.append("f_equipments")
    if any(kw in hint_lower for kw in ["위치", "지역", "좌표"]):
        relevant_tables.append("f_gis")
    # 기획지원 관련 키워드 (Phase 19.5 추가)
    if any(kw in hint_lower for kw in ["배점", "배점표", "평가표", "가점", "우대"]):
        relevant_tables.append("f_ancm_evalp")
    if any(kw in hint_lower for kw in ["공고", "사업공고", "신청조건", "자격조건"]):
        relevant_tables.extend(["f_ancm_evalp", "f_ancm_prcnd"])
    if any(kw in hint_lower for kw in ["기술분류", "6t", "k12"]):
        relevant_tables.append("f_proposal_techclsf")

    if not relevant_tables:
        # 기본: 주요 테이블만
        relevant_tables = ["f_projects", "f_patents"]

    # 중복 제거
    relevant_tables = list(dict.fromkeys(relevant_tables))

    return get_schema_context(
        tables=relevant_tables,
        include_examples=True,
        include_relationships=True
    )


if __name__ == "__main__":
    # 테스트
    print("=== 전체 스키마 컨텍스트 ===")
    print(get_full_schema_context())
    print("\n=== 간략한 스키마 ===")
    print(get_compact_schema_context())
    print("\n=== 동적 스키마 (특허 관련) ===")
    print(get_dynamic_schema_context("특허 10개"))
