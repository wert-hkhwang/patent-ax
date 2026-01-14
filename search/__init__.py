# AX Elasticsearch Search Module
"""
Elasticsearch 기반 검색 모듈

이 모듈은 PostgreSQL ILIKE 검색을 대체하여
고성능 한글 검색 및 집계 기능을 제공합니다.

주요 컴포넌트:
- es_client: Elasticsearch 클라이언트 및 검색 API
- es_indices: 인덱스 생성/삭제/관리
- es_migrator: PostgreSQL → Elasticsearch 데이터 마이그레이션
- es_orchestrator: 검색 전략 결정 및 다중 엔진 조율
"""

from .es_client import ESSearchClient
from .es_indices import ESIndexManager
from .es_migrator import ESMigrator

__all__ = [
    "ESSearchClient",
    "ESIndexManager",
    "ESMigrator",
]
