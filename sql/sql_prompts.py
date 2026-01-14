"""
SQL 에이전트 프롬프트 템플릿
- 자연어 → SQL 변환 프롬프트
- 스키마 컨텍스트 포맷팅
- 결과 해석 프롬프트
"""

# SQL 생성 시스템 프롬프트 (Phase 35.3: 모듈화 - 토큰 최적화)
# Phase 53: 장비 검색 시 핵심 키워드만 사용하도록 규칙 추가
SQL_GENERATION_SYSTEM = """PostgreSQL 전문가. 자연어 질문을 SQL로 변환.

## 필수 규칙
1. SELECT만 사용 (INSERT/UPDATE/DELETE/DROP 금지)
2. 테이블명 쌍따옴표: "table_name"
3. 한글 검색: ILIKE '%키워드%'
4. LIMIT: 기본 10, 명시적 요청 시 해당 값, 전체 요청 시 100
5. 날짜 컬럼(ptnaplc_ymd, ancm_yy, srvc_open_ta_yy)은 TEXT → LEFT() 사용 (EXTRACT 금지)
   예: LEFT(ptnaplc_ymd, 4) as 연도
6. 복합 키워드: AND 조건 분리
   예: WHERE (conts_klang_nm ILIKE '%AI%' AND conts_klang_nm ILIKE '%반도체%')
7. 장비(f_equipments) 검색 규칙:
   - 핵심 키워드만 사용: "압축강도 측정 장비" → '%압축강도%' (측정, 장비, 리스트 제외)
   - 기관명 검색: "A기관 보유 장비" → org_nm ILIKE '%A기관%' (conts_klang_nm 아님!)
   - 일반 단어(측정, 시험, 장비, 추천, 리스트, 목록) 제외하고 기술/기관 키워드만 검색
   - WHERE 절: (conts_klang_nm ILIKE '%키워드%' OR org_nm ILIKE '%기관명%')
8. 특허(f_patents) 검색 규칙:
   - 필수 컬럼 포함: documentid, conts_klang_nm, ipc_main, ptnaplc_ymd, ntcd, patent_frst_appn
   - 출원인 정보(patent_frst_appn) 반드시 포함!
   - 회사명/기관명 검색 시 patent_frst_appn 필드 사용! (conts_klang_nm은 특허명)
   - 예시1 (기술 키워드만): WHERE conts_klang_nm ILIKE '%수소연료%'
   - 예시2 (회사+기술): WHERE patent_frst_appn ILIKE '%현대자동차%' AND conts_klang_nm ILIKE '%수소연료%'
   - 예시3 (회사 특허 전체): WHERE patent_frst_appn ILIKE '%삼성전자%'

## Phase 104.3: 기관 역량 검색 (기관별 집계) - 중요!
"역량 보유 기관", "개발 기관", "출원기관 TOP", "수행기관 TOP" 키워드 감지 시 **GROUP BY 집계 필수!**:

### 특허 출원기관 집계 (patent_frst_appn 기준)
SELECT p.patent_frst_appn as 기관명, COUNT(*) as 특허수,
       MIN(LEFT(p.ptnaplc_ymd, 4)) as 첫출원년도,
       MAX(LEFT(p.ptnaplc_ymd, 4)) as 최근출원년도
FROM "f_patents" p
WHERE p.conts_klang_nm ILIKE '%키워드%'
  AND p.patent_frst_appn IS NOT NULL AND p.patent_frst_appn <> ''
GROUP BY p.patent_frst_appn
ORDER BY 특허수 DESC LIMIT 20

### 과제 수행기관 집계 (f_proposal_orgn.orgn_nm + ptcp_orgn_role_se 역할 구분)
SELECT po.orgn_nm as 기관명, COUNT(DISTINCT po.sbjt_id) as 과제수,
       COUNT(CASE WHEN po.ptcp_orgn_role_se LIKE '%주관%' THEN 1 END) as 주관과제,
       COUNT(CASE WHEN po.ptcp_orgn_role_se LIKE '%참여%' THEN 1 END) as 참여과제
FROM "f_proposal_orgn" po
JOIN "f_proposal_profile" pp ON po.sbjt_id = pp.sbjt_id
WHERE pp.sbjt_nm ILIKE '%키워드%'
  AND po.orgn_nm IS NOT NULL AND po.orgn_nm <> ''
GROUP BY po.orgn_nm
ORDER BY 과제수 DESC LIMIT 20

## 동향 분석 쿼리 (trend_analysis) - 1개 쿼리만!
"~동향", "연구동향", "기술동향", "특허동향" 질문 시:
- 연도별 추이 쿼리 (세미콜론 없이 1개만 생성):
  SELECT LEFT(conts_ymd, 4) as 연도, COUNT(*) as 건수
  FROM "f_projects" WHERE conts_klang_nm ILIKE '%키워드%'
  GROUP BY LEFT(conts_ymd, 4) ORDER BY 연도 DESC

## 테이블 관계 (JOIN 시 참고)
- f_patents.documentid = f_patent_applicants.document_id
- f_proposal_profile.sbjt_id = f_proposal_techclsf.sbjt_id

## 출력
SQL만 출력. 마크다운/설명 없이.
"""

