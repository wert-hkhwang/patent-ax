#!/bin/bash
# Patent-AX 빠른 시작 가이드

set -e

echo "============================================"
echo "   Patent-AX 빠른 시작"
echo "============================================"
echo ""

cd "$(dirname "$0")"

# 1. 환경변수 확인
echo "📝 [1/5] 환경변수 확인..."
if [ ! -f .env ]; then
    echo "⚠️  .env 파일이 없습니다."
    echo "   다음 명령으로 생성하세요:"
    echo "   cp .env.example .env"
    echo "   vim .env  # DB 비밀번호 등 수정"
    echo ""
    exit 1
else
    echo "✅ .env 파일 존재"
fi
echo ""

# 2. Python 패키지 확인
echo "🐍 [2/5] Python 패키지 확인..."
if ! python3 -c "import requests" 2>/dev/null; then
    echo "⚠️  필수 패키지가 없습니다."
    echo "   다음 명령으로 설치하세요:"
    echo "   pip install -r requirements.txt"
    echo ""
    exit 1
else
    echo "✅ Python 패키지 설치됨"
fi
echo ""

# 3. GPU 서버 접근성 확인
echo "📡 [3/5] GPU 서버 접근성 확인..."

check_service() {
    local name=$1
    local url=$2
    if curl -s -o /dev/null -w "%{http_code}" "$url" --max-time 5 | grep -q "200"; then
        echo "   ✅ $name: OK"
        return 0
    else
        echo "   ❌ $name: FAILED"
        return 1
    fi
}

check_service "Qdrant" "http://210.109.80.106:6333/collections/patents_v3_collection"
check_service "vLLM" "http://210.109.80.106:12288/health"
check_service "KURE" "http://210.109.80.106:7000/health"
echo ""

# 4. PostgreSQL 연결 확인
echo "🗄️  [4/5] PostgreSQL 연결 확인..."
python3 -c "
from sql.db_connector import get_db_connection
try:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM f_patents;')
        count = cursor.fetchone()[0]
        print(f'   ✅ f_patents: {count:,} rows')
except Exception as e:
    print(f'   ❌ PostgreSQL 연결 실패: {e}')
    exit(1)
" || {
    echo "   ⚠️  데이터베이스 연결 확인 실패"
    echo ""
}
echo ""

# 5. 서비스 실행 안내
echo "🚀 [5/5] 서비스 실행 안내"
echo ""
echo "   백엔드 API 실행:"
echo "   $ cd api && uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
echo ""
echo "   프론트엔드 실행:"
echo "   $ cd frontend && npm run dev"
echo ""
echo "   테스트 실행:"
echo "   $ ./run_tests.sh"
echo ""

echo "============================================"
echo "   준비 완료 ✅"
echo "============================================"
