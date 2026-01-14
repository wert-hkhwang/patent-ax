-- EP-Agent: f_equipments NaN 처리

UPDATE f_equipments SET org_busir_no = NULL WHERE org_busir_no = 'NaN' OR org_busir_no = '';
UPDATE f_equipments SET org_corp_no = NULL WHERE org_corp_no = 'NaN' OR org_corp_no = '';

-- 확인
SELECT 'Equipments NaN cleaned' as status, COUNT(*) as count FROM f_equipments WHERE org_busir_no IS NULL;
