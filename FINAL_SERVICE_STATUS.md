# Easy 특허 Agent v1.3 - 최종 서비스 상태

**구동 시간**: 2026-01-15
**최종 업데이트**: Phase 2 UI 간소화 완료

---

## ✅ 서비스 정상 구동

### 서비스 URL

- **Frontend**: http://localhost:3002 ✓
- **Backend API**: http://localhost:8001 ✓
- **API 문서**: http://localhost:8001/docs
- **Easy Mode**: http://localhost:3002/easy

### Health Check

```bash
$ curl http://localhost:8001/health
{"status":"healthy"}

$ curl -I http://localhost:3002
HTTP/1.1 200 OK
```

---

## 🎨 UI 변경사항 (최신)

### 헤더
- **이전**: "AX Agent - AI 연구 데이터 어시스턴트"
- **현재**: "Easy 특허 Agent - 특허 맞춤형 AI 어시스턴트"

### 제거된 기능
- ❌ 통합검색 모드 탭 (AX/통합검색)
- ❌ 레거시 레벨 옵션 (초등/일반인/전문가)
- ❌ 불필요한 UI 요소

### 간소화된 기능
- ✅ 특허 전용 검색 (자동 고정)
- ✅ V3 리터러시 레벨만 표시 (L1-L6)
- ✅ 깔끔한 푸터

---

## 📊 V3 리터러시 레벨 시스템

| 레벨 | 대상 | 이모지 | 특징 |
|------|------|--------|------|
| **L1** | 초등학생 | 🎓 | 쉬운 말, 비유, 이모지 |
| **L2** | 대학생/일반인 | 📚 | 괄호 설명, 학술적 표현 |
| **L3** | 중소기업 실무자 | 💼 | 사업화, 경쟁사 분석 |
| **L4** | 연구자 | 🔬 | 기술 용어, 수치 범위 |
| **L5** | 변리사/심사관 | ⚖️ | 법률 용어, 권리범위 |
| **L6** | 정책담당자 | 📊 | 거시 지표, 국가별 비교 |

---

## 🚀 주요 기능

### 1. 사용자 프로필 생성
- 학력/직업 입력
- 자동 레벨 매핑
- 프로필 표시

**예시**:
```json
{
  "user_id": "demo_user",
  "education_level": "대학생",
  "occupation": "연구원"
  → "registered_level": "L4" (자동 매핑)
}
```

### 2. Easy Mode
- URL: http://localhost:3002/easy
- 6개 추천 질문 (🔋배터리, 🤖로봇, 🚗자동차 등)
- 큰 글씨, 친근한 UI
- L1 레벨 자동 적용

### 3. 레벨별 답변 차이

**동일 질문**: "전기차 배터리에 대해서 설명해줘"

**L1 응답**:
```
전기차 배터리는 마치 큰 건전지 같아요! 🔋
자동차를 움직이게 하는 에너지를 저장하는 곳이에요.
```

**L2 응답**:
```
전기차 배터리(Battery, 리튬이온 배터리)는 전기를 저장했다가
모터에 공급하여 차량을 구동하는 핵심 부품입니다.
```

**L4 응답**:
```
리튬이온 배터리(Li-ion Battery)
- 양극재: NCM811 (Ni:Co:Mn = 8:1:1)
- 에너지 밀도: 250-280 Wh/kg
- 충방전 사이클: 1,000-1,500회
```

---

## 🔧 API 엔드포인트

### 사용자 프로필

```bash
# 프로필 생성
curl -X POST http://localhost:8001/user/profile \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user",
    "education_level": "대학생",
    "occupation": "연구원"
  }'

# 프로필 조회
curl http://localhost:8001/user/profile/test_user

# 레벨 변경
curl -X POST http://localhost:8001/user/level/change \
  -d '{
    "user_id": "test_user",
    "new_level": "L5",
    "reason": "변리사 자격 취득"
  }'
```

### 채팅

```bash
# 스트리밍 채팅
curl -X POST http://localhost:8001/workflow/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "전기차 배터리",
    "session_id": "test",
    "level": "L2"
  }'
```

---

## 📝 최근 커밋

