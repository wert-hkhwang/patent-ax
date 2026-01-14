"""
Patent-AX 벡터 검색 API 설정 (특허 전용)
"""
import os

# 서버 설정 - 환경변수 우선
QDRANT_URL = os.getenv("QDRANT_URL", "http://210.109.80.106:6333")
KURE_API = os.getenv("KURE_API_URL", "http://210.109.80.106:7000/api/embedding")

# Patent-AX: 특허 컬렉션만
COLLECTIONS = {
    "patents": "patents_v3_collection",
}

# Patent-AX: 특허 필터 가능 필드만
FILTERABLE_FIELDS = {
    "patents": ["ipc_main", "patent_status", "applicant", "application_date", "ntcd"],
}

# Patent-AX: 특허 표시 이름만
DISPLAY_NAMES = {
    "patents": "특허",
}

# 기본 설정
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
EMBEDDING_TIMEOUT = 30
SEARCH_TIMEOUT = 30
