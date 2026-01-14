"""
워크플로우 커스텀 예외 클래스
- 표준화된 에러 핸들링
- 노드별 특화 예외
"""


class WorkflowError(Exception):
    """워크플로우 기본 예외"""

    def __init__(self, message: str, node: str = None, details: dict = None):
        self.message = message
        self.node = node
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "node": self.node,
            "details": self.details
        }


class QueryAnalysisError(WorkflowError):
    """쿼리 분석 실패"""

    def __init__(self, message: str, query: str = None, details: dict = None):
        super().__init__(message, node="analyzer", details=details)
        self.query = query


class SQLExecutionError(WorkflowError):
    """SQL 실행 실패"""

    def __init__(self, message: str, sql: str = None, details: dict = None):
        super().__init__(message, node="sql_executor", details=details)
        self.sql = sql


class RAGRetrievalError(WorkflowError):
    """RAG 검색 실패"""

    def __init__(self, message: str, strategy: str = None, details: dict = None):
        super().__init__(message, node="rag_retriever", details=details)
        self.strategy = strategy


class MergeError(WorkflowError):
    """결과 병합 실패"""

    def __init__(self, message: str, details: dict = None):
        super().__init__(message, node="merger", details=details)


class ResponseGenerationError(WorkflowError):
    """응답 생성 실패"""

    def __init__(self, message: str, details: dict = None):
        super().__init__(message, node="generator", details=details)


class EmptyQueryError(WorkflowError):
    """빈 쿼리 에러"""

    def __init__(self):
        super().__init__(
            message="쿼리가 비어있습니다.",
            node="analyzer",
            details={"error_code": "EMPTY_QUERY"}
        )


class LLMConnectionError(WorkflowError):
    """LLM 연결 실패"""

    def __init__(self, message: str = "LLM 서버 연결 실패", details: dict = None):
        super().__init__(message, node=None, details=details)


class DatabaseConnectionError(WorkflowError):
    """데이터베이스 연결 실패"""

    def __init__(self, message: str = "데이터베이스 연결 실패", details: dict = None):
        super().__init__(message, node="sql_executor", details=details)
