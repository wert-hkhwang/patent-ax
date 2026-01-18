# 별첨 B. 데이터베이스 스키마

> Patent-AX 기술 백서 별첨

---

## 1. 데이터베이스 개요

| 항목 | 값 |
|------|-----|
| DBMS | PostgreSQL 15 |
| Database | ax |
| 스키마 | public |
| 인코딩 | UTF-8 |

---

## 2. 테이블 목록

### 2.1 핵심 테이블

| 테이블 | 설명 | 레코드 수 |
|--------|------|----------|
| f_patents | 특허 정보 | 1,200,000 |
| f_patent_applicants | 출원인 정보 | 600,000 |
| f_applicant_address | 출원인 주소 | 500,000 |

### 2.2 정규화 테이블 (그래프 엣지)

| 테이블 | 설명 | 레코드 수 |
|--------|------|----------|
| patent_ipc_normalized | IPC 분류 정규화 | 3,500,000 |
| patent_inventor_normalized | 발명자 정규화 | 2,000,000 |

---

## 3. 상세 스키마

### 3.1 f_patents (특허 정보)

```sql
CREATE TABLE f_patents (
    documentid VARCHAR(50) PRIMARY KEY,
    conts_klang_nm TEXT,                  -- 특허명 (한글)
    ipc_main VARCHAR(20),                 -- 주 IPC 분류
    ipc_all TEXT,                         -- 전체 IPC 분류
    patent_abstc_ko TEXT,                 -- 초록 (한글)
    objectko TEXT,                        -- 해결과제
    solutionko TEXT,                      -- 해결수단
    ptnaplc_ymd DATE,                     -- 출원일
    patent_rgstn_ymd DATE,                -- 등록일
    org_nm VARCHAR(200),                  -- 출원인 기관명
    org_busir_no VARCHAR(20),             -- 사업자등록번호
    ntcd VARCHAR(10),                     -- 국가코드 (KR, US, JP, CN)
    patent_status VARCHAR(50),            -- 특허 상태
    claim_count INTEGER,                  -- 청구항 수
    citation_count INTEGER,               -- 피인용 횟수
    created_at TIMESTAMP DEFAULT NOW()
);

-- 인덱스
CREATE INDEX idx_patents_ipc ON f_patents(ipc_main);
CREATE INDEX idx_patents_date ON f_patents(ptnaplc_ymd);
CREATE INDEX idx_patents_org ON f_patents(org_nm);
CREATE INDEX idx_patents_ntcd ON f_patents(ntcd);
```

**주요 컬럼 설명**

| 컬럼 | 타입 | 설명 | 예시 |
|------|------|------|------|
| documentid | VARCHAR | 특허 고유 ID | KR10-2023-0001234 |
| ipc_main | VARCHAR | 주 IPC 분류 코드 | H01M-010/05 |
| patent_abstc_ko | TEXT | 특허 초록 (한글) | 본 발명은... |
| objectko | TEXT | 해결하고자 하는 과제 | 기존 배터리의 문제점... |
| solutionko | TEXT | 과제 해결 수단 | 이를 해결하기 위해... |
| ptnaplc_ymd | DATE | 출원일 | 2023-01-15 |
| ntcd | VARCHAR | 국가코드 | KR, US, JP, CN |

---

### 3.2 f_patent_applicants (출원인 정보)

```sql
CREATE TABLE f_patent_applicants (
    id SERIAL PRIMARY KEY,
    document_id VARCHAR(50) REFERENCES f_patents(documentid),
    applicant_name VARCHAR(300),          -- 출원인 이름
    applicant_code VARCHAR(50),           -- 출원인 코드
    applicant_country VARCHAR(10),        -- 출원인 국가
    applicant_order INTEGER,              -- 출원인 순서
    applicant_type VARCHAR(20),           -- 개인/법인
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_applicants_doc ON f_patent_applicants(document_id);
CREATE INDEX idx_applicants_name ON f_patent_applicants(applicant_name);
```

---

### 3.3 f_applicant_address (출원인 주소)

