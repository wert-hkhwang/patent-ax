"""
Patent-AX Loader 모듈 (특허 전용)
- 특허 랭킹 및 분석 전용 Loader
- 출원기관, 피인용, 영향력, 국적별 분석
"""

from workflow.loaders.base_loader import BaseLoader, create_markdown_table
from workflow.loaders.registry import (
    get_loader,
    get_loader_class,
    LOADER_MAPPING,
    list_available_loaders,
    is_loader_available,
)

# Patent-AX: 특허 Loader만 export
from workflow.loaders.patent_ranking_loader import (
    PatentRankingLoader,
    PatentCitationLoader,
    PatentInfluenceLoader,
    PatentNationalityLoader,
)

__all__ = [
    # Base
    "BaseLoader",
    "create_markdown_table",
    # Registry
    "get_loader",
    "get_loader_class",
    "LOADER_MAPPING",
    "list_available_loaders",
    "is_loader_available",
    # Patent-AX: 특허 Loader만
    "PatentRankingLoader",
    "PatentCitationLoader",
    "PatentInfluenceLoader",
    "PatentNationalityLoader",
]
