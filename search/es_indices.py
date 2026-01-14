"""
Elasticsearch 인덱스 관리

인덱스 생성, 삭제, 매핑 업데이트, 상태 확인 등을 담당합니다.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from elasticsearch import Elasticsearch, AsyncElasticsearch
from elasticsearch.exceptions import NotFoundError, RequestError

logger = logging.getLogger(__name__)

# 설정 파일 경로
CONFIG_DIR = Path(__file__).parent.parent / "config" / "elasticsearch"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
MAPPINGS_DIR = CONFIG_DIR / "mappings"


class ESIndexManager:
    """
    Elasticsearch 인덱스 관리자

    인덱스 생성, 삭제, 상태 확인, 매핑 관리 기능을 제공합니다.

    사용 예:
        manager = ESIndexManager()
        await manager.create_all_indices()
        status = await manager.get_indices_status()
    """

    # 인덱스 목록 및 매핑 파일
    INDICES = {
        "ax_patents": "ax_patents.json",
        "ax_projects": "ax_projects.json",
        "ax_equipments": "ax_equipments.json",
        "ax_proposals": "ax_proposals.json",
        "ax_evaluations": "ax_evaluations.json",
    }

    def __init__(
        self,
        hosts: Optional[List[str]] = None,
    ):
        """
        인덱스 관리자 초기화

        Args:
            hosts: ES 호스트 목록
        """
        es_host = os.getenv("ES_HOST", "localhost")
        es_port = os.getenv("ES_PORT", "9200")
        es_scheme = os.getenv("ES_SCHEME", "http")

        self.hosts = hosts or [f"{es_scheme}://{es_host}:{es_port}"]
        self._client: Optional[Elasticsearch] = None
        self._async_client: Optional[AsyncElasticsearch] = None

    @property
    def client(self) -> Elasticsearch:
        """동기 클라이언트"""
        if self._client is None:
            self._client = Elasticsearch(hosts=self.hosts)
        return self._client

    @property
    def async_client(self) -> AsyncElasticsearch:
        """비동기 클라이언트"""
        if self._async_client is None:
            self._async_client = AsyncElasticsearch(hosts=self.hosts)
        return self._async_client

    def _load_settings(self) -> Dict[str, Any]:
        """settings.json 로드"""
        if not SETTINGS_PATH.exists():
            logger.warning(f"Settings file not found: {SETTINGS_PATH}")
            return {}

        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_mapping(self, index_name: str) -> Dict[str, Any]:
        """인덱스별 매핑 파일 로드"""
        mapping_file = self.INDICES.get(index_name)
        if not mapping_file:
            raise ValueError(f"Unknown index: {index_name}")

        mapping_path = MAPPINGS_DIR / mapping_file
        if not mapping_path.exists():
            raise FileNotFoundError(f"Mapping file not found: {mapping_path}")

        with open(mapping_path, "r", encoding="utf-8") as f:
            return json.load(f)

    async def create_index(
        self,
        index_name: str,
        recreate: bool = False,
    ) -> bool:
        """
        단일 인덱스 생성

        Args:
            index_name: 인덱스명
            recreate: 기존 인덱스 삭제 후 재생성

        Returns:
            성공 여부
        """
        try:
            exists = await self.async_client.indices.exists(index=index_name)

            if exists:
                if recreate:
                    logger.info(f"Deleting existing index: {index_name}")
                    await self.async_client.indices.delete(index=index_name)
                else:
                    logger.info(f"Index already exists: {index_name}")
                    return True

            # 설정 및 매핑 로드
            settings = self._load_settings()
            mapping = self._load_mapping(index_name)

            # 인덱스 생성
            body = {
                "settings": settings.get("settings", {}),
                "mappings": mapping.get("mappings", {}),
            }

            await self.async_client.indices.create(
                index=index_name,
                body=body,
            )

            logger.info(f"Index created: {index_name}")
            return True

        except RequestError as e:
            logger.error(f"Failed to create index {index_name}: {e}")
            return False

    def create_index_sync(
        self,
        index_name: str,
        recreate: bool = False,
    ) -> bool:
        """단일 인덱스 생성 (동기)"""
        try:
            exists = self.client.indices.exists(index=index_name)

            if exists:
                if recreate:
                    logger.info(f"Deleting existing index: {index_name}")
                    self.client.indices.delete(index=index_name)
                else:
                    logger.info(f"Index already exists: {index_name}")
                    return True

            settings = self._load_settings()
            mapping = self._load_mapping(index_name)

            body = {
                "settings": settings.get("settings", {}),
                "mappings": mapping.get("mappings", {}),
            }

            self.client.indices.create(index=index_name, body=body)
            logger.info(f"Index created: {index_name}")
            return True

        except RequestError as e:
            logger.error(f"Failed to create index {index_name}: {e}")
            return False

    async def create_all_indices(self, recreate: bool = False) -> Dict[str, bool]:
        """
        모든 인덱스 생성

        Args:
            recreate: 기존 인덱스 삭제 후 재생성

        Returns:
            인덱스별 생성 결과
        """
        results = {}
        for index_name in self.INDICES.keys():
            results[index_name] = await self.create_index(index_name, recreate)
        return results

    def create_all_indices_sync(self, recreate: bool = False) -> Dict[str, bool]:
        """모든 인덱스 생성 (동기)"""
        results = {}
        for index_name in self.INDICES.keys():
            results[index_name] = self.create_index_sync(index_name, recreate)
        return results

    async def delete_index(self, index_name: str) -> bool:
        """
        인덱스 삭제

        Args:
            index_name: 삭제할 인덱스명

        Returns:
            성공 여부
        """
        try:
            exists = await self.async_client.indices.exists(index=index_name)
            if not exists:
                logger.info(f"Index does not exist: {index_name}")
                return True

            await self.async_client.indices.delete(index=index_name)
            logger.info(f"Index deleted: {index_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete index {index_name}: {e}")
            return False

    async def delete_all_indices(self) -> Dict[str, bool]:
        """모든 AX 인덱스 삭제"""
        results = {}
        for index_name in self.INDICES.keys():
            results[index_name] = await self.delete_index(index_name)
        return results

    async def get_index_info(self, index_name: str) -> Optional[Dict[str, Any]]:
        """
        인덱스 정보 조회

        Args:
            index_name: 인덱스명

        Returns:
            인덱스 설정/매핑/통계 정보
        """
        try:
            exists = await self.async_client.indices.exists(index=index_name)
            if not exists:
                return None

            # 설정 조회
            settings = await self.async_client.indices.get_settings(index=index_name)

            # 매핑 조회
            mapping = await self.async_client.indices.get_mapping(index=index_name)

            # 통계 조회
            stats = await self.async_client.indices.stats(index=index_name)

            return {
                "name": index_name,
                "settings": settings.get(index_name, {}).get("settings", {}),
                "mappings": mapping.get(index_name, {}).get("mappings", {}),
                "docs_count": stats["indices"][index_name]["primaries"]["docs"]["count"],
                "size_bytes": stats["indices"][index_name]["primaries"]["store"]["size_in_bytes"],
            }

        except NotFoundError:
            return None

    async def get_indices_status(self) -> Dict[str, Dict[str, Any]]:
        """
        모든 인덱스 상태 조회

        Returns:
            인덱스별 상태 정보
        """
        status = {}
        for index_name in self.INDICES.keys():
            info = await self.get_index_info(index_name)
            if info:
                status[index_name] = {
                    "exists": True,
                    "docs_count": info["docs_count"],
                    "size_bytes": info["size_bytes"],
                    "size_mb": round(info["size_bytes"] / (1024 * 1024), 2),
                }
            else:
                status[index_name] = {
                    "exists": False,
                    "docs_count": 0,
                    "size_bytes": 0,
                    "size_mb": 0,
                }
        return status

    def get_indices_status_sync(self) -> Dict[str, Dict[str, Any]]:
        """모든 인덱스 상태 조회 (동기)"""
        status = {}
        for index_name in self.INDICES.keys():
            try:
                exists = self.client.indices.exists(index=index_name)
                if exists:
                    stats = self.client.indices.stats(index=index_name)
                    status[index_name] = {
                        "exists": True,
                        "docs_count": stats["indices"][index_name]["primaries"]["docs"]["count"],
                        "size_bytes": stats["indices"][index_name]["primaries"]["store"]["size_in_bytes"],
                    }
                else:
                    status[index_name] = {"exists": False, "docs_count": 0, "size_bytes": 0}
            except Exception as e:
                logger.error(f"Error getting status for {index_name}: {e}")
                status[index_name] = {"exists": False, "docs_count": 0, "size_bytes": 0, "error": str(e)}
        return status

    async def refresh_index(self, index_name: str) -> bool:
        """
        인덱스 새로고침

        인덱싱된 문서를 검색 가능하게 만듭니다.

        Args:
            index_name: 인덱스명

        Returns:
            성공 여부
        """
        try:
            await self.async_client.indices.refresh(index=index_name)
            logger.info(f"Index refreshed: {index_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to refresh index {index_name}: {e}")
            return False

    async def update_synonyms(self, synonyms_path: str) -> bool:
        """
        동의어 사전 업데이트

        동의어 파일 변경 후 인덱스 재오픈이 필요합니다.

        Args:
            synonyms_path: 동의어 파일 경로

        Returns:
            성공 여부
        """
        try:
            # 모든 인덱스 닫기
            for index_name in self.INDICES.keys():
                await self.async_client.indices.close(index=index_name)

            # 동의어 필터 업데이트 (인덱스 설정에서 참조)
            # 파일 변경은 외부에서 수행, 여기서는 인덱스 재오픈만

            # 모든 인덱스 열기
            for index_name in self.INDICES.keys():
                await self.async_client.indices.open(index=index_name)

            logger.info("Synonyms updated, indices reopened")
            return True

        except Exception as e:
            logger.error(f"Failed to update synonyms: {e}")
            return False

    async def reindex(
        self,
        source_index: str,
        dest_index: str,
        query: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        인덱스 리인덱싱

        Args:
            source_index: 소스 인덱스
            dest_index: 대상 인덱스
            query: 필터 쿼리

        Returns:
            리인덱싱 결과
        """
        body = {
            "source": {"index": source_index},
            "dest": {"index": dest_index},
        }

        if query:
            body["source"]["query"] = query

        try:
            result = await self.async_client.reindex(
                body=body,
                wait_for_completion=True,
            )
            logger.info(f"Reindex completed: {source_index} → {dest_index}")
            return result

        except Exception as e:
            logger.error(f"Reindex failed: {e}")
            return {"error": str(e)}

    async def close(self):
        """비동기 클라이언트 종료"""
        if self._async_client:
            await self._async_client.close()
            self._async_client = None

    def close_sync(self):
        """동기 클라이언트 종료"""
        if self._client:
            self._client.close()
            self._client = None


