"""
SQL 에이전트
- 자연어 → SQL 변환
- SQL 실행 및 결과 반환
- 안전한 쿼리 검증
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import logging
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

from sql.db_connector import get_db_connection
from sql.schema_analyzer import get_schema_analyzer, SchemaAnalyzer
from sql.sql_prompts import (
    build_sql_generation_prompt,
    build_result_interpretation_prompt,
    format_query_result
)
from llm.llm_client import get_llm_client, LLMClient

logger = logging.getLogger(__name__)


@dataclass
class SQLResult:
    """SQL 실행 결과"""
    success: bool
    columns: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)
    row_count: int = 0
    error: Optional[str] = None
    execution_time_ms: float = 0


@dataclass
class SQLAgentResponse:
    """SQL 에이전트 응답"""
    question: str
    generated_sql: str
    result: SQLResult
    interpretation: Optional[str] = None
    related_tables: List[str] = field(default_factory=list)
    elapsed_ms: float = 0


class SQLAgent:
    """SQL 에이전트 - 자연어 → SQL 변환 및 실행"""

    # 위험한 SQL 키워드
    DANGEROUS_KEYWORDS = [
        r'\bDROP\b', r'\bDELETE\b', r'\bUPDATE\b', r'\bINSERT\b',
        r'\bTRUNCATE\b', r'\bALTER\b', r'\bCREATE\b', r'\bGRANT\b',
        r'\bREVOKE\b', r'\bEXEC\b', r'\bEXECUTE\b', r'\bxp_',
        r'\bsp_', r'--', r'/\*', r'\*/'
    ]

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        schema_analyzer: Optional[SchemaAnalyzer] = None,
        max_rows: int = 1000,
        timeout: int = 30
    ):
        self.llm = llm_client or get_llm_client()
        self.schema_analyzer = schema_analyzer or get_schema_analyzer()
        self.max_rows = max_rows
        self.timeout = timeout

    def query(
        self,
        question: str,
        interpret_result: bool = True,
        max_tokens: int = 1024,
        temperature: float = 0.3,
        sql_hints: Optional[str] = None
    ) -> SQLAgentResponse:
        """자연어 질문으로 SQL 쿼리 실행

        Args:
            question: 자연어 질문
            interpret_result: 결과 해석 여부
            max_tokens: LLM 최대 토큰
            temperature: LLM 온도
            sql_hints: 벡터 검색 기반 SQL 힌트 (선택적)

        Returns:
            SQLAgentResponse
        """
        start_time = time.time()

        # 1. 관련 테이블 추론
        related_tables = self.schema_analyzer.get_related_tables(question)
        logger.info(f"관련 테이블: {related_tables}")

        # 2. 스키마 컨텍스트 생성
        schema_context = self.schema_analyzer.format_schema_for_llm(tables=related_tables)

        # 3. SQL 생성 (벡터 힌트 포함)
        generated_sql = self._generate_sql(
            question=question,
            schema=schema_context,
            max_tokens=max_tokens,
            temperature=temperature,
            sql_hints=sql_hints
        )
        logger.info(f"생성된 SQL: {generated_sql[:200]}...")

        # 4. SQL 검증
        is_safe, error_msg = self._validate_sql(generated_sql)
        if not is_safe:
            return SQLAgentResponse(
                question=question,
                generated_sql=generated_sql,
                result=SQLResult(success=False, error=f"안전하지 않은 SQL: {error_msg}"),
                related_tables=related_tables,
                elapsed_ms=(time.time() - start_time) * 1000
            )

        # 5. SQL 실행
        result = self._execute_sql(generated_sql)

        # 6. 결과 해석 (선택적)
        interpretation = None
        if interpret_result and result.success and result.rows:
            interpretation = self._interpret_result(
                question=question,
                sql=generated_sql,
                columns=result.columns,
                rows=result.rows,
                max_tokens=max_tokens,
                temperature=temperature
            )

        elapsed_ms = (time.time() - start_time) * 1000

        return SQLAgentResponse(
            question=question,
            generated_sql=generated_sql,
            result=result,
            interpretation=interpretation,
            related_tables=related_tables,
            elapsed_ms=round(elapsed_ms, 2)
        )

    def execute_raw(self, sql: str) -> SQLResult:
        """직접 SQL 실행 (검증 후)

        Args:
            sql: SQL 쿼리

        Returns:
            SQLResult
        """
        # 검증
        is_safe, error_msg = self._validate_sql(sql)
        if not is_safe:
            return SQLResult(success=False, error=f"안전하지 않은 SQL: {error_msg}")

        return self._execute_sql(sql)

    def _generate_sql(
        self,
        question: str,
        schema: str,
        max_tokens: int = 1024,
        temperature: float = 0.3,
        sql_hints: Optional[str] = None
    ) -> str:
        """LLM으로 SQL 생성"""
        system_prompt, user_prompt = build_sql_generation_prompt(question, schema, sql_hints)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        response = self.llm.chat(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature
        )

        sql = response.get("choices", [{}])[0].get("message", {}).get("content", "")

        # SQL 정리 (코드 블록 제거)
        sql = self._clean_sql(sql)

        return sql

    def _clean_sql(self, sql: str) -> str:
        """SQL 정리 (마크다운 코드 블록 제거 등)"""
        # 마크다운 코드 블록 제거
        sql = re.sub(r'```sql\s*', '', sql, flags=re.IGNORECASE)
        sql = re.sub(r'```\s*', '', sql)

        # 앞뒤 공백 제거
        sql = sql.strip()

        # 여러 줄 정리
        lines = [line.strip() for line in sql.split('\n') if line.strip()]
        sql = ' '.join(lines)

        return sql

    def _validate_sql(self, sql: str) -> Tuple[bool, Optional[str]]:
        """SQL 안전성 검증

        Returns:
            (is_safe, error_message)
        """
        sql_upper = sql.upper().strip()

        # SELECT 또는 WITH (CTE)로 시작하는지 확인
        # Phase 72.4: CTE 쿼리 (WITH ... SELECT) 허용 추가
        if not (sql_upper.startswith('SELECT') or sql_upper.startswith('WITH')):
            return False, "SELECT 쿼리만 허용됩니다 (CTE WITH 절 포함)"

        # WITH 쿼리인 경우 최종적으로 SELECT가 있는지 확인
        if sql_upper.startswith('WITH') and 'SELECT' not in sql_upper:
            return False, "WITH 절 뒤에 SELECT 쿼리가 필요합니다"

        # 위험한 키워드 검사
        for pattern in self.DANGEROUS_KEYWORDS:
            if re.search(pattern, sql, re.IGNORECASE):
                return False, f"위험한 키워드 감지: {pattern}"

        # 세미콜론 여러 개 (다중 쿼리) 검사
        if sql.count(';') > 1:
            return False, "다중 쿼리는 허용되지 않습니다"

        return True, None

    def _execute_sql(self, sql: str) -> SQLResult:
        """SQL 실행"""
        start_time = time.time()

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # 타임아웃 설정 (PostgreSQL)
            cursor.execute(f"SET statement_timeout = '{self.timeout * 1000}ms'")

            # 쿼리 실행
            cursor.execute(sql)

            # 결과 가져오기
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(self.max_rows)

            # 리스트로 변환
            rows = [list(row) for row in rows]

            conn.close()

            execution_time_ms = (time.time() - start_time) * 1000

            return SQLResult(
                success=True,
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_time_ms=round(execution_time_ms, 2)
            )

        except Exception as e:
            logger.error(f"SQL 실행 오류: {e}")
            return SQLResult(
                success=False,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000
            )

    def _interpret_result(
        self,
        question: str,
        sql: str,
        columns: List[str],
        rows: List[List[Any]],
        max_tokens: int = 1024,
        temperature: float = 0.5
    ) -> str:
        """쿼리 결과 해석"""
        # 결과 포맷팅
        result_text = format_query_result(columns, rows, max_rows=20)

        system_prompt, user_prompt = build_result_interpretation_prompt(
            question=question,
            sql=sql,
            result=result_text,
            row_count=len(rows)
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        response = self.llm.chat(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature
        )

        return response.get("choices", [{}])[0].get("message", {}).get("content", "")

    def get_example_queries(self) -> List[Dict[str, str]]:
        """예제 쿼리 목록 (Phase 35.3: ENTITY_COLUMNS 기반으로 변경)"""
        from sql.sql_prompts import ENTITY_COLUMNS, ENTITY_LABELS
        return [
            {
                "name": k,
                "question": f"{ENTITY_LABELS.get(k, k)} 검색",
                "sql": v["sql_template"].format(keyword="검색어")
            }
            for k, v in ENTITY_COLUMNS.items()
        ]


# 싱글톤 인스턴스
_sql_agent: Optional[SQLAgent] = None


def get_sql_agent() -> SQLAgent:
    """SQL 에이전트 싱글톤"""
    global _sql_agent
    if _sql_agent is None:
        _sql_agent = SQLAgent()
    return _sql_agent


if __name__ == "__main__":
    print("SQL 에이전트 테스트")

    agent = get_sql_agent()

    # 예제 쿼리 테스트
    print("\n1. 예제 쿼리 목록:")
    examples = agent.get_example_queries()
    for ex in examples[:3]:
        print(f"   - {ex['name']}: {ex['question']}")

    # 자연어 쿼리 테스트
    print("\n2. 자연어 쿼리 테스트:")
    question = "연구과제 중에서 예산이 가장 큰 과제 10개를 알려줘"
    print(f"   질문: {question}")

    response = agent.query(question, interpret_result=True)

    print(f"\n3. 생성된 SQL:")
    print(f"   {response.generated_sql}")

    print(f"\n4. 실행 결과:")
    if response.result.success:
        print(f"   - 행 수: {response.result.row_count}")
        print(f"   - 컬럼: {response.result.columns[:5]}...")
        if response.result.rows:
            print(f"   - 첫 번째 행: {response.result.rows[0][:3]}...")
    else:
        print(f"   - 오류: {response.result.error}")

    if response.interpretation:
        print(f"\n5. 해석:")
        print(f"   {response.interpretation[:300]}...")

    print(f"\n6. 처리 시간: {response.elapsed_ms:.2f}ms")
