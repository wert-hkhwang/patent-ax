# Patent-AX 사용자 리터러시 레벨 시스템 사용 가이드

## 개요

Patent-AX v1.3은 사용자의 특허 리터러시 수준에 맞춤화된 응답을 제공합니다.

## 리터러시 레벨 (6단계)

| 레벨 | 대상 | 설명 | 특징 |
|------|------|------|------|
| **L1** | 초등/중학생 | 쉬운 설명 | 쉬운 말, 비유, 이모지 🔋 |
| **L2** | 대학생/일반인 | 기본 설명 | 괄호 설명, 학술적 표현 |
| **L3** | 중소기업 실무자 | 실무 중심 | 사업화, 경쟁사 분석 |
| **L4** | 연구자 | 기술 상세 | 기술 용어, 수치 범위 |
| **L5** | 변리사/심사관 | 전문가 | 법률 용어, 권리범위 |
| **L6** | 정책담당자 | 정책 동향 | 거시 지표, 국가별 비교 |

## API 사용법

### 1. 사용자 프로필 생성

```bash
curl -X POST "http://localhost:8000/user/profile" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_001",
    "education_level": "대학생",
    "occupation": "연구원"
  }'
```

**응답**:
```json
{
  "id": 1,
  "user_id": "user_001",
  "education_level": "대학생",
  "occupation": "연구원",
  "registered_level": "L4",
  "current_level": "L4",
  "level_description": "기술 상세 (연구자)"
}
```

### 2. 프로필 조회

```bash
curl "http://localhost:8000/user/profile/user_001"
```

### 3. 레벨 수동 변경

```bash
curl -X POST "http://localhost:8000/user/level/change" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_001",
    "new_level": "L5",
    "reason": "변리사 자격 취득"
  }'
```

### 4. 레벨별 통계

```bash
curl "http://localhost:8000/user/level/statistics"
```

**응답**:
```json
{
  "statistics": {
    "L1": 5,
    "L2": 120,
    "L3": 45,
    "L4": 80,
    "L5": 30,
    "L6": 10
  },
  "total": 290
}
```

### 5. 레벨 정보 조회

```bash
curl "http://localhost:8000/user/level/info"
```

## 특허 검색 시 레벨 적용

### Workflow API 사용

```bash
curl -X POST "http://localhost:8000/workflow/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "양자컴퓨터 특허",
    "session_id": "session_001",
    "level": "L4"
  }'
```

### 레벨별 응답 예시

**동일 질문**: "배터리 양극재 특허"

**L1 (초등학생) 응답**:
```
배터리에서 전기를 만드는 물질인 양극재에 대한 특허를 찾았어요! 🔋

이 기술은 마치 휴대폰 배터리를 더 오래 쓸 수 있게 하는 거예요.
삼성과 LG 같은 회사들이 만들었답니다.
```

**L2 (대학생) 응답**:
```
양극재(Cathode material, 배터리의 양극 활물질)에 관한 특허를 검색했습니다.

NCM811(니켈:코발트:망간 = 8:1:1 비율의 삼원계 양극재)이 주요 기술로,
리튬이온 배터리는 양극재, 음극재, 전해질로 구성되며...
```

**L4 (연구자) 응답**:
```
NCM811 양극재 (Ni 0.8, Co 0.1, Mn 0.1 비율)
IPC H01M 4/525 (리튬 복합산화물 양극 활물질)

에너지 밀도 280 Wh/kg, 충방전 사이클 1,500회
X-ray 회절 분석 결과, 결정 구조는 층상 구조(Layered)
```

**L5 (변리사) 응답**:
```
특허법 제29조 제2항(진보성) 검토 필요

청구항 1의 구성요소 A는 선행기술 KR10-2020-0001234의 실시예 1과 동일
권리범위 해석: 구성요소 B는 균등론 적용 가능
```