# SQL 생성 사용자 프롬프트 템플릿
SQL_GENERATION_USER = """## 데이터베이스 스키마
{schema}

{hints_section}## 사용자 질문
{question}

위 질문에 대한 SQL 쿼리를 작성하세요.
벡터 검색 힌트가 있으면 해당 키워드와 document ID를 적극 활용하세요.
"""

# 결과 해석 시스템 프롬프트
SQL_RESULT_INTERPRETATION_SYSTEM = """당신은 데이터 분석 전문가입니다.
SQL 쿼리 결과를 분석하여 사용자에게 친절하게 설명합니다.

## 답변 지침
1. 결과 데이터를 요약하여 핵심 내용을 먼저 설명하세요.
2. 숫자가 있으면 의미있는 통계를 제시하세요.
3. 결과가 없으면 그 이유를 추측해보세요.
4. 추가 분석이 가능하면 제안하세요.
5. 한국어로 답변하세요.
"""

# 결과 해석 사용자 프롬프트 템플릿
SQL_RESULT_INTERPRETATION_USER = """## 사용자 질문
{question}

## 실행된 SQL
{sql}

## 쿼리 결과 (상위 {row_count}개)
{result}

위 결과를 분석하여 사용자 질문에 답변하세요.
"""

# 테이블 선택 프롬프트
TABLE_SELECTION_SYSTEM = """당신은 데이터베이스 전문가입니다.
사용자 질문에 필요한 테이블을 선택합니다.

## 사용 가능한 테이블
{tables}

## 출력 형식
필요한 테이블명을 쉼표로 구분하여 출력하세요.
예: f_patents, f_patent_applicants
"""

# SQL 검증 프롬프트
SQL_VALIDATION_SYSTEM = """당신은 SQL 보안 전문가입니다.
SQL 쿼리의 안전성을 검증합니다.

## 검증 항목
1. SELECT 쿼리인가?
2. 위험한 키워드(DROP, DELETE, UPDATE, INSERT, TRUNCATE, ALTER, EXEC, EXECUTE)가 없는가?
3. 주석(-- 또는 /**/)이 없는가?
4. 세미콜론으로 여러 쿼리를 연결하지 않았는가?

## 출력
- 안전하면: SAFE
- 위험하면: UNSAFE: [이유]
"""


def build_sql_generation_prompt(question: str, schema: str, sql_hints: str = None) -> tuple:
    """SQL 생성 프롬프트 구성

    Args:
        question: 사용자 질문
        schema: 스키마 정보
        sql_hints: 벡터 검색 기반 SQL 힌트 (선택적)

    Returns:
        (system_prompt, user_prompt) 튜플
    """
    # 힌트 섹션 생성
    hints_section = ""
    if sql_hints:
        hints_section = f"{sql_hints}\n\n"

    user_prompt = SQL_GENERATION_USER.format(
        schema=schema,
        hints_section=hints_section,
        question=question
    )
    return SQL_GENERATION_SYSTEM, user_prompt


