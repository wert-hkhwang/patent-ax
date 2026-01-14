"""
User Literacy Level Mapper

가입 정보 (학력, 직업)을 기반으로 초기 리터러시 레벨을 자동 설정합니다.
사용자는 언제든 UI에서 레벨을 수동 변경할 수 있습니다.
"""

import psycopg2
import psycopg2.extras
import os
import json
from typing import Dict, Optional, List
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


class UserLevelMapper:
    """사용자 리터러시 레벨 매핑 및 관리"""

    # 학력/직업 → 리터러시 레벨 매핑 테이블
    LEVEL_MAPPING = {
        # ========================================
        # 학력 기반 매핑
        # ========================================
        "초등학생": "L1",
        "중학생": "L1",
        "고등학생": "L2",
        "대학생": "L2",
        "대학원생": "L2",
        "석사": "L2",
        "박사": "L4",  # 박사는 연구자 수준

        # ========================================
        # 직업 기반 매핑 (우선순위 높음)
        # ========================================
        # L3: 중소기업 실무자
        "중소기업_실무자": "L3",
        "스타트업_실무자": "L3",
        "기업_기획자": "L3",
        "사업개발_담당자": "L3",

        # L4: 연구자 / 대기업 R&D
        "연구원": "L4",
        "대기업_R&D": "L4",
        "R&D_엔지니어": "L4",
        "기술개발자": "L4",
        "대학_연구원": "L4",
        "출연연_연구원": "L4",

        # L5: 변리사 / 심사관 / 특허 전문가
        "변리사": "L5",
        "특허변호사": "L5",
        "심사관": "L5",
        "특허심사관": "L5",
        "특허전문가": "L5",
        "IP_매니저": "L5",
        "기술이전_전문가": "L5",

        # L6: 정책담당자
        "정책담당자": "L6",
        "정부부처_담당자": "L6",
        "연구기획_평가자": "L6",
        "기술정책_연구자": "L6",
        "산업분석가": "L6",
    }

    # 레벨별 설명 (UI에 표시)
    LEVEL_DESCRIPTIONS = {
        "L1": "쉬운 설명 (학생)",
        "L2": "기본 설명 (대학생/일반인)",
        "L3": "실무 중심 (중소기업)",
        "L4": "기술 상세 (연구자)",
        "L5": "전문가 (변리사/심사관)",
        "L6": "정책 동향 (담당자)",
    }

    def __init__(self):
        """데이터베이스 연결 초기화"""
        self.db_config = {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": os.getenv("DB_PORT", "5432"),
            "database": os.getenv("DB_NAME", "ax"),
            "user": os.getenv("DB_USER", "postgres"),
            "password": os.getenv("DB_PASSWORD", "postgres"),
        }

    def get_initial_level(
        self,
        education_level: Optional[str] = None,
        occupation: Optional[str] = None
    ) -> str:
        """
        학력/직업 정보를 기반으로 초기 리터러시 레벨 결정

        Args:
            education_level: 학력 (예: "대학생", "고등학생")
            occupation: 직업 (예: "연구원", "변리사")

        Returns:
            str: 리터러시 레벨 (L1~L6)

        Rules:
            1. 직업 정보가 있으면 우선 적용 (더 구체적)
            2. 직업 없으면 학력 기반으로 결정
            3. 둘 다 없거나 매핑 안 되면 L2 (기본)
        """
        # 1. 직업 우선 (더 구체적)
        if occupation and occupation in self.LEVEL_MAPPING:
            return self.LEVEL_MAPPING[occupation]

        # 2. 학력 기반
        if education_level and education_level in self.LEVEL_MAPPING:
            return self.LEVEL_MAPPING[education_level]

        # 3. 기본값: L2 (일반인)
        return "L2"

    def create_user_profile(
        self,
        user_id: str,
        education_level: Optional[str] = None,
        occupation: Optional[str] = None
    ) -> Dict:
        """
        신규 사용자 프로필 생성

        Args:
            user_id: 사용자 고유 ID
            education_level: 학력
            occupation: 직업

        Returns:
            Dict: 생성된 프로필 정보
        """
        # 초기 레벨 결정
        initial_level = self.get_initial_level(education_level, occupation)

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO f_user_profiles
                    (user_id, education_level, occupation, registered_level, current_level)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET
                    education_level = EXCLUDED.education_level,
                    occupation = EXCLUDED.occupation,
                    registered_level = EXCLUDED.registered_level,
                    current_level = EXCLUDED.current_level,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id, user_id, registered_level, current_level, created_at
                """,
                (user_id, education_level, occupation, initial_level, initial_level)
            )

            row = cursor.fetchone()
            conn.commit()

            return {
                "id": row[0],
                "user_id": row[1],
                "education_level": education_level,
                "occupation": occupation,
                "registered_level": row[2],
                "current_level": row[3],
                "created_at": row[4],
            }

        finally:
            cursor.close()
            conn.close()

    def get_user_profile(self, user_id: str) -> Optional[Dict]:
        """
        사용자 프로필 조회

        Args:
            user_id: 사용자 고유 ID

        Returns:
            Optional[Dict]: 프로필 정보 또는 None
        """
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT
                    id, user_id, education_level, occupation,
                    registered_level, current_level,
                    level_change_history, created_at, updated_at
                FROM f_user_profiles
                WHERE user_id = %s
                """,
                (user_id,)
            )

            row = cursor.fetchone()

            if row is None:
                return None

            return {
                "id": row[0],
                "user_id": row[1],
                "education_level": row[2],
                "occupation": row[3],
                "registered_level": row[4],
                "current_level": row[5],
                "level_change_history": row[6],
                "created_at": row[7],
                "updated_at": row[8],
            }

        finally:
            cursor.close()
            conn.close()

    def update_current_level(
        self,
        user_id: str,
        new_level: str,
        reason: Optional[str] = None
    ) -> Dict:
        """
        사용자가 UI에서 수동으로 레벨 변경

        Args:
            user_id: 사용자 고유 ID
            new_level: 새로운 레벨 (L1~L6)
            reason: 변경 이유 (선택사항)

        Returns:
            Dict: 업데이트된 프로필 정보

        Raises:
            ValueError: 잘못된 레벨 값
        """
        # 레벨 유효성 검증
        valid_levels = ["L1", "L2", "L3", "L4", "L5", "L6"]
        if new_level not in valid_levels:
            raise ValueError(f"Invalid level: {new_level}. Must be one of {valid_levels}")

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()

        try:
            # 현재 프로필 조회
            cursor.execute(
                "SELECT current_level, level_change_history FROM f_user_profiles WHERE user_id = %s",
                (user_id,)
            )
            row = cursor.fetchone()

            if row is None:
                raise ValueError(f"User not found: {user_id}")

            old_level = row[0]
            history = row[1] or []

            # 이력 추가
            history.append({
                "from": old_level,
                "to": new_level,
                "timestamp": datetime.now().isoformat(),
                "reason": reason
            })

            # 레벨 업데이트
            cursor.execute(
                """
                UPDATE f_user_profiles
                SET current_level = %s,
                    level_change_history = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
                RETURNING id, user_id, registered_level, current_level, updated_at
                """,
                (new_level, psycopg2.extras.Json(history), user_id)
            )

            row = cursor.fetchone()
            conn.commit()

            return {
                "id": row[0],
                "user_id": row[1],
                "registered_level": row[2],
                "current_level": row[3],
                "updated_at": row[4],
                "change_history": history,
            }

        finally:
            cursor.close()
            conn.close()

    def get_level_statistics(self) -> Dict:
        """
        레벨별 사용자 통계 조회

        Returns:
            Dict: 레벨별 사용자 수
        """
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT current_level, COUNT(*) as count
                FROM f_user_profiles
                GROUP BY current_level
                ORDER BY current_level
                """
            )

            rows = cursor.fetchall()

            stats = {level: 0 for level in ["L1", "L2", "L3", "L4", "L5", "L6"]}
            for row in rows:
                stats[row[0]] = row[1]

            return stats

        finally:
            cursor.close()
            conn.close()

    @classmethod
    def get_all_mappings(cls) -> Dict[str, str]:
        """
        전체 매핑 테이블 반환 (관리자용)

        Returns:
            Dict: 학력/직업 → 레벨 매핑
        """
        return cls.LEVEL_MAPPING.copy()

    @classmethod
    def get_level_description(cls, level: str) -> str:
        """
        레벨 설명 반환 (UI 표시용)

        Args:
            level: 리터러시 레벨 (L1~L6)

        Returns:
            str: 레벨 설명
        """
        return cls.LEVEL_DESCRIPTIONS.get(level, "알 수 없음")