```
8bd3f35 fix: Remove entity_types parameter from streaming API calls
dc485da feat: Simplify UI and support V3 literacy levels
b2aad76 docs: Add Phase 2 UI implementation report
5f955e1 feat(frontend): Implement Phase 2 UI for v1.3 Literacy System
062c167 Add comprehensive literacy level integration tests
```

---

## 🗂️ 파일 구조

```
patent-ax/
├── api/
│   ├── main.py (user router 포함)
│   ├── streaming.py (V3 레벨 지원)
│   └── routers/
│       └── user.py (프로필 관리 API)
│
├── workflow/
│   ├── user/
│   │   └── level_mapper.py (레벨 매핑 로직)
│   ├── nodes/
│   │   └── generator.py (LEVEL_PROMPTS_V3)
│   └── state.py (entity_types=["patent"] 고정)
│
├── frontend/
│   ├── app/
│   │   ├── page.tsx (간소화된 메인 UI)
│   │   └── easy/
│   │       └── page.tsx (Easy Mode)
│   │
│   └── components/
│       ├── easy/
│       │   └── EasyChat.tsx (L1 채팅)
│       └── user/
│           ├── UserProfileForm.tsx
│           ├── UserProfileModal.tsx
│           └── UserProfileDisplay.tsx
│
└── docs/
    ├── PHASE2_UI_IMPLEMENTATION.md
    ├── USER_LITERACY_GUIDE.md
    └── IMPLEMENTATION_PLAN_USER_LITERACY.md
```

---

## 🎯 사용 시나리오

### 시나리오 1: 초등학생 사용자
1. http://localhost:3002/easy 접속
2. 🔋 배터리 버튼 클릭
3. "배터리는 마치 에너지 저장고 같아요!" 답변 받기

### 시나리오 2: 연구원 사용자
1. http://localhost:3002 접속
2. "프로필 생성" 클릭
3. 학력: 대학생, 직업: 연구원 입력
4. 자동으로 L4 레벨 할당
5. 기술 상세 답변 받기

### 시나리오 3: 변리사 사용자
1. 프로필에서 L5 선택
2. "특허 청구항 작성 방법" 질문
3. 법률 용어, 권리범위 중심 답변 받기

---

## 📊 성능 메트릭

- **Frontend 빌드 크기**: ~150 KB (First Load JS)
- **API 응답 시간**: 평균 2-5초 (LLM 생성 시간 포함)
- **레벨 매핑**: 즉시 (DB 조회)

---

## 🔒 보안 및 설정

### CORS
- Backend: `allow_origins=["*"]` (개발 환경)
- Production: 특정 도메인만 허용 필요

### 환경 변수

**Frontend** (`.env.local`):
```
NEXT_PUBLIC_API_URL=http://localhost:8001
```

**Backend** (`.env`):
```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ax
DB_USER=postgres
DB_PASSWORD=postgres

QDRANT_URL=http://210.109.80.106:6333
VLLM_BASE_URL=http://210.109.80.106:12288
KURE_API_URL=http://210.109.80.106:7000
```

---

## 📚 문서

- [Phase 2 구현 보고서](docs/PHASE2_UI_IMPLEMENTATION.md)
- [사용자 가이드](docs/USER_LITERACY_GUIDE.md)
- [구현 계획서](docs/IMPLEMENTATION_PLAN_USER_LITERACY.md)
- [서비스 정보](SERVICE_INFO.md)

---

## ✅ 완료된 Phase

### Phase 1: Backend 구현 ✓
- DB 테이블 생성 (f_user_profiles, f_patent_tech_elements)
- UserLevelMapper 클래스
- API 엔드포인트 (5개)
- LEVEL_PROMPTS_V3
- 통합 테스트 (23개 통과)

### Phase 2: Frontend 구현 ✓
- Easy Mode UI (/easy)
- V3 레벨 드롭다운
- 사용자 프로필 폼
- UI 간소화 (통합검색 제거)

---

## 🚧 다음 단계 (Phase 3)

- [ ] 관점별 요약 UI (목적/소재/공법/효과 탭)
- [ ] 사용자 대시보드
- [ ] 문서 업로드 및 자동 분석
- [ ] A/B 테스트
- [ ] 통계 대시보드

---

**버전**: v1.3
**상태**: 정상 구동 중
**최종 업데이트**: 2026-01-15