# CLI 인터페이스
async def main():
    """CLI 진입점"""
    import argparse

    parser = argparse.ArgumentParser(description="ES Index Manager")
    parser.add_argument("action", choices=["create", "delete", "status", "refresh"])
    parser.add_argument("--index", "-i", help="Target index (default: all)")
    parser.add_argument("--recreate", "-r", action="store_true", help="Recreate existing indices")

    args = parser.parse_args()

    manager = ESIndexManager()

    try:
        if args.action == "create":
            if args.index:
                result = await manager.create_index(args.index, args.recreate)
                print(f"Create {args.index}: {'OK' if result else 'FAILED'}")
            else:
                results = await manager.create_all_indices(args.recreate)
                for idx, ok in results.items():
                    print(f"  {idx}: {'OK' if ok else 'FAILED'}")

        elif args.action == "delete":
            if args.index:
                result = await manager.delete_index(args.index)
                print(f"Delete {args.index}: {'OK' if result else 'FAILED'}")
            else:
                results = await manager.delete_all_indices()
                for idx, ok in results.items():
                    print(f"  {idx}: {'OK' if ok else 'FAILED'}")

        elif args.action == "status":
            status = await manager.get_indices_status()
            print("\n=== ES Index Status ===")
            for idx, info in status.items():
                if info["exists"]:
                    print(f"  {idx}: {info['docs_count']:,} docs, {info['size_mb']} MB")
                else:
                    print(f"  {idx}: NOT EXISTS")

        elif args.action == "refresh":
            if args.index:
                result = await manager.refresh_index(args.index)
                print(f"Refresh {args.index}: {'OK' if result else 'FAILED'}")
            else:
                for index_name in manager.INDICES.keys():
                    result = await manager.refresh_index(index_name)
                    print(f"  {index_name}: {'OK' if result else 'FAILED'}")

    finally:
        await manager.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
