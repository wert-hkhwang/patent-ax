#!/usr/bin/env python3
"""
EP-Agent: 특허 임베딩 스크립트
배치 사이즈: 10 (안정성 우선)
"""

import os
import requests
import psycopg2
import time
from datetime import datetime

# 설정
KURE_API = os.getenv("KURE_API_URL", "http://210.109.80.106:7000/api/embedding")
QDRANT_URL = os.getenv("QDRANT_URL", "http://210.109.80.106:6333")
DB_CONFIG = {
    "host": "localhost",
    "database": "ax",
    "user": "postgres",
    "password": "postgres"
}
BATCH_SIZE = 10
COLLECTION_NAME = "patent"

def get_embedding(text: str) -> list:
    try:
        resp = requests.post(KURE_API, json={"text": text}, timeout=30)
        if resp.status_code == 200:
            return resp.json().get("embedding")
    except Exception as e:
        print(f"  [ERROR] 임베딩 실패: {e}")
    return None

def upsert_to_qdrant(points: list) -> bool:
    try:
        resp = requests.put(
            f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points",
            json={"points": points},
            timeout=60
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"  [ERROR] Qdrant 저장 실패: {e}")
        return False

def create_collection():
    try:
        resp = requests.put(
            f"{QDRANT_URL}/collections/{COLLECTION_NAME}",
            json={"vectors": {"size": 1024, "distance": "Cosine"}},
            timeout=30
        )
        print(f"컬렉션 생성: {resp.status_code}")
    except Exception as e:
        print(f"컬렉션 이미 존재하거나 오류: {e}")

def main():
    print(f"[{datetime.now()}] 특허 임베딩 시작", flush=True)
    create_collection()

    conn = psycopg2.connect(**DB_CONFIG)
    # 서버 사이드 커서 사용 (메모리 효율)
    cur = conn.cursor(name='patent_cursor')
    cur.itersize = 1000

    print("DB 쿼리 시작...", flush=True)

    # 전체 건수 조회 (별도 커서)
    count_cur = conn.cursor()
    count_cur.execute("SELECT COUNT(*) FROM f_patents WHERE conts_klang_nm IS NOT NULL")
    total = count_cur.fetchone()[0]
    count_cur.close()
    print(f"전체 건수: {total:,}", flush=True)

    try:
        resp = requests.post(
            f"http://210.109.80.106:6333/collections/{COLLECTION_NAME}/points/count",
            json={}, timeout=10
        )
        processed = resp.json().get("result", {}).get("count", 0)
        print(f"이미 처리됨: {processed:,}", flush=True)
    except:
        processed = 0

    # 특허: 제목 + 해결과제 + 기술수단 결합 (비교 분석 최적화)
    print("데이터 로딩 중...", flush=True)
    cur.execute("""
        SELECT documentid,
               COALESCE(conts_klang_nm, '') || ' ' ||
               COALESCE(objectko, '') || ' ' ||
               COALESCE(solutionko, '') as text,
               conts_klang_nm, ipc_main, application_date, objectko, solutionko
        FROM f_patents
        WHERE conts_klang_nm IS NOT NULL
        ORDER BY documentid
        OFFSET %s
    """, (processed,))
    print("데이터 로딩 완료, 임베딩 시작", flush=True)

    batch = []
    count = processed
    start_time = time.time()

    for row in cur:
        documentid, text, title, ipc_main, app_date, objectko, solutionko = row

        if not text.strip():
            continue

        embedding = get_embedding(text[:2000])
        if embedding is None:
            continue

        batch.append({
            "id": hash(documentid) & 0x7FFFFFFFFFFFFFFF,
            "vector": embedding,
            "payload": {
                "documentid": documentid,
                "title": title[:200] if title else "",
                "ipc_main": ipc_main,
                "application_date": str(app_date) if app_date else None,
                "objectko": objectko[:500] if objectko else "",
                "solutionko": solutionko[:500] if solutionko else "",
                "type": "patent"
            }
        })

        if len(batch) >= BATCH_SIZE:
            if upsert_to_qdrant(batch):
                count += len(batch)
                elapsed = time.time() - start_time
                rate = count / elapsed if elapsed > 0 else 0
                eta = (total - count) / rate if rate > 0 else 0
                print(f"\r[{count:,}/{total:,}] {count*100/total:.1f}% | {rate:.1f}/s | ETA: {eta/3600:.1f}h", end="", flush=True)
            batch = []
            time.sleep(0.1)

    if batch:
        upsert_to_qdrant(batch)
        count += len(batch)

    cur.close()
    conn.close()
    print(f"\n[{datetime.now()}] 완료: {count:,}건 처리됨")

if __name__ == "__main__":
    main()
