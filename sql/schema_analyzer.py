"""
DB 스키마 분석기
- PostgreSQL ax 데이터베이스 스키마 추출
- 테이블/컬럼 정보 캐싱
- LLM 컨텍스트용 스키마 포맷팅
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import json
from sql.db_connector import get_db_connection

logger = logging.getLogger(__name__)


@dataclass
class ColumnInfo:
    """컬럼 정보"""
    name: str
    data_type: str
    max_length: Optional[int] = None
    is_nullable: bool = True
    description: str = ""


@dataclass
class TableInfo:
    """테이블 정보"""
    name: str
    columns: List[ColumnInfo] = field(default_factory=list)
    row_count: int = 0
    description: str = ""
    sample_values: Dict[str, List[Any]] = field(default_factory=dict)


class SchemaAnalyzer:
    """DB 스키마 분석기"""

    # 주요 테이블 설명 (한글)
    TABLE_DESCRIPTIONS = {
        "f_patents": "특허 정보 (특허명, IPC 코드, 문제점, 해결책)",
        "f_patent_applicants": "특허 출원인/기관 정보",
        "f_applicant_address": "출원인 주소 및 사업자등록번호",
        "f_proposal_profile": "연구제안서 기본 정보 (제안명, 기관, 개발목표)",
        "f_proposal_orgn": "제안서 참여 기관",
        "f_proposal_kpi": "제안서 성과지표(KPI)",
        "f_proposal_techclsf": "제안서 기술분류",
        "f_projects": "연구과제 정보 (과제명, 예산, 기간)",
        "f_equipments": "연구장비 정보",
        "f_gis": "지리정보 (좌표, 행정동)",
        "f_ancm_evalp": "공고 평가 점수",
        "f_ancm_prcnd": "공고 조건/자격",
        "f_kpi": "KPI 데이터",
        "patent_ipc_normalized": "정규화된 IPC 코드",
        "patent_inventor_normalized": "정규화된 발명자 정보",
        "equipment_kpi_normalized": "정규화된 장비 KPI",
        "master_organization": "기관 마스터",
        "master_inventor": "발명자 마스터",
        "master_ipc": "IPC 코드 마스터",
        # 엣지 테이블
        "edge_patent_applicant": "특허-출원인 관계",
        "edge_patent_inventor": "특허-발명자 관계",
        "edge_patent_ipc": "특허-IPC 관계",
        "edge_proposal_project": "제안서-과제 관계",
        "edge_proposal_kpi": "제안서-KPI 관계",
        "edge_proposal_techclass": "제안서-기술분류 관계",
        "edge_proposal_evalp": "제안서-평가 관계",
        "edge_org_proposal": "기관-제안서 관계",
        "edge_org_collaboration": "기관 협력 관계",
        "edge_equipment_gis": "장비-지역 관계",
    }

    # 주요 컬럼 설명 (한글)
    COLUMN_DESCRIPTIONS = {
        # 공통
        "conts_id": "콘텐츠/과제 ID",
        "conts_klang_nm": "한글 명칭",
        "org_nm": "기관명",
        "org_busir_no": "사업자등록번호",
        "org_corp_no": "법인등록번호",
        "ancm_id": "공고 ID",
        "ancm_yy": "공고 연도",
        "ancm_tl_nm": "공고명",
        # 특허
        "documentid": "특허 문서 ID",
        "ipc_main": "주요 IPC 코드",
        "ipc_all": "전체 IPC 코드",
        "objectko": "해결하려는 문제",
        "solutionko": "해결 방법",
        "ptnaplc_ymd": "출원일",
        "patent_rgstn_ymd": "등록일",
        # 제안서
        "sbjt_id": "제안서/과제 ID",
        "sbjt_nm": "제안서명",
        "orgn_id": "기관 ID",
        "orgn_nm": "기관명",
        "dvlp_gole": "개발 목표",
        "rhdp_whol_cn": "연구 내용",
        "busir_no": "사업자등록번호",
        "corp_no": "법인등록번호",
        # 과제
        "rsrh_bgnv_ymd": "연구 시작일",
        "rsrh_endv_ymd": "연구 종료일",
        "tot_rsrh_blgn_amt": "총 연구비",
        "govn_splm_amt": "정부 지원금",
        "bnfn_splm_amt": "수혜기관 부담금",
        "cmpn_splm_amt": "기업 부담금",
        # 장비
        "equip_grp_lv1_nm": "장비 대분류",
        "equip_grp_lv2_nm": "장비 중분류",
        "equip_grp_lv3_nm": "장비 소분류",
        "kpi_nm_list": "KPI 목록",
        # GIS
        "x_coord": "경도 (longitude)",
        "y_coord": "위도 (latitude)",
        "admin_dong_name": "행정동명",
        "legal_dong_name": "법정동명",
        "region_code": "지역 코드",
    }

    def __init__(self, cache_enabled: bool = True):
        self.cache_enabled = cache_enabled
        self._schema_cache: Dict[str, TableInfo] = {}
        self._tables_loaded = False

    def get_tables(self) -> List[str]:
        """테이블 목록 조회"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()
            return tables
        except Exception as e:
            logger.error(f"테이블 목록 조회 실패: {e}")
            return []

    def get_table_info(self, table_name: str, include_samples: bool = False) -> Optional[TableInfo]:
        """테이블 상세 정보 조회"""
        # 캐시 확인
        if self.cache_enabled and table_name in self._schema_cache:
            return self._schema_cache[table_name]

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # 컬럼 정보 조회 (PostgreSQL)
            cursor.execute("""
                SELECT
                    column_name,
                    data_type,
                    character_maximum_length,
                    is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                ORDER BY ordinal_position
            """, (table_name,))

            columns = []
            for row in cursor.fetchall():
                col = ColumnInfo(
                    name=row[0],
                    data_type=row[1],
                    max_length=row[2],
                    is_nullable=(row[3] == 'YES'),
                    description=self.COLUMN_DESCRIPTIONS.get(row[0], "")
                )
                columns.append(col)

            if not columns:
                conn.close()
                return None

            # 행 수 조회 (PostgreSQL)
            cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
            row_count = cursor.fetchone()[0]

            # 샘플 값 조회 (선택적)
            sample_values = {}
            if include_samples and columns:
                sample_cols = [c.name for c in columns[:5]]  # 처음 5개 컬럼만
                col_list = ", ".join([f'"{c}"' for c in sample_cols])
                cursor.execute(f'SELECT {col_list} FROM "{table_name}" LIMIT 3')
                rows = cursor.fetchall()
                for i, col_name in enumerate(sample_cols):
                    sample_values[col_name] = [row[i] for row in rows if row[i] is not None]

            conn.close()

            table_info = TableInfo(
                name=table_name,
                columns=columns,
                row_count=row_count,
                description=self.TABLE_DESCRIPTIONS.get(table_name, ""),
                sample_values=sample_values
            )

            # 캐시 저장
            if self.cache_enabled:
                self._schema_cache[table_name] = table_info

            return table_info

        except Exception as e:
            logger.error(f"테이블 정보 조회 실패 [{table_name}]: {e}")
            return None

    def get_full_schema(self, include_samples: bool = False) -> Dict[str, TableInfo]:
        """전체 스키마 조회"""
        if self._tables_loaded and self.cache_enabled:
            return self._schema_cache

        tables = self.get_tables()
        schema = {}

        for table_name in tables:
            table_info = self.get_table_info(table_name, include_samples)
            if table_info:
                schema[table_name] = table_info

        self._tables_loaded = True
        return schema

    def format_schema_for_llm(self, tables: Optional[List[str]] = None) -> str:
        """LLM 컨텍스트용 스키마 포맷팅"""
        if tables:
            schema = {t: self.get_table_info(t) for t in tables if self.get_table_info(t)}
        else:
            schema = self.get_full_schema()

        lines = ["## R&D 데이터베이스 스키마\n"]

        for table_name, table_info in schema.items():
            if not table_info:
                continue

            # 테이블 헤더
            desc = table_info.description or ""
            lines.append(f"### {table_name}")
            if desc:
                lines.append(f"설명: {desc}")
            lines.append(f"행 수: {table_info.row_count:,}")
            lines.append("")

            # 컬럼 정보
            lines.append("| 컬럼명 | 타입 | 설명 |")
            lines.append("|--------|------|------|")
            for col in table_info.columns:
                dtype = col.data_type
                if col.max_length and col.max_length > 0:
                    dtype = f"{col.data_type}({col.max_length})"
                desc = col.description or ""
                lines.append(f"| {col.name} | {dtype} | {desc} |")
            lines.append("")

        return "\n".join(lines)

    def format_compact_schema(self, tables: Optional[List[str]] = None) -> str:
        """컴팩트한 스키마 포맷 (토큰 절약)"""
        if tables:
            schema = {t: self.get_table_info(t) for t in tables if self.get_table_info(t)}
        else:
            schema = self.get_full_schema()

        lines = []
        for table_name, table_info in schema.items():
            if not table_info:
                continue

            cols = ", ".join([f"{c.name}:{c.data_type}" for c in table_info.columns])
            desc = f" -- {table_info.description}" if table_info.description else ""
            lines.append(f"{table_name}({cols}){desc}")

        return "\n".join(lines)

    def get_related_tables(self, query: str) -> List[str]:
        """쿼리와 관련된 테이블 추천"""
        query_lower = query.lower()
        related = []

        # 키워드 기반 테이블 매칭
        keyword_table_map = {
            ("특허", "patent", "ipc", "발명"): ["f_patents", "f_patent_applicants", "f_applicant_address", "patent_ipc_normalized"],
            ("제안", "proposal", "연구", "개발"): ["f_proposal_profile", "f_proposal_orgn", "f_proposal_kpi", "f_proposal_techclsf"],
            ("과제", "project", "프로젝트"): ["f_projects"],
            ("장비", "equipment", "기기"): ["f_equipments", "equipment_kpi_normalized"],
            ("지역", "위치", "좌표", "gis", "지도"): ["f_gis"],
            ("공고", "ancm", "모집"): ["f_ancm_evalp", "f_ancm_prcnd"],
            ("kpi", "성과", "지표"): ["f_kpi", "f_proposal_kpi", "equipment_kpi_normalized"],
            ("기관", "organization", "org", "회사", "대학"): ["f_proposal_orgn", "f_patent_applicants", "master_organization"],
        }

        for keywords, tables in keyword_table_map.items():
            if any(kw in query_lower for kw in keywords):
                for t in tables:
                    if t not in related:
                        related.append(t)

        # 기본 테이블 (아무것도 매칭되지 않으면)
        if not related:
            related = ["f_projects", "f_proposal_profile", "f_patents"]

        return related

    def clear_cache(self):
        """캐시 초기화"""
        self._schema_cache.clear()
        self._tables_loaded = False

    def search_program_by_name(self, program_name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """사업명/공고명으로 검색

        Args:
            program_name: 검색할 사업명 (부분 일치)
            limit: 최대 결과 수

        Returns:
            매칭된 공고/사업 목록
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # 공고 테이블에서 검색
            cursor.execute("""
                SELECT DISTINCT ancm_id, ancm_tl_nm, ancm_yy
                FROM f_ancm_evalp
                WHERE ancm_tl_nm ILIKE %s
                ORDER BY ancm_yy DESC
                LIMIT %s
            """, (f"%{program_name}%", limit))

            results = []
            for row in cursor.fetchall():
                results.append({
                    "ancm_id": row[0],
                    "ancm_tl_nm": row[1],
                    "ancm_yy": row[2],
                    "source": "f_ancm_evalp"
                })

            # 제안서 테이블에서도 검색
            cursor.execute("""
                SELECT DISTINCT sbjt_id, sbjt_nm
                FROM f_proposal_profile
                WHERE sbjt_nm ILIKE %s
                LIMIT %s
            """, (f"%{program_name}%", limit))

            for row in cursor.fetchall():
                results.append({
                    "sbjt_id": row[0],
                    "sbjt_nm": row[1],
                    "source": "f_proposal_profile"
                })

            conn.close()
            return results

        except Exception as e:
            logger.error(f"사업명 검색 실패 [{program_name}]: {e}")
            return []

    def search_equipment_by_name(self, equipment_name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """장비명으로 검색 및 보유 기관 조회

        Args:
            equipment_name: 검색할 장비명 (부분 일치)
            limit: 최대 결과 수

        Returns:
            매칭된 장비 및 기관 정보
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT conts_id, conts_klang_nm, org_nm,
                       equip_grp_lv1_nm, equip_grp_lv2_nm, equip_grp_lv3_nm
                FROM f_equipments
                WHERE conts_klang_nm ILIKE %s
                ORDER BY org_nm
                LIMIT %s
            """, (f"%{equipment_name}%", limit))

            results = []
            for row in cursor.fetchall():
                results.append({
                    "conts_id": row[0],
                    "equipment_name": row[1],
                    "org_nm": row[2],
                    "category_lv1": row[3],
                    "category_lv2": row[4],
                    "category_lv3": row[5]
                })

            conn.close()
            return results

        except Exception as e:
            logger.error(f"장비 검색 실패 [{equipment_name}]: {e}")
            return []

    def get_preference_conditions(self, ancm_id: str = None, preference_type: str = None) -> List[Dict[str, Any]]:
        """우대/가점 조건 조회

        Args:
            ancm_id: 공고 ID (선택)
            preference_type: 우대 유형 (여성기업, 중소기업 등)

        Returns:
            우대/가점 조건 목록
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            query = """
                SELECT ancm_id, prcnd_se_nm, prcnd_cn
                FROM f_ancm_prcnd
                WHERE 1=1
            """
            params = []

            if ancm_id:
                query += " AND ancm_id = %s"
                params.append(ancm_id)

            if preference_type:
                query += " AND (prcnd_cn ILIKE %s OR prcnd_se_nm ILIKE %s)"
                params.extend([f"%{preference_type}%", f"%{preference_type}%"])

            query += " LIMIT 50"

            cursor.execute(query, params)

            results = []
            for row in cursor.fetchall():
                results.append({
                    "ancm_id": row[0],
                    "condition_type": row[1],
                    "condition_content": row[2]
                })

            conn.close()
            return results

        except Exception as e:
            logger.error(f"우대조건 조회 실패: {e}")
            return []


# 싱글톤 인스턴스
_schema_analyzer: Optional[SchemaAnalyzer] = None


def get_schema_analyzer() -> SchemaAnalyzer:
    """스키마 분석기 싱글톤"""
    global _schema_analyzer
    if _schema_analyzer is None:
        _schema_analyzer = SchemaAnalyzer()
    return _schema_analyzer


if __name__ == "__main__":
    print("스키마 분석기 테스트")

    analyzer = get_schema_analyzer()

    # 1. 테이블 목록
    print("\n1. 테이블 목록:")
    tables = analyzer.get_tables()
    for t in tables[:10]:
        print(f"   - {t}")
    print(f"   ... 총 {len(tables)}개")

    # 2. 테이블 상세 정보
    print("\n2. f_projects 테이블 정보:")
    info = analyzer.get_table_info("f_projects", include_samples=True)
    if info:
        print(f"   설명: {info.description}")
        print(f"   행 수: {info.row_count:,}")
        print(f"   컬럼 수: {len(info.columns)}")
        print("   주요 컬럼:")
        for col in info.columns[:5]:
            print(f"     - {col.name} ({col.data_type}): {col.description}")

    # 3. 관련 테이블 추천
    print("\n3. 관련 테이블 추천 ('인공지능 특허'):")
    related = analyzer.get_related_tables("인공지능 특허")
    for t in related:
        print(f"   - {t}")

    # 4. LLM용 스키마 포맷
    print("\n4. LLM용 스키마 (컴팩트):")
    compact = analyzer.format_compact_schema(tables=["f_projects", "f_patents"])
    print(compact[:500] + "...")
