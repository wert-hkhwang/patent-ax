-- EP-Agent: risegpt에서 ax로 f_ 테이블 복사
-- dblink를 사용하여 테이블 복사

-- dblink 연결 설정
CREATE EXTENSION IF NOT EXISTS dblink;

-- 각 테이블을 복사 (백업 테이블 제외)
-- 1. f_kpi (가장 작은 테이블부터)
DROP TABLE IF EXISTS f_kpi CASCADE;
CREATE TABLE f_kpi AS
SELECT * FROM dblink(
    'dbname=risegpt user=postgres password=postgres host=localhost',
    'SELECT * FROM f_kpi'
) AS t(
    id INTEGER,
    kpi_data TEXT,
    created_at TIMESTAMP
);

-- 2. f_ancm_evalp
DROP TABLE IF EXISTS f_ancm_evalp CASCADE;
CREATE TABLE f_ancm_evalp AS
SELECT * FROM dblink(
    'dbname=risegpt user=postgres password=postgres host=localhost',
    'SELECT * FROM f_ancm_evalp'
) AS t(
    id INTEGER,
    eval_idx_nm TEXT,
    bucl_cd TEXT,
    bucl_depth1_nm TEXT,
    bucl_depth2_nm TEXT,
    bucl_depth3_nm TEXT,
    bucl_depth4_nm TEXT,
    col27 TEXT,
    col28 TEXT,
    col29 TEXT,
    col30 TEXT
);

-- 3. f_ancm_prcnd
DROP TABLE IF EXISTS f_ancm_prcnd CASCADE;
CREATE TABLE f_ancm_prcnd AS
SELECT * FROM dblink(
    'dbname=risegpt user=postgres password=postgres host=localhost',
    'SELECT * FROM f_ancm_prcnd'
) AS t(
    id INTEGER,
    ancm_id TEXT,
    ancm_yy TEXT,
    ancm_tl_nm TEXT,
    prcnd_se_cd TEXT,
    prcnd_se_nm TEXT,
    prcnd_cn TEXT,
    pref_gd TEXT,
    pref_dmrk_max_gd TEXT,
    bucl_cd TEXT,
    bucl_depth1_nm TEXT,
    bucl_depth2_nm TEXT,
    bucl_depth3_nm TEXT,
    bucl_depth4_nm TEXT
);

-- 4. f_projects
DROP TABLE IF EXISTS f_projects CASCADE;
CREATE TABLE f_projects AS
SELECT * FROM dblink(
    'dbname=risegpt user=postgres password=postgres host=localhost',
    'SELECT * FROM f_projects'
) AS t(
    id INTEGER,
    conts_id TEXT,
    ancm_id TEXT,
    ancm_tl_nm TEXT,
    conts_klang_nm TEXT,
    rsrh_bgnv_ymd TEXT,
    rsrh_endv_ymd TEXT,
    tot_rsrh_blgn_amt TEXT,
    govn_splm_amt TEXT,
    bnfn_splm_amt TEXT,
    cmpn_splm_amt TEXT
);

-- 5. f_equipments
DROP TABLE IF EXISTS f_equipments CASCADE;
CREATE TABLE f_equipments AS
SELECT * FROM dblink(
    'dbname=risegpt user=postgres password=postgres host=localhost',
    'SELECT * FROM f_equipments'
) AS t(
    id INTEGER,
    conts_id TEXT,
    conts_klang_nm TEXT,
    org_nm TEXT,
    org_busir_no TEXT,
    org_corp_no TEXT,
    address_dosi TEXT,
    equip_grp_lv1_nm TEXT,
    equip_grp_lv2_nm TEXT,
    equip_grp_lv3_nm TEXT,
    kpi_nm_list TEXT
);

