# Patent-AX Agent

특허 데이터 전문 AI 검색 시스템 (LangGraph + Graph RAG + 벡터 검색)

---

## 개요

Patent-AX는 **특허 데이터만을 대상으로 하는 AI 기반 질의응답 시스템**입니다.
기존 AX Agent 통합 시스템에서 특허 도메인만을 분리하여 독립적으로 운영됩니다.

### 주요 기능

1. **벡터 검색 (Qdrant)**: 의미론적 유사도 기반 특허 검색
2. **Graph RAG (cuGraph)**: 그래프 탐색을 통한 연관 특허/출원인 발견
3. **SQL 분석 (PostgreSQL)**: 구조화된 특허 데이터 통계 분석
4. **리터러시 레벨**: 사용자 수준별 맞춤 답변 생성 (초등/일반인/전문가)

### 지원 데이터

- **특허**: 약 120만 건 (f_patents)
- **출원인**: 약 60만 건 (f_patent_applicants)
- **벡터 컬렉션**: patents_v3_collection (1.82M points)
- **그래프 노드**: patent, applicant, ipc, org

---

## 빠른 시작

### 1. 환경 설정

```bash
cp .env.example .env
vim .env
```

### 2. 의존성 설치

```bash
# Python
pip install -r requirements.txt

# Frontend
cd frontend && npm install
```

### 3. 실행

```bash
# 백엔드
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 프론트엔드
cd frontend && npm run dev
```

---

## 기술 스택

| 구성요소 | 기술 | 비고 |
|----------|------|------|
| LLM | EXAONE-4.0.1-32B (vLLM) | 포트 12288 |
| 벡터 DB | Qdrant v1.7.4 | 포트 6333 |
| 임베딩 | KURE API (1024-dim) | 포트 7000 |
| 그래프 | cuGraph (GPU) | 포트 8000 |
| RDBMS | PostgreSQL 15 | 포트 5432 |
| 워크플로우 | LangGraph | - |
| 백엔드 | FastAPI | 포트 8000 |
| 프론트엔드 | Next.js 14 | 포트 3000 |

---

## 프로젝트 구조

```
patent-ax/
├── api/                    # FastAPI 백엔드 (상세: api/README.md)
├── workflow/               # LangGraph 워크플로우 (상세: workflow/README.md)
├── frontend/               # Next.js 프론트엔드 (상세: frontend/README.md)
├── sql/                    # SQL 쿼리 생성
├── graph/                  # cuGraph 래퍼
├── llm/                    # LLM 클라이언트
├── embedding/              # 벡터 임베딩
└── tests/                  # 테스트
```

각 하위 폴더의 README.md에서 상세 구조와 구현 내용을 확인하세요.

---

## 테스트

```bash
# 단위 테스트
pytest tests/

# 프론트엔드 빌드 검증
cd frontend && npm run build
```

---

## 문서

- [프론트엔드 가이드](frontend/README.md)
- [워크플로우 가이드](workflow/README.md)
- [API 가이드](api/README.md)

---

## 라이선스

(프로젝트 라이선스 명시)