def build_result_interpretation_prompt(
    question: str,
    sql: str,
    result: str,
    row_count: int = 10
) -> tuple:
    """결과 해석 프롬프트 구성

    Args:
        question: 사용자 질문
        sql: 실행된 SQL
        result: 쿼리 결과 (텍스트)
        row_count: 결과 행 수

    Returns:
        (system_prompt, user_prompt) 튜플
    """
    user_prompt = SQL_RESULT_INTERPRETATION_USER.format(
        question=question,
        sql=sql,
        result=result,
        row_count=row_count
    )
    return SQL_RESULT_INTERPRETATION_SYSTEM, user_prompt


def format_query_result(columns: list, rows: list, max_rows: int = 10) -> str:
    """쿼리 결과를 텍스트로 포맷팅

    Args:
        columns: 컬럼명 리스트
        rows: 결과 행 리스트
        max_rows: 최대 표시 행 수

    Returns:
        포맷팅된 결과 문자열
    """
    if not rows:
        return "(결과 없음)"

    lines = []

    # 헤더
    lines.append(" | ".join(str(c) for c in columns))
    lines.append("-" * 80)

    # 데이터 행
    for i, row in enumerate(rows[:max_rows]):
        values = []
        for v in row:
            if v is None:
                values.append("NULL")
            elif isinstance(v, str) and len(v) > 50:
                values.append(v[:50] + "...")
            else:
                values.append(str(v))
        lines.append(" | ".join(values))

    if len(rows) > max_rows:
        lines.append(f"... (총 {len(rows)}개 중 {max_rows}개 표시)")

    return "\n".join(lines)


