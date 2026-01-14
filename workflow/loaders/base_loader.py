"""
Base Table Loader
==================

모든 테이블 로더의 추상 클래스
- DB-First 원칙: 항상 DB에서 먼저 검색
- 템플릿은 포맷팅만 담당, 데이터 생성 금지
- 표준화된 인터페이스 제공

RISE-GPT v2에서 이식
작성일: 2025-12-12
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple
import logging
import os

logger = logging.getLogger(__name__)


class BaseLoader(ABC):
    """
    모든 테이블 로더의 추상 클래스

    DB-First 원칙:
    1. 항상 DB에서 실제 데이터 검색
    2. 검색된 데이터를 마크다운 테이블로 포맷팅
    3. DB에 데이터 없을 경우에만 fallback 메시지 반환
    4. LLM으로 임의 데이터 생성 절대 금지

    서브클래스 구현 필수:
    - load_data(): DB에서 데이터 로드
    - format_markdown(): 마크다운 테이블 포맷팅
    """

    def __init__(self):
        """초기화"""
        # Phase 88: 기존 SQL Agent와 동일한 환경변수 사용 (DB_HOST 등)
        self.pg_config = {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': int(os.getenv('DB_PORT', 5432)),
            'database': os.getenv('DB_NAME', 'ax'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASSWORD', 'postgres')
        }
        self.table_name = None  # 서브클래스에서 설정
        self.loader_name = self.__class__.__name__
        self.last_query = None  # 마지막으로 실행된 SQL 쿼리

    async def get_connection(self):
        """
        PostgreSQL 연결 생성

        Returns:
            asyncpg.Connection
        """
        import asyncpg
        dsn = (
            f"postgresql://{self.pg_config['user']}:{self.pg_config['password']}@"
            f"{self.pg_config['host']}:{self.pg_config['port']}/{self.pg_config['database']}"
        )
        return await asyncpg.connect(dsn, timeout=10)

    async def execute_query(
        self,
        query: str,
        params: Optional[List[Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        SQL 쿼리 실행

        Args:
            query: SQL 쿼리 문자열
            params: 쿼리 파라미터

        Returns:
            결과 레코드 리스트
        """
        self.last_query = query  # 실행 쿼리 기록
        try:
            conn = await self.get_connection()
            try:
                if params:
                    rows = await conn.fetch(query, *params)
                else:
                    rows = await conn.fetch(query)

                # Record → Dict 변환
                return [dict(row) for row in rows]

            finally:
                await conn.close()

        except Exception as e:
            logger.error(f"쿼리 실행 실패: {e}")
            logger.error(f"쿼리: {query}")
            raise

    async def execute_count_query(
        self,
        count_query: str,
        params: Optional[List[Any]] = None
    ) -> int:
        """
        공통 COUNT 쿼리 실행 메서드

        Args:
            count_query: COUNT 쿼리 문자열
            params: 쿼리 파라미터

        Returns:
            총 결과 개수 (int)
        """
        try:
            conn = await self.get_connection()
            try:
                if params:
                    result = await conn.fetchval(count_query, *params)
                else:
                    result = await conn.fetchval(count_query)

                total_count = int(result) if result is not None else 0
                logger.debug(f"{self.loader_name} COUNT 쿼리 결과: {total_count:,}개")
                return total_count

            finally:
                await conn.close()

        except Exception as e:
            logger.warning(f"{self.loader_name} COUNT 쿼리 실패: {e}")
            return 0

    @abstractmethod
    async def load_data(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        DB에서 데이터 로드 (서브클래스 구현 필수)

        Args:
            context: 로드 컨텍스트 (query, filters, limit 등)

        Returns:
            DB 레코드 리스트
        """
        pass

    @abstractmethod
    def format_markdown(
        self,
        data: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        마크다운 테이블 포맷팅 (서브클래스 구현 필수)

        Args:
            data: DB에서 로드한 데이터
            context: 포맷팅 컨텍스트 (제목, 추가 정보 등)

        Returns:
            마크다운 형식 테이블
        """
        pass

    async def load(
        self,
        query: str,
        keywords: List[str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        테이블 생성 (전체 파이프라인)

        1. DB에서 데이터 로드
        2. 마크다운 포맷팅
        3. 메타데이터 생성
        4. GIS 데이터 추출 (가능한 경우)

        Args:
            query: 원본 사용자 질의
            keywords: 추출된 키워드
            context: 생성 컨텍스트

        Returns:
            {
                "markdown": str,           # 마크다운 테이블
                "data": List[Dict],        # 원본 데이터
                "columns": List[str],      # 컬럼명
                "gis_data": List[Dict],    # GIS 좌표 데이터
                "metadata": Dict,          # 메타데이터
                "total_count": int,        # 총 결과 수
            }
        """
        try:
            # 컨텍스트에 원본 쿼리와 키워드 추가
            context["original_query"] = query
            context["keywords"] = keywords

            # 1. DB에서 데이터 로드 (최우선)
            data = await self.load_data(context)

            if data:
                logger.info(f"{self.loader_name}: {len(data)}개 레코드 로드 성공")

                # 2. 마크다운 포맷팅
                markdown = self.format_markdown(data, context)

                # 3. GIS 데이터 추출
                gis_data = self._extract_gis_data(data)

                # 4. 컬럼명 추출
                columns = list(data[0].keys()) if data else []

                # 5. 메타데이터 생성
                metadata = {
                    "loader": self.loader_name,
                    "result_count": len(data),
                    "query_executed": self.last_query,
                    "context": {
                        k: v for k, v in context.items()
                        if k not in ["original_query"]  # 중복 제거
                    }
                }

                return {
                    "markdown": markdown,
                    "data": data,
                    "columns": columns,
                    "gis_data": gis_data,
                    "metadata": metadata,
                    "total_count": len(data),
                }
            else:
                logger.warning(f"{self.loader_name}: DB에 데이터 없음")
                return {
                    "markdown": self._generate_fallback_message(context),
                    "data": [],
                    "columns": [],
                    "gis_data": [],
                    "metadata": {"loader": self.loader_name, "result_count": 0},
                    "total_count": 0,
                }

        except Exception as e:
            logger.error(f"{self.loader_name} 오류: {e}")
            return {
                "markdown": self._generate_error_message(str(e)),
                "data": [],
                "columns": [],
                "gis_data": [],
                "metadata": {"loader": self.loader_name, "error": str(e)},
                "total_count": 0,
            }

    def _extract_gis_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        GIS 좌표 데이터 추출

        Args:
            data: DB 레코드 리스트

        Returns:
            GIS 데이터 리스트 (위도, 경도, 이름 등)
        """
        gis_data = []
        for row in data:
            # 일반적인 좌표 컬럼명 체크
            lat = row.get("latitude") or row.get("lat") or row.get("위도")
            lon = row.get("longitude") or row.get("lng") or row.get("lon") or row.get("경도")

            if lat and lon:
                try:
                    gis_data.append({
                        "lat": float(lat),
                        "lng": float(lon),
                        "name": row.get("name") or row.get("기관명") or row.get("org_name") or "",
                        "address": row.get("address") or row.get("주소") or "",
                        "data": row  # 전체 데이터 포함
                    })
                except (ValueError, TypeError):
                    continue

        return gis_data

    def _generate_fallback_message(
        self,
        context: Dict[str, Any]
    ) -> str:
        """
        DB에 데이터가 없을 경우 fallback 메시지

        Args:
            context: 컨텍스트

        Returns:
            fallback 메시지 (마크다운)
        """
        lines = []
        lines.append("### 데이터 없음")
        lines.append("")
        lines.append(f"- **{self.loader_name}**: DB에서 요청하신 데이터를 찾을 수 없습니다.")
        lines.append("- 검색 조건을 변경하거나 다른 키워드로 시도해주세요.")
        lines.append("")

        return "\n".join(lines)

    def _generate_error_message(self, error: str) -> str:
        """
        오류 메시지 생성

        Args:
            error: 오류 내용

        Returns:
            오류 메시지 (마크다운)
        """
        lines = []
        lines.append("### 오류 발생")
        lines.append("")
        lines.append(f"- **{self.loader_name}**: 데이터 로드 중 오류가 발생했습니다.")
        lines.append(f"- 오류 내용: {error}")
        lines.append("")

        return "\n".join(lines)

    def _safe_get(
        self,
        record: Dict[str, Any],
        key: str,
        default: Any = None
    ) -> Any:
        """
        안전한 딕셔너리 값 추출

        Args:
            record: 레코드
            key: 키
            default: 기본값

        Returns:
            값 또는 기본값
        """
        value = record.get(key, default)

        # None이나 빈 문자열이면 기본값 반환
        if value is None or (isinstance(value, str) and not value.strip()):
            return default

        return value

    def _format_number(self, value: Any, decimal_places: int = 0) -> str:
        """
        숫자 포맷팅 (천 단위 콤마)

        Args:
            value: 숫자 값
            decimal_places: 소수점 자릿수

        Returns:
            포맷팅된 문자열
        """
        try:
            if isinstance(value, (int, float)):
                if decimal_places > 0:
                    return f"{value:,.{decimal_places}f}"
                else:
                    return f"{int(value):,}"
            return str(value)
        except:
            return str(value)

    def _format_percentage(self, value: Any, decimal_places: int = 1) -> str:
        """
        퍼센트 포맷팅

        Args:
            value: 숫자 값 (0-100 또는 0-1)
            decimal_places: 소수점 자릿수

        Returns:
            포맷팅된 퍼센트 문자열
        """
        try:
            num = float(value)
            # 0-1 범위면 100 곱하기
            if 0 <= num <= 1:
                num *= 100
            return f"{num:.{decimal_places}f}%"
        except:
            return str(value)


# ============================================================================
# 헬퍼 함수
# ============================================================================

def create_markdown_table(
    headers: List[str],
    rows: List[List[Any]],
    alignments: Optional[List[str]] = None
) -> str:
    """
    마크다운 테이블 생성 (재사용 가능한 유틸리티)

    Args:
        headers: 헤더 리스트
        rows: 데이터 행 리스트
        alignments: 정렬 (left, center, right)

    Returns:
        마크다운 테이블
    """
    if not headers or not rows:
        return ""

    def escape_table_cell(cell: Any) -> str:
        """
        테이블 셀 내용을 안전하게 이스케이프
        - 파이프 문자(|)를 &#124;로 변경
        - 줄바꿈 문자를 <br>로 변경
        """
        cell_str = str(cell) if cell is not None else ""
        # 파이프 문자를 HTML 엔티티로 변경
        cell_str = cell_str.replace("|", "&#124;")
        # 줄바꿈을 <br>로 변경
        cell_str = cell_str.replace("\n", "<br>")
        return cell_str

    lines = []

    # 헤더 (헤더도 이스케이프 적용)
    escaped_headers = [escape_table_cell(h) for h in headers]
    lines.append("| " + " | ".join(escaped_headers) + " |")

    # 구분선
    if alignments:
        separators = []
        for align in alignments:
            if align == "center":
                separators.append(":---:")
            elif align == "right":
                separators.append("---:")
            else:
                separators.append("---")
        lines.append("| " + " | ".join(separators) + " |")
    else:
        lines.append("| " + " | ".join("---" for _ in headers) + " |")

    # 데이터 행 (모든 셀에 이스케이프 적용)
    for row in rows:
        escaped_row = [escape_table_cell(cell) for cell in row]
        lines.append("| " + " | ".join(escaped_row) + " |")

    return "\n".join(lines)
