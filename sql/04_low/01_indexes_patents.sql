-- EP-Agent: 특허 테이블 인덱스

-- f_patents 인덱스
CREATE INDEX IF NOT EXISTS idx_patents_documentid ON f_patents(documentid);
CREATE INDEX IF NOT EXISTS idx_patents_ipc_main ON f_patents(ipc_main);
CREATE INDEX IF NOT EXISTS idx_patents_application_date ON f_patents(application_date);
CREATE INDEX IF NOT EXISTS idx_patents_registration_date ON f_patents(registration_date);
CREATE INDEX IF NOT EXISTS idx_patents_org_busir_no ON f_patents(org_busir_no);

-- f_patent_applicants 인덱스
CREATE INDEX IF NOT EXISTS idx_patent_applicants_doc_id ON f_patent_applicants(document_id);
CREATE INDEX IF NOT EXISTS idx_patent_applicants_code ON f_patent_applicants(applicant_code);
CREATE INDEX IF NOT EXISTS idx_patent_applicants_country ON f_patent_applicants(applicant_country);

-- f_applicant_address 인덱스
CREATE INDEX IF NOT EXISTS idx_applicant_address_doc_id ON f_applicant_address(document_id);
CREATE INDEX IF NOT EXISTS idx_applicant_address_corp_no ON f_applicant_address(corp_no);

SELECT 'Patent indexes created' as status;
