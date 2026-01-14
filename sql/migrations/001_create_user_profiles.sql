-- 사용자 프로필 테이블 생성
-- Patent-AX 사용자 수준별 특허 정보 제공 시스템

CREATE TABLE IF NOT EXISTS f_user_profiles (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(100) UNIQUE NOT NULL,

    -- 기본 정보 (가입 시 입력)
    education_level VARCHAR(50),  -- 학력: 초등학생, 중학생, 고등학생, 대학생, 대학원생 등
    occupation VARCHAR(50),       -- 직업: 중소기업_실무자, 대기업_R&D, 연구원, 변리사, 심사관, 특허전문가, 정책담당자 등

    -- 리터러시 레벨
    registered_level VARCHAR(20) NOT NULL,  -- 가입 시 자동 설정된 레벨
    current_level VARCHAR(20) NOT NULL,     -- 현재 사용 중인 레벨 (UI에서 변경 가능)

    -- 레벨 변경 이력 (선택사항, JSON 형식)
    level_change_history JSONB DEFAULT '[]'::JSONB,

    -- 메타데이터
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 제약조건
    CHECK (registered_level IN ('L1', 'L2', 'L3', 'L4', 'L5', 'L6')),
    CHECK (current_level IN ('L1', 'L2', 'L3', 'L4', 'L5', 'L6'))
);

-- 인덱스 생성
CREATE INDEX idx_user_profiles_user_id ON f_user_profiles(user_id);
CREATE INDEX idx_user_profiles_current_level ON f_user_profiles(current_level);

-- updated_at 자동 업데이트 트리거
CREATE OR REPLACE FUNCTION update_user_profiles_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_user_profiles_updated_at
    BEFORE UPDATE ON f_user_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_user_profiles_updated_at();

-- 코멘트
COMMENT ON TABLE f_user_profiles IS '사용자 리터러시 레벨 프로필';
COMMENT ON COLUMN f_user_profiles.user_id IS '사용자 고유 ID';
COMMENT ON COLUMN f_user_profiles.education_level IS '학력 수준';
COMMENT ON COLUMN f_user_profiles.occupation IS '직업/직군';
COMMENT ON COLUMN f_user_profiles.registered_level IS '가입 시 자동 설정된 리터러시 레벨 (L1~L6)';
COMMENT ON COLUMN f_user_profiles.current_level IS '현재 사용 중인 리터러시 레벨 (UI에서 변경 가능)';
COMMENT ON COLUMN f_user_profiles.level_change_history IS '레벨 변경 이력 (JSON 배열)';