# 엔티티별 표준 컬럼 정의 (Phase 19/33: 실제 DB 컬럼 기반)
# DB 스키마 조회 결과를 반영하여 정확한 컬럼명 사용
ENTITY_COLUMNS = {
    "patent": {
        "table": "f_patents",
        "join_table": None,  # Phase 72.1: JOIN 제거 (중복 방지)
        "columns": ["documentid", "conts_klang_nm", "ipc_main", "ptnaplc_ymd", "ntcd", "patent_frst_appn"],
        "join_columns": [],
        "aliases": ["특허번호", "특허명", "IPC분류", "출원일", "등록국가", "최초출원인"],
        # Phase 72.1: JOIN 제거로 중복 방지, patent_frst_appn 사용
        # Phase 99.7: 회사명 검색 시 patent_frst_appn 필드도 검색
        "sql_template": """SELECT p.documentid as 특허번호, p.conts_klang_nm as 특허명,
       p.ipc_main as IPC분류, LEFT(p.ptnaplc_ymd, 4) as 출원년도,
       p.ntcd as 등록국가, p.patent_frst_appn as 최초출원인
FROM "f_patents" p
WHERE (p.conts_klang_nm ILIKE '%{keyword}%' OR p.patent_frst_appn ILIKE '%{keyword}%')
ORDER BY p.ptnaplc_ymd DESC
LIMIT 10"""
    },
    "project": {
        "table": "f_projects",
        "join_table": None,
        # Phase 36.1: 실제 DB 컬럼 확인 - orgn_nm 컬럼 없음
        # 사용 가능 컬럼: conts_id, conts_klang_nm, tot_rsrh_blgn_amt, ancm_yy, bucl_nm, ancm_tl_nm
        "columns": ["conts_id", "conts_klang_nm", "ancm_yy", "tot_rsrh_blgn_amt", "bucl_nm"],
        "join_columns": [],
        "aliases": ["과제ID", "과제명", "공고연도", "연구비", "사업분류"],
        "sql_template": """SELECT conts_id as 과제ID, conts_klang_nm as 과제명,
       ancm_yy as 공고연도, tot_rsrh_blgn_amt as 연구비, bucl_nm as 사업분류
FROM "f_projects"
WHERE conts_klang_nm ILIKE '%{keyword}%'
LIMIT 10"""
    },
    "proposal": {
        "table": "f_proposal_profile",
        "join_table": None,
        # 실제 DB 컬럼: sbjt_id, sbjt_nm, orgn_nm, dvlp_gole, rsrh_expn, ancm_yy
        "columns": ["sbjt_id", "sbjt_nm", "orgn_nm", "dvlp_gole", "rsrh_expn"],
        "join_columns": [],
        "aliases": ["제안서ID", "제안서명", "기관명", "개발목표", "연구비"],
        "sql_template": """SELECT sbjt_id as 제안서ID, sbjt_nm as 제안서명,
       orgn_nm as 기관명, dvlp_gole as 개발목표, rsrh_expn as 연구비
FROM "f_proposal_profile"
WHERE sbjt_nm ILIKE '%{keyword}%'
LIMIT 10"""
    },
    "equip": {
        "table": "f_equipments",
        "join_table": None,
        # Phase 56: 컬럼 재정의
        #   - kpi_nm_list(측정지표) → conts_mclas_nm(분야) 변경 (의미 명확화)
        #   - region_code(숫자코드) → address_dosi(지역명) 변경 (가독성 향상)
        # Phase 57: WHERE 절에서 kpi_nm_list 검색 제거
        #   - 확장 키워드가 측정지표(kpi_nm_list)에서 매칭되어 무관한 결과 반환 문제 해결
        # Phase 58: 기관명(org_nm) 검색 추가
        #   - "서울테크노파크 보유 장비" 등 기관 기반 검색 지원
        "columns": ["conts_id", "conts_klang_nm", "org_nm", "conts_mclas_nm", "equip_grp_lv2_nm", "address_dosi"],
        "join_columns": [],
        "aliases": ["장비ID", "장비명", "보유기관", "분야", "장비분류", "지역"],
        "sql_template": """SELECT conts_id as 장비ID, conts_klang_nm as 장비명,
       org_nm as 보유기관, conts_mclas_nm as 분야, equip_grp_lv2_nm as 장비분류, address_dosi as 지역
FROM "f_equipments"
WHERE (conts_klang_nm ILIKE '%{keyword}%' OR org_nm ILIKE '%{keyword}%')
LIMIT 10"""
    },
    # Phase 48: evalp 두 가지 조회 방식
    # 1. evalp: 평가표 목록 조회 (요약)
    # 2. evalp_detail: 특정 평가표의 세부 항목 조회 (개별 행)
    "evalp": {
        "table": "f_ancm_evalp",
        "join_table": None,
        # Phase 46: 평가표 단위 그룹핑 (평가지표+배점 통합, 최신순 정렬)
        # Phase 48: 세부 항목 요청 시 evalp_detail 사용
        # 실제 DB 컬럼: evalp_id(평가표명), eval_idx_nm(평가지표), eval_score(배점), vlid_srt_ymd(연도)
        "columns": ["evalp_id", "항목수", "총배점", "평가항목", "연도"],
        "join_columns": [],
        "aliases": ["평가표명", "항목수", "총배점", "평가항목", "연도"],
        "sql_template": """SELECT
    evalp_id as 평가표명,
    COUNT(*) as 항목수,
    SUM(CAST(NULLIF(eval_score, '') AS INTEGER)) as 총배점,
    STRING_AGG(eval_idx_nm || ' (' || COALESCE(eval_score, '-') || '점)', ' | ' ORDER BY eval_score DESC) as 평가항목,
    MAX(vlid_srt_ymd) as 연도
FROM "f_ancm_evalp"
WHERE (evalp_id ILIKE '%{keyword}%' OR ancm_nm ILIKE '%{keyword}%')
  AND eval_idx_nm IS NOT NULL AND eval_idx_nm <> ''
GROUP BY evalp_id
ORDER BY MAX(vlid_srt_ymd) DESC NULLS LAST
LIMIT 10"""
    },
    # Phase 48: 평가표 세부 항목 조회 (개별 평가지표별 행)
    "evalp_detail": {
        "table": "f_ancm_evalp",
        "join_table": None,
        # 특정 평가표의 전체 평가항목을 개별 행으로 조회
        "columns": ["evalp_id", "eval_idx_nm", "eval_score", "eval_note"],
        "join_columns": [],
        "aliases": ["평가표명", "평가지표", "배점", "비고"],
        "sql_template": """SELECT
    evalp_id as 평가표명,
    eval_idx_nm as 평가지표,
    COALESCE(eval_score, '-') as 배점,
    COALESCE(eval_note, '-') as 비고
FROM "f_ancm_evalp"
WHERE (evalp_id ILIKE '%{keyword}%' OR ancm_nm ILIKE '%{keyword}%')
  AND eval_idx_nm IS NOT NULL AND eval_idx_nm <> ''
ORDER BY evalp_id, CAST(NULLIF(eval_score, '') AS INTEGER) DESC NULLS LAST
LIMIT 50"""
    },
    "ancm": {
        "table": "f_ancm_prcnd",
        "join_table": None,
        # 실제 DB 컬럼: ancm_id, ancm_tl_nm, ancm_ymd, bucl_nm, prcnd_yn
        "columns": ["ancm_id", "ancm_tl_nm", "ancm_ymd", "bucl_nm", "prcnd_yn"],
        "join_columns": [],
        "aliases": ["공고ID", "공고명", "공고일자", "사업분류", "조건여부"],
        "sql_template": """SELECT ancm_id as 공고ID, ancm_tl_nm as 공고명,
       ancm_ymd as 공고일자, bucl_nm as 사업분류, prcnd_yn as 조건여부
FROM "f_ancm_prcnd"
WHERE ancm_tl_nm ILIKE '%{keyword}%' OR bucl_nm ILIKE '%{keyword}%'
LIMIT 10"""
    },
    "tech": {
        "table": "f_proposal_techclsf",
        "join_table": None,
        # 실제 DB 컬럼: sbjt_id, tecl_cd, tecl_nm, tecl_nm_tree
        "columns": ["tecl_cd", "tecl_nm", "tecl_nm_tree"],
        "join_columns": [],
        "aliases": ["기술코드", "기술명", "기술트리"],
        "sql_template": """SELECT tecl_cd as 기술코드, tecl_nm as 기술명, tecl_nm_tree as 기술트리
FROM "f_proposal_techclsf"
WHERE tecl_nm ILIKE '%{keyword}%'
GROUP BY tecl_cd, tecl_nm, tecl_nm_tree
LIMIT 10"""
    }
}

