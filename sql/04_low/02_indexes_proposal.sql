-- EP-Agent: 제안 테이블 인덱스

-- f_proposal_profile 인덱스
CREATE INDEX IF NOT EXISTS idx_proposal_profile_sbjt_id ON f_proposal_profile(sbjt_id);
CREATE INDEX IF NOT EXISTS idx_proposal_profile_ancm_id ON f_proposal_profile(ancm_id);
CREATE INDEX IF NOT EXISTS idx_proposal_profile_orgn_id ON f_proposal_profile(orgn_id);
CREATE INDEX IF NOT EXISTS idx_proposal_profile_busir_no ON f_proposal_profile(busir_no);
CREATE INDEX IF NOT EXISTS idx_proposal_profile_dates ON f_proposal_profile(start_date, end_date);

-- f_proposal_kpi 인덱스
CREATE INDEX IF NOT EXISTS idx_proposal_kpi_sbjt_id ON f_proposal_kpi(sbjt_id);
CREATE INDEX IF NOT EXISTS idx_proposal_kpi_eval_item ON f_proposal_kpi(eval_item_nm);

-- f_proposal_orgn 인덱스
CREATE INDEX IF NOT EXISTS idx_proposal_orgn_sbjt_id ON f_proposal_orgn(sbjt_id);
CREATE INDEX IF NOT EXISTS idx_proposal_orgn_orgn_id ON f_proposal_orgn(orgn_id);
CREATE INDEX IF NOT EXISTS idx_proposal_orgn_busir_no ON f_proposal_orgn(busir_no);
CREATE INDEX IF NOT EXISTS idx_proposal_orgn_role ON f_proposal_orgn(ptcp_orgn_role_se);

-- f_proposal_techclsf 인덱스
CREATE INDEX IF NOT EXISTS idx_proposal_techclsf_sbjt_id ON f_proposal_techclsf(sbjt_id);
CREATE INDEX IF NOT EXISTS idx_proposal_techclsf_tecl_tp ON f_proposal_techclsf(tecl_tp_se);
CREATE INDEX IF NOT EXISTS idx_proposal_techclsf_tecl_cd ON f_proposal_techclsf(tecl_cd);

SELECT 'Proposal indexes created' as status;
