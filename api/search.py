"""
EP-Agent 벡터 검색 로직
"""

import requests
from typing import Dict, List, Optional, Any
from api.config import (
    QDRANT_URL, KURE_API, COLLECTIONS, FILTERABLE_FIELDS, DISPLAY_NAMES,
    EMBEDDING_TIMEOUT, SEARCH_TIMEOUT
)


def get_embedding(text: str) -> Optional[List[float]]:
    """KURE API로 텍스트 임베딩 생성"""
    try:
        resp = requests.post(
            KURE_API,
            json={"text": text},
            timeout=EMBEDDING_TIMEOUT
        )
        if resp.status_code == 200:
            return resp.json().get("embedding")
    except Exception as e:
        print(f"임베딩 오류: {e}")
    return None


def build_filter(filters: Dict[str, str], collection_key: str) -> Optional[Dict]:
    """Qdrant 필터 객체 생성"""
    if not filters:
        return None

    allowed_fields = FILTERABLE_FIELDS.get(collection_key, [])
    must_conditions = []

    for key, value in filters.items():
        if key in allowed_fields and value:
            must_conditions.append({
                "key": key,
                "match": {"text": value}
            })

    if not must_conditions:
        return None

    return {"must": must_conditions}


def search_single_collection(
    query: str,
    collection_key: str,
    limit: int = 10,
    filters: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    """단일 컬렉션 검색"""

    # 임베딩 생성
    embedding = get_embedding(query)
    if not embedding:
        return []

    # 컬렉션 이름 확인
    collection_name = COLLECTIONS.get(collection_key)
    if not collection_name:
        return []

    # 검색 요청 구성
    search_payload = {
        "vector": embedding,
        "limit": limit,
        "with_payload": True
    }

    # 필터 추가
    filter_obj = build_filter(filters, collection_key)
    if filter_obj:
        search_payload["filter"] = filter_obj

    # Qdrant 검색 실행
    try:
        resp = requests.post(
            f"{QDRANT_URL}/collections/{collection_name}/points/search",
            json=search_payload,
            timeout=SEARCH_TIMEOUT
        )

        if resp.status_code == 200:
            results = resp.json().get("result", [])
            # 컬렉션 정보 추가
            for r in results:
                r["collection"] = collection_key
            return results
    except Exception as e:
        print(f"검색 오류 ({collection_key}): {e}")

    return []


def search_multiple_collections(
    query: str,
    collections: List[str],
    limit_per_collection: int = 5,
    filters: Optional[Dict[str, Dict[str, str]]] = None
) -> List[Dict[str, Any]]:
    """다중 컬렉션 통합 검색"""

    # 임베딩 생성 (한 번만)
    embedding = get_embedding(query)
    if not embedding:
        return []

    all_results = []

    for collection_key in collections:
        collection_name = COLLECTIONS.get(collection_key)
        if not collection_name:
            continue

        # 컬렉션별 필터
        collection_filters = None
        if filters and collection_key in filters:
            collection_filters = filters[collection_key]

        # 검색 요청 구성
        search_payload = {
            "vector": embedding,
            "limit": limit_per_collection,
            "with_payload": True
        }

        # 필터 추가
        filter_obj = build_filter(collection_filters, collection_key)
        if filter_obj:
            search_payload["filter"] = filter_obj

        # 검색 실행
        try:
            resp = requests.post(
                f"{QDRANT_URL}/collections/{collection_name}/points/search",
                json=search_payload,
                timeout=SEARCH_TIMEOUT
            )

            if resp.status_code == 200:
                results = resp.json().get("result", [])
                for r in results:
                    r["collection"] = collection_key
                all_results.extend(results)
        except Exception as e:
            print(f"검색 오류 ({collection_key}): {e}")
            continue

    # 점수 기준 정렬
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)

    return all_results


def get_collection_count(collection_key: str) -> int:
    """컬렉션 벡터 수 조회"""
    collection_name = COLLECTIONS.get(collection_key)
    if not collection_name:
        return 0

    try:
        resp = requests.post(
            f"{QDRANT_URL}/collections/{collection_name}/points/count",
            json={},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get("result", {}).get("count", 0)
    except:
        pass

    return 0


def get_all_collection_info() -> List[Dict[str, Any]]:
    """모든 컬렉션 정보 조회"""
    info_list = []

    for key, collection_name in COLLECTIONS.items():
        count = get_collection_count(key)
        info_list.append({
            "name": key,
            "display_name": DISPLAY_NAMES.get(key, key),
            "vector_count": count,
            "filterable_fields": FILTERABLE_FIELDS.get(key, [])
        })

    return info_list
