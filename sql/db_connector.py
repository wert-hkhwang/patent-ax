"""
데이터베이스 연결 모듈
- PostgreSQL 연결 (로컬 ax 데이터베이스)
- 환경 변수 기반 설정
"""

import os
import psycopg2
from typing import Optional


# 환경 변수에서 DB 연결 정보 로드
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "database": os.getenv("DB_NAME", "ax"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
}


def get_db_connection():
    """DB 연결 생성"""
    try:
        conn = psycopg2.connect(
            host=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            database=DB_CONFIG["database"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"]
        )
        return conn
    except Exception as e:
        print(f"DB 연결 오류: {e}")
        raise


def test_connection():
    """DB 연결 테스트"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        conn.close()
        print(f"DB 연결 성공: {result}")
        return True
    except Exception as e:
        print(f"DB 연결 실패: {e}")
        return False


if __name__ == "__main__":
    test_connection()