# 엔티티별 한글 라벨
ENTITY_LABELS = {
    "patent": "특허",
    "project": "연구과제",
    "proposal": "제안서",
    "equip": "연구장비",
    "evalp": "평가표/배점표",
    "evalp_detail": "평가표 세부항목",  # Phase 48
    "ancm": "사업공고",
    "tech": "기술분류"
}


# Phase 35.3: EXAMPLE_QUERIES 제거됨 (토큰 절약)
# 엔티티별 sql_template은 ENTITY_COLUMNS에서 제공

# Phase 104.3: 기관별 집계 쿼리 템플릿 (역량 보유 기관 검색)
ORGANIZATION_AGGREGATION_TEMPLATES = {
    "patent": {
        "description": "특허 출원기관별 집계",
        "sql_template": """SELECT
    p.patent_frst_appn as 기관명,
    COUNT(*) as 특허수,
    MIN(LEFT(p.ptnaplc_ymd, 4)) as 첫출원년도,
    MAX(LEFT(p.ptnaplc_ymd, 4)) as 최근출원년도,
    STRING_AGG(DISTINCT p.ipc_main, ', ' ORDER BY p.ipc_main) as 주요IPC
FROM "f_patents" p
WHERE (p.conts_klang_nm ILIKE '%{keyword}%' OR p.patent_frst_appn ILIKE '%{keyword}%')
  AND p.patent_frst_appn IS NOT NULL
  AND p.patent_frst_appn <> ''
GROUP BY p.patent_frst_appn
ORDER BY 특허수 DESC
LIMIT 20""",
        "aliases": ["기관명", "특허수", "첫출원년도", "최근출원년도", "주요IPC"]
    },
    "project": {
        "description": "과제 수행기관별 집계",
        "sql_template": """SELECT
    po.orgn_nm as 기관명,
    COUNT(DISTINCT po.sbjt_id) as 과제수,
    COUNT(CASE WHEN po.ptcp_orgn_role_se LIKE '%주관%' THEN 1 END) as 주관과제,
    COUNT(CASE WHEN po.ptcp_orgn_role_se LIKE '%참여%' THEN 1 END) as 참여과제
FROM "f_proposal_orgn" po
JOIN "f_proposal_profile" pp ON po.sbjt_id = pp.sbjt_id
WHERE pp.sbjt_nm ILIKE '%{keyword}%'
  AND po.orgn_nm IS NOT NULL
  AND po.orgn_nm <> ''
GROUP BY po.orgn_nm
ORDER BY 과제수 DESC
LIMIT 20""",
        "aliases": ["기관명", "과제수", "대표과제"]
    },
    "proposal": {
        "description": "제안서 참여기관별 집계",
        "sql_template": """SELECT
    pp.orgn_nm as 기관명,
    COUNT(*) as 제안수,
    SUM(COALESCE(CAST(NULLIF(pp.rsrh_expn, '') AS BIGINT), 0)) as 총연구비
FROM "f_proposal_profile" pp
WHERE pp.sbjt_nm ILIKE '%{keyword}%'
  AND pp.orgn_nm IS NOT NULL
  AND pp.orgn_nm <> ''
GROUP BY pp.orgn_nm
ORDER BY 제안수 DESC
LIMIT 20""",
        "aliases": ["기관명", "제안수", "총연구비"]
    }
}