**L6 (정책담당자) 응답**:
```
IPC H01M 분야는 중국이 특허 출원 1위(연 3만 건), 한국 2위(1.5만 건)
양극재 시장은 2030년까지 50조 원 규모로 성장 전망(CAGR 15%)

한·중·일 배터리 3국 경쟁 구도:
- 한국: 고용량 기술 우위
- 일본: 안전성 중심
- 중국: 저가 대량생산
```

## 학력/직업 매핑 규칙

### 학력 기반
- 초등학생, 중학생 → **L1**
- 고등학생, 대학생, 석사 → **L2**
- 박사 → **L4**

### 직업 기반 (우선순위 높음)
- 중소기업_실무자, 스타트업_실무자 → **L3**
- 연구원, 대기업_R&D, 출연연_연구원 → **L4**
- 변리사, 심사관, 특허전문가 → **L5**
- 정책담당자, 정부부처_담당자 → **L6**

## 데이터베이스 스키마

### f_user_profiles

```sql
CREATE TABLE f_user_profiles (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(100) UNIQUE NOT NULL,
    education_level VARCHAR(50),
    occupation VARCHAR(50),
    registered_level VARCHAR(20) NOT NULL,  -- 가입 시 설정
    current_level VARCHAR(20) NOT NULL,     -- UI에서 변경 가능
    level_change_history JSONB,             -- 변경 이력
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Python 코드 예시

### UserLevelMapper 사용

```python
from workflow.user.level_mapper import UserLevelMapper

# 초기 레벨 결정
mapper = UserLevelMapper()
level = mapper.get_initial_level(
    education_level="대학생",
    occupation="연구원"
)
print(level)  # "L4"

# 프로필 생성
profile = mapper.create_user_profile(
    user_id="user_001",
    education_level="대학생",
    occupation="연구원"
)

# 레벨 변경
updated = mapper.update_current_level(
    user_id="user_001",
    new_level="L5",
    reason="변리사 자격 취득"
)
```

## 프롬프트 구조

### LEVEL_PROMPTS_V3

```python
from workflow.nodes.generator import LEVEL_PROMPTS_V3, TOKEN_LIMITS_V3

# L1 프롬프트 확인
print(LEVEL_PROMPTS_V3["L1"])

# 토큰 제한 확인
print(TOKEN_LIMITS_V3)
# {'L1': 1000, 'L2': 2000, 'L3': 2500, 'L4': 3500, 'L5': 4000, 'L6': 2500}
```

## 테스트

### 전체 테스트 실행

```bash
# 유닛 테스트
pytest tests/test_user_level_mapper.py -v

# 통합 테스트
pytest tests/test_literacy_level_integration.py -v

# 전체 테스트
pytest tests/test_user_level_mapper.py tests/test_literacy_level_integration.py -v
```

### 결과

```
TestUserLevelMapper: 6 passed
TestUserProfileDatabase: 5 passed
TestLevelPromptsV3: 5 passed
TestBackwardCompatibility: 2 passed
TestLevelProgression: 2 passed
TestPromptExamples: 1 passed
TestIntegrationMock: 2 passed

Total: 23 passed
```

## 문제 해결

### 1. 프로필 생성 실패

**증상**: `User not found` 에러

**해결**:
```python
# 먼저 프로필 생성
mapper.create_user_profile(user_id="user_001", education_level="대학생")
```

### 2. 잘못된 레벨

**증상**: `Invalid level: L99`

**해결**:
```python
# 유효한 레벨만 사용: L1, L2, L3, L4, L5, L6
valid_levels = ["L1", "L2", "L3", "L4", "L5", "L6"]
```

### 3. DB 연결 실패

**해결**:
```bash
# .env 파일 확인
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ax
DB_USER=postgres
DB_PASSWORD=postgres
```

## 참고 자료

- [구현 계획서](/root/patent-ax/docs/IMPLEMENTATION_PLAN_USER_LITERACY.md)
- [API 문서](http://localhost:8000/docs)
- [테스트 코드](/root/patent-ax/tests/)

---

**버전**: v1.3
**최종 수정**: 2026-01-15
**작성자**: Claude Code Agent