```sql
CREATE TABLE f_applicant_address (
    id SERIAL PRIMARY KEY,
    document_id VARCHAR(50),
    busir_no VARCHAR(20),                 -- 사업자등록번호
    corp_no VARCHAR(20),                  -- 법인등록번호
    address TEXT,                         -- 주소
    zipcode VARCHAR(10),                  -- 우편번호
    region VARCHAR(50),                   -- 지역
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

### 3.4 patent_ipc_normalized (IPC 정규화)

```sql
CREATE TABLE patent_ipc_normalized (
    id SERIAL PRIMARY KEY,
    documentid VARCHAR(50) REFERENCES f_patents(documentid),
    ipc_code VARCHAR(20),                 -- IPC 코드
    ipc_name VARCHAR(200),                -- IPC 명칭
    ipc_level INTEGER,                    -- 분류 레벨 (1-4)
    is_main BOOLEAN DEFAULT FALSE,        -- 주 분류 여부
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_ipc_doc ON patent_ipc_normalized(documentid);
CREATE INDEX idx_ipc_code ON patent_ipc_normalized(ipc_code);
```

**IPC 분류 체계**

| 레벨 | 예시 | 설명 |
|------|------|------|
| 1 | H | 섹션 (전기) |
| 2 | H01 | 클래스 (기본 전기 소자) |
| 3 | H01M | 서브클래스 (전지) |
| 4 | H01M-010/05 | 메인그룹/서브그룹 |

---

### 3.5 patent_inventor_normalized (발명자 정규화)

```sql
CREATE TABLE patent_inventor_normalized (
    id SERIAL PRIMARY KEY,
    documentid VARCHAR(50) REFERENCES f_patents(documentid),
    inventor_name VARCHAR(200),           -- 발명자 이름
    inventor_code VARCHAR(50),            -- 발명자 코드
    inventor_order INTEGER,               -- 발명자 순서
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_inventor_doc ON patent_inventor_normalized(documentid);
CREATE INDEX idx_inventor_name ON patent_inventor_normalized(inventor_name);
```

---

## 4. ER 다이어그램

```
┌─────────────────────┐
│     f_patents       │
├─────────────────────┤
│ documentid (PK)     │◄──────┐
│ conts_klang_nm      │       │
│ ipc_main            │       │
│ patent_abstc_ko     │       │
│ ptnaplc_ymd         │       │
│ org_nm              │       │
└─────────────────────┘       │
          │                   │
          │ 1:N               │ 1:N
          ▼                   │
┌─────────────────────┐       │
│ f_patent_applicants │       │
├─────────────────────┤       │
│ document_id (FK)    │───────┤
│ applicant_name      │       │
│ applicant_country   │       │
└─────────────────────┘       │
                              │
┌─────────────────────┐       │
│patent_ipc_normalized│       │
├─────────────────────┤       │
│ documentid (FK)     │───────┤
│ ipc_code            │       │
│ ipc_name            │       │
└─────────────────────┘       │
                              │
┌─────────────────────┐       │
│patent_inventor_norm │       │
├─────────────────────┤       │
│ documentid (FK)     │───────┘
│ inventor_name       │
│ inventor_code       │
└─────────────────────┘
```

---

## 5. 자주 사용되는 쿼리

### 5.1 특허 목록 조회

```sql
SELECT
    p.documentid,
    p.conts_klang_nm AS title,
    p.ipc_main,
    p.ptnaplc_ymd AS application_date,
    a.applicant_name
FROM f_patents p
LEFT JOIN f_patent_applicants a
    ON p.documentid = a.document_id
    AND a.applicant_order = 1
WHERE p.ipc_main LIKE 'H01M%'
ORDER BY p.ptnaplc_ymd DESC
LIMIT 10;
```

### 5.2 출원인별 특허 건수

```sql
SELECT
    applicant_name,
    COUNT(*) AS patent_count
FROM f_patent_applicants
GROUP BY applicant_name
ORDER BY patent_count DESC
LIMIT 10;
```

### 5.3 연도별 출원 추이

```sql
SELECT
    EXTRACT(YEAR FROM ptnaplc_ymd) AS year,
    COUNT(*) AS count
FROM f_patents
WHERE ptnaplc_ymd >= '2018-01-01'
GROUP BY year
ORDER BY year;
```

### 5.4 IPC 분류별 통계

```sql
SELECT
    SUBSTRING(ipc_main, 1, 4) AS ipc_class,
    COUNT(*) AS patent_count
FROM f_patents
WHERE ipc_main IS NOT NULL
GROUP BY ipc_class
ORDER BY patent_count DESC
LIMIT 10;
```

### 5.5 특허 상세 정보 조회

```sql
SELECT
    p.documentid,
    p.conts_klang_nm AS title,
    p.patent_abstc_ko AS abstract,
    p.objectko AS problem,
    p.solutionko AS solution,
    p.ipc_main,
    p.ptnaplc_ymd,
    p.patent_rgstn_ymd,
    STRING_AGG(DISTINCT a.applicant_name, ', ') AS applicants,
    STRING_AGG(DISTINCT i.inventor_name, ', ') AS inventors
FROM f_patents p
LEFT JOIN f_patent_applicants a ON p.documentid = a.document_id
LEFT JOIN patent_inventor_normalized i ON p.documentid = i.documentid
WHERE p.documentid = 'KR10-2023-0001234'
GROUP BY p.documentid;
```

---

## 6. 벡터 데이터 (Qdrant)

### 6.1 컬렉션 정보

| 항목 | 값 |
|------|-----|
| 컬렉션명 | patents_v3_collection |
| 벡터 차원 | 1024 |
| 포인트 수 | 1,820,000 |
| 데이터 크기 | 9.4 GB |
| 임베딩 모델 | KURE (BGE-M3 기반) |

### 6.2 페이로드 구조

```json
{
  "documentid": "KR10-2023-0001234",
  "title": "리튬이온 배터리 제조방법",
  "ipc_main": "H01M-010/05",
  "applicant": "삼성SDI",
  "application_date": "2023-01-15",
  "content": "본 발명은 리튬이온 배터리의..."
}
```

### 6.3 검색 예시

```python
# Python (qdrant-client)
from qdrant_client import QdrantClient

client = QdrantClient(url="http://210.109.80.106:6333")

results = client.search(
    collection_name="patents_v3_collection",
    query_vector=embedding,  # 1024-dim
    limit=10,
    query_filter={
        "must": [
            {"key": "ipc_main", "match": {"text": "H01M"}}
        ]
    }
)
```

---

## 7. 데이터 갱신 주기

| 데이터 | 갱신 주기 | 방법 |
|--------|----------|------|
| f_patents | 월 1회 | 특허청 API |
| 벡터 인덱스 | 월 1회 | KURE 재임베딩 |
| IPC 정규화 | 분기 1회 | ETL 파이프라인 |

---

## 8. 백업 정책

| 대상 | 방법 | 주기 | 보관 기간 |
|------|------|------|----------|
| PostgreSQL | pg_dump | 일 1회 | 30일 |
| Qdrant | 스냅샷 | 주 1회 | 4주 |

**스냅샷 위치**
```
/root/AX_BACKUP/qdrant_snapshots/patents_v3_collection.snapshot
```
