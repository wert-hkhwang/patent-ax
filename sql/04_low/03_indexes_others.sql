-- EP-Agent: 기타 테이블 인덱스

-- f_projects 인덱스
CREATE INDEX IF NOT EXISTS idx_projects_conts_id ON f_projects(conts_id);
CREATE INDEX IF NOT EXISTS idx_projects_ancm_id ON f_projects(ancm_id);
CREATE INDEX IF NOT EXISTS idx_projects_ancm_tl_nm ON f_projects(ancm_tl_nm);

-- f_ancm_evalp 인덱스
CREATE INDEX IF NOT EXISTS idx_ancm_evalp_ancm_id_ref ON f_ancm_evalp(ancm_id_ref);
CREATE INDEX IF NOT EXISTS idx_ancm_evalp_bucl ON f_ancm_evalp(bucl_cd);
CREATE INDEX IF NOT EXISTS idx_ancm_evalp_eval_idx ON f_ancm_evalp(eval_idx_nm);

-- f_ancm_prcnd 인덱스
CREATE INDEX IF NOT EXISTS idx_ancm_prcnd_ancm_tl_nm ON f_ancm_prcnd(ancm_tl_nm);
CREATE INDEX IF NOT EXISTS idx_ancm_prcnd_prcnd_se ON f_ancm_prcnd(prcnd_se_cd);
CREATE INDEX IF NOT EXISTS idx_ancm_prcnd_bucl ON f_ancm_prcnd(bucl_cd);

-- f_equipments 인덱스
CREATE INDEX IF NOT EXISTS idx_equipments_conts_id ON f_equipments(conts_id);
CREATE INDEX IF NOT EXISTS idx_equipments_org_nm ON f_equipments(org_nm);
CREATE INDEX IF NOT EXISTS idx_equipments_region ON f_equipments(address_dosi);
CREATE INDEX IF NOT EXISTS idx_equipments_region_code ON f_equipments(region_code);

-- f_gis 인덱스
CREATE INDEX IF NOT EXISTS idx_gis_org_nm ON f_gis(org_nm);
CREATE INDEX IF NOT EXISTS idx_gis_conts_id ON f_gis(conts_id);
CREATE INDEX IF NOT EXISTS idx_gis_admin_dong ON f_gis(admin_dong_code);
CREATE INDEX IF NOT EXISTS idx_gis_postal ON f_gis(postal_code);

-- f_kpi 인덱스
CREATE INDEX IF NOT EXISTS idx_kpi_data ON f_kpi(kpi_data);

SELECT 'Other indexes created' as status;
