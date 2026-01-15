# Patent-AX v1.3 서비스 구동 정보

**구동 시간**: 2026-01-15
**버전**: v1.3 Phase 2

---

## 서비스 URL

### Backend API (FastAPI)
- **URL**: http://localhost:8001
- **Health Check**: http://localhost:8001/health
- **API 문서**: http://localhost:8001/docs
- **Redoc**: http://localhost:8001/redoc
- **PID**: 3002965

### Frontend (Next.js)
- **메인 페이지**: http://localhost:3002/
- **Easy Mode**: http://localhost:3002/easy
- **Visualization**: http://localhost:3002/visualization
- **포트**: 3002

---

## 주요 API 엔드포인트

### 사용자 프로필 관리
```bash
# 프로필 생성
curl -X POST "http://localhost:8001/user/profile" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user",
    "education_level": "대학생",
    "occupation": "연구원"
  }'

# 프로필 조회
curl "http://localhost:8001/user/profile/test_user"

# 레벨 변경
curl -X POST "http://localhost:8001/user/level/change" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user",
    "new_level": "L5",
    "reason": "변리사 자격 취득"
  }'

# 레벨별 통계
curl "http://localhost:8001/user/level/statistics"

# 전체 레벨 정보
curl "http://localhost:8001/user/level/info"
```

### 워크플로우 채팅
```bash
# 스트리밍 채팅
curl -X POST "http://localhost:8001/workflow/chat/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "양자컴퓨터 특허",
    "session_id": "test_session",
    "level": "L4"
  }'

# 일반 채팅
curl -X POST "http://localhost:8001/workflow/chat?query=배터리 특허&session_id=test"
```

---

## 테스트 결과

### 프로필 생성 테스트
```json
{
  "id": 8,
  "user_id": "demo_user",
  "education_level": "대학생",
  "occupation": "연구원",
  "registered_level": "L4",
  "current_level": "L4",
  "level_description": "기술 상세 (연구자)"
}
```

✓ **자동 레벨 매핑 성공**: 대학생 + 연구원 → L4

---

## 주요 기능

### 1. Easy Mode (L1 사용자용)
- **URL**: http://localhost:3002/easy
- **특징**:
  - 큰 글씨, 친근한 디자인
  - 6개 추천 질문 버튼
  - 쉬운 말로 된 답변

### 2. V3 리터러시 레벨 (L1~L6)
- **L1**: 초등학생 🎓 - 쉬운 설명
- **L2**: 대학생/일반인 📚 - 기본 설명
- **L3**: 중소기업 실무자 💼 - 실무 중심
- **L4**: 연구자 🔬 - 기술 상세
- **L5**: 변리사/심사관 ⚖️ - 전문가
- **L6**: 정책담당자 📊 - 정책 동향

### 3. 자동 레벨 매핑
| 학력/직업 | 레벨 |
|-----------|------|
| 초등학생, 중학생 | L1 |
| 고등학생, 대학생, 석사 | L2 |
| 중소기업 실무자 | L3 |
| 연구원 | L4 |
| 변리사, 심사관 | L5 |
| 정책담당자 | L6 |

---

## 서비스 관리

### 프로세스 확인
```bash
# Backend
ps aux | grep "uvicorn.*8001"

# Frontend
netstat -tuln | grep 3002
```

### 로그 확인
```bash
# Backend 로그 (있는 경우)
tail -f logs/api_8001.log

# Frontend 로그
# 표준 출력으로 실행 중
```

### 서비스 중지
```bash
# Backend 중지
kill 3002965

# Frontend 중지
lsof -ti:3002 | xargs kill
```

### 서비스 재시작
```bash
# Backend
cd /root/patent-ax
/usr/bin/python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8001 &

# Frontend
cd /root/patent-ax/frontend
NEXT_PUBLIC_API_URL=http://localhost:8001 PORT=3002 npm run dev &
```

---

## 환경 변수

### Frontend
- `NEXT_PUBLIC_API_URL`: http://localhost:8001
- `PORT`: 3002

### Backend
- 환경 변수는 `.env` 파일에서 로드
- DB, Qdrant, vLLM 연결 정보 포함

---

## 데이터베이스

### PostgreSQL
- **Host**: localhost
- **Port**: 5432
- **Database**: ax
- **주요 테이블**:
  - `f_user_profiles`: 사용자 프로필
  - `f_patent_tech_elements`: 특허 기술 요소

### Qdrant (Vector DB)
- **URL**: 210.109.80.106:6333
- **Collection**: patents_v3_collection (1.82M points)

### vLLM (LLM 서버)
- **URL**: 210.109.80.106:12288
- **Model**: EXAONE-4.0.1-32B

---

## 문서

- [Phase 2 구현 보고서](docs/PHASE2_UI_IMPLEMENTATION.md)
- [사용자 가이드](docs/USER_LITERACY_GUIDE.md)
- [구현 계획서](docs/IMPLEMENTATION_PLAN_USER_LITERACY.md)
- [API 문서](http://localhost:8001/docs)

---

## 문제 해결

### Frontend가 Backend에 연결 안 됨
**증상**: `Failed to fetch`

**해결**:
1. Backend가 실행 중인지 확인:
   ```bash
   curl http://localhost:8001/health
   ```

2. 환경 변수 확인:
   ```bash
   echo $NEXT_PUBLIC_API_URL
   ```

3. CORS 설정 확인 (api/main.py)

### 프로필 생성 실패
**증상**: `User not found`

**해결**:
1. PostgreSQL 연결 확인
2. 테이블 생성 확인:
   ```sql
   \c ax
   \d f_user_profiles
   ```

---

**최종 업데이트**: 2026-01-15 10:30
**작성자**: Claude Code Agent