# Phase 62: 분류체계 유형 매핑 (사용자 요청 → DB 코드)
# f_proposal_techclsf 테이블의 cd_nm (분류체계명) 기반 정확한 매핑
CLASSIFICATION_TYPE_MAPPING = {
    # 신산업기술분류코드 - SAF006 (가장 많이 사용: 77,500건)
    "신산업기술분류": "SAF006",
    "신산업기술분류코드": "SAF006",
    "신산업": "SAF006",

    # 6T 기술분류 - SAF002 (51,980건)
    "6T": "SAF002",
    "6t": "SAF002",
    "6T_CODE": "SAF002",
    "6T기술분류": "SAF002",

    # 국가과학기술표준분류 - SAF047 (55,405건)
    "국가과학기술표준분류": "SAF047",
    "과학기술표준분류": "SAF047",
    "KISTEP": "SAF047",

    # 10대기술분야 - SAF041 (45,006건)
    "10대기술분야": "SAF041",
    "10대기술": "SAF041",
    "K12": "SAF041",
    "k12": "SAF041",

    # 한국표준산업분류 - SAF040 (45,774건)
    "한국표준산업분류": "SAF040",
    "산업분류": "SAF040",

    # 적용분야 - SAF037 (47,996건)
    "적용분야": "SAF037",
}

# 분류체계 한글 라벨 (cd_nm 기반)
CLASSIFICATION_TYPE_LABELS = {
    "SAF006": "신산업기술분류코드",
    "SAF002": "6T 기술분류",
    "SAF047": "국가과학기술표준분류(2018년)",
    "SAF041": "10대기술분야",
    "SAF040": "한국표준산업분류",
    "SAF037": "적용분야",
    "SAF045": "신성장분야 전략기술분류(2017년)",
    "SAF048": "중점과학기술분류",
    "SAF036": "NTIS 과학기술분류",
    "SAF043": "국가기술지도분류",
}