-- 6. f_proposal_kpi
DROP TABLE IF EXISTS f_proposal_kpi CASCADE;
CREATE TABLE f_proposal_kpi AS
SELECT * FROM dblink(
    'dbname=risegpt user=postgres password=postgres host=localhost',
    'SELECT * FROM f_proposal_kpi'
) AS t(
    id INTEGER,
    sbjt_id TEXT,
    prfm_sn TEXT,
    eval_item_nm TEXT,
    top_prfm_lvl_de TEXT,
    cpt_pt TEXT,
    rhdp_gole_cn TEXT
);

-- 7. f_proposal_orgn
DROP TABLE IF EXISTS f_proposal_orgn CASCADE;
CREATE TABLE f_proposal_orgn AS
SELECT * FROM dblink(
    'dbname=risegpt user=postgres password=postgres host=localhost',
    'SELECT * FROM f_proposal_orgn'
) AS t(
    id INTEGER,
    sbjt_id TEXT,
    orgn_id TEXT,
    orgn_nm TEXT,
    busir_no TEXT,
    corp_no TEXT,
    ptcp_orgn_role_se TEXT
);

-- 8. f_applicant_address
DROP TABLE IF EXISTS f_applicant_address CASCADE;
CREATE TABLE f_applicant_address AS
SELECT * FROM dblink(
    'dbname=risegpt user=postgres password=postgres host=localhost',
    'SELECT * FROM f_applicant_address'
) AS t(
    id INTEGER,
    document_id TEXT,
    busir_no TEXT,
    corp_no TEXT,
    address TEXT
);

-- 9. f_patent_applicants
DROP TABLE IF EXISTS f_patent_applicants CASCADE;
CREATE TABLE f_patent_applicants AS
SELECT * FROM dblink(
    'dbname=risegpt user=postgres password=postgres host=localhost',
    'SELECT * FROM f_patent_applicants'
) AS t(
    id INTEGER,
    document_id TEXT,
    applicant_code TEXT,
    applicant_name TEXT,
    applicant_order INTEGER,
    applicant_country TEXT,
    applicant_type INTEGER
);

-- 10. f_proposal_profile (대용량)
DROP TABLE IF EXISTS f_proposal_profile CASCADE;
CREATE TABLE f_proposal_profile AS
SELECT * FROM dblink(
    'dbname=risegpt user=postgres password=postgres host=localhost',
    'SELECT * FROM f_proposal_profile'
) AS t(
    id INTEGER,
    sbjt_id TEXT,
    sbjt_nm TEXT,
    ancm_id TEXT,
    ancm_yy TEXT,
    ancm_tl_nm TEXT,
    orgn_id TEXT,
    orgn_nm TEXT,
    busir_no TEXT,
    corp_no TEXT,
    dvlp_gole TEXT,
    rhdp_whol_cn TEXT,
    tot_dvlp_srt_ymd TEXT,
    tot_dvlp_end_ymd TEXT
);

-- 11. f_gis (대용량)
DROP TABLE IF EXISTS f_gis CASCADE;
CREATE TABLE f_gis AS
SELECT * FROM dblink(
    'dbname=risegpt user=postgres password=postgres host=localhost',
    'SELECT * FROM f_gis'
) AS t(
    id INTEGER,
    conts_id TEXT,
    org_nm TEXT,
    org_busir_no TEXT,
    org_corp_no TEXT,
    x_coord DOUBLE PRECISION,
    y_coord DOUBLE PRECISION,
    admin_dong_code TEXT,
    admin_dong_name TEXT,
    legal_dong_code TEXT,
    legal_dong_name TEXT,
    postal_code TEXT
);

-- 12. f_proposal_techclsf (대용량)
DROP TABLE IF EXISTS f_proposal_techclsf CASCADE;
CREATE TABLE f_proposal_techclsf AS
SELECT * FROM dblink(
    'dbname=risegpt user=postgres password=postgres host=localhost',
    'SELECT * FROM f_proposal_techclsf'
) AS t(
    id INTEGER,
    sbjt_id TEXT,
    tecl_tp_se TEXT,
    tecl_cd TEXT,
    tecl_nm TEXT,
    cd_nm TEXT
);

-- 복사 완료 메시지
SELECT 'Table copy completed' AS status;
