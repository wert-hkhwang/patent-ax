"""
User Profile and Literacy Level Management API

사용자 프로필 및 리터러시 레벨 관리 엔드포인트
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict
from workflow.user.level_mapper import UserLevelMapper

router = APIRouter(prefix="/user", tags=["User Profile"])


# ========================================
# Request/Response Models
# ========================================

class UserProfileCreate(BaseModel):
    """사용자 프로필 생성 요청"""
    user_id: str = Field(..., description="사용자 고유 ID")
    education_level: Optional[str] = Field(None, description="학력 (예: 대학생, 고등학생)")
    occupation: Optional[str] = Field(None, description="직업 (예: 연구원, 변리사)")

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user_12345",
                "education_level": "대학생",
                "occupation": "연구원"
            }
        }


class UserProfileResponse(BaseModel):
    """사용자 프로필 응답"""
    id: int
    user_id: str
    education_level: Optional[str]
    occupation: Optional[str]
    registered_level: str
    current_level: str
    level_description: str


class LevelChangeRequest(BaseModel):
    """레벨 변경 요청"""
    user_id: str = Field(..., description="사용자 고유 ID")
    new_level: str = Field(..., description="새로운 레벨 (L1~L6)")
    reason: Optional[str] = Field(None, description="변경 이유 (선택사항)")

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user_12345",
                "new_level": "L4",
                "reason": "연구자 수준의 상세한 정보 필요"
            }
        }


class LevelStatisticsResponse(BaseModel):
    """레벨별 통계 응답"""
    statistics: Dict[str, int] = Field(..., description="레벨별 사용자 수")
    total: int = Field(..., description="전체 사용자 수")


class LevelInfoResponse(BaseModel):
    """레벨 정보 응답"""
    level: str
    description: str
    example_education: list[str]
    example_occupation: list[str]


# ========================================
# API Endpoints
# ========================================

@router.post("/profile", response_model=UserProfileResponse, summary="사용자 프로필 생성")
async def create_user_profile(request: UserProfileCreate):
    """
    신규 사용자 프로필 생성

    - 학력/직업 정보를 기반으로 초기 리터러시 레벨 자동 설정
    - 동일 user_id로 재요청 시 프로필 업데이트
    """
    try:
        mapper = UserLevelMapper()
        profile = mapper.create_user_profile(
            user_id=request.user_id,
            education_level=request.education_level,
            occupation=request.occupation
        )

        return UserProfileResponse(
            id=profile["id"],
            user_id=profile["user_id"],
            education_level=profile["education_level"],
            occupation=profile["occupation"],
            registered_level=profile["registered_level"],
            current_level=profile["current_level"],
            level_description=UserLevelMapper.get_level_description(profile["current_level"])
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create profile: {str(e)}")


@router.get("/profile/{user_id}", response_model=UserProfileResponse, summary="사용자 프로필 조회")
async def get_user_profile(user_id: str):
    """
    사용자 프로필 조회

    - 존재하지 않는 user_id인 경우 404 에러
    """
    try:
        mapper = UserLevelMapper()
        profile = mapper.get_user_profile(user_id)

        if profile is None:
            raise HTTPException(status_code=404, detail=f"User not found: {user_id}")

        return UserProfileResponse(
            id=profile["id"],
            user_id=profile["user_id"],
            education_level=profile["education_level"],
            occupation=profile["occupation"],
            registered_level=profile["registered_level"],
            current_level=profile["current_level"],
            level_description=UserLevelMapper.get_level_description(profile["current_level"])
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get profile: {str(e)}")


@router.post("/level/change", summary="리터러시 레벨 변경")
async def change_user_level(request: LevelChangeRequest):
    """
    사용자가 UI에서 수동으로 레벨 변경

    - 변경 이력이 자동으로 기록됨
    - L1~L6 중 하나만 가능
    """
    try:
        mapper = UserLevelMapper()
        updated = mapper.update_current_level(
            user_id=request.user_id,
            new_level=request.new_level,
            reason=request.reason
        )

        return {
            "success": True,
            "user_id": updated["user_id"],
            "previous_level": updated["change_history"][-1]["from"] if updated["change_history"] else None,
            "current_level": updated["current_level"],
            "level_description": UserLevelMapper.get_level_description(updated["current_level"]),
            "updated_at": updated["updated_at"]
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to change level: {str(e)}")


@router.get("/level/statistics", response_model=LevelStatisticsResponse, summary="레벨별 통계 조회")
async def get_level_statistics():
    """
    레벨별 사용자 통계 조회

    - 전체 사용자의 레벨 분포
    """
    try:
        mapper = UserLevelMapper()
        stats = mapper.get_level_statistics()

        return LevelStatisticsResponse(
            statistics=stats,
            total=sum(stats.values())
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get statistics: {str(e)}")


@router.get("/level/info", summary="전체 레벨 정보 조회")
async def get_all_level_info():
    """
    전체 리터러시 레벨 정보 조회

    - 각 레벨별 설명
    - 예시 학력/직업
    """
    mappings = UserLevelMapper.get_all_mappings()

    # 레벨별로 역매핑
    level_examples = {
        "L1": {"education": [], "occupation": []},
        "L2": {"education": [], "occupation": []},
        "L3": {"education": [], "occupation": []},
        "L4": {"education": [], "occupation": []},
        "L5": {"education": [], "occupation": []},
        "L6": {"education": [], "occupation": []},
    }

    for key, level in mappings.items():
        # 학력 vs 직업 구분
        if any(kw in key for kw in ["학생", "석사", "박사"]):
            level_examples[level]["education"].append(key)
        else:
            level_examples[level]["occupation"].append(key)

    result = []
    for level in ["L1", "L2", "L3", "L4", "L5", "L6"]:
        result.append({
            "level": level,
            "description": UserLevelMapper.get_level_description(level),
            "example_education": level_examples[level]["education"],
            "example_occupation": level_examples[level]["occupation"]
        })

    return result


@router.get("/level/mappings", summary="전체 매핑 테이블 조회 (관리자용)")
async def get_all_mappings():
    """
    전체 학력/직업 → 레벨 매핑 테이블 조회

    - 관리자 또는 디버깅용
    """
    return {
        "mappings": UserLevelMapper.get_all_mappings(),
        "total_count": len(UserLevelMapper.get_all_mappings())
    }
