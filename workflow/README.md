# Workflow (LangGraph)

특허 AI 검색 시스템 워크플로우 엔진

## 노드 구조

```
질의 입력
    ↓
[Analyzer] 질의 분석 → entity_types=["patent"]
    ↓
[SQL Executor] PostgreSQL 쿼리 실행
    ↓
[RAG Retriever] Qdrant 벡터 + cuGraph 탐색
    ↓
[Generator] EXAONE 기반 답변 생성 + 관점별 요약
    ↓
최종 응답
```

## 디렉토리 구조

```
workflow/
├── nodes/
│   ├── analyzer.py        # 질의 분석
│   ├── sql_executor.py    # SQL 실행
│   ├── rag_retriever.py   # RAG 검색
│   └── generator.py       # 답변 생성
├── loaders/               # 특허 전용 Loader
├── prompts/               # 프롬프트 템플릿
├── state.py               # AgentState 정의
└── graph.py               # 워크플로우 그래프
```

## 주요 기능

### 리터러시 레벨
- L1: 초등학생 (쉬운 용어, 이모지)
- L2: 대학생/일반인
- L3: 중소기업 실무자
- L4: 연구자
- L5: 변리사/심사관
- L6: 정책담당자

### 관점별 요약 (perspective_summary)
특허 문서의 원본 데이터 + 레벨별 부연 설명 생성
- purpose: 목적 (objectko 기반)
- material: 소재 (solutionko 기반)
- method: 공법 (solutionko 기반)
- effect: 효과 (초록 기반)
