"use client";

import { useState } from "react";

// 백엔드 API URL
const API_URL = process.env.NEXT_PUBLIC_API_URL ||
  (typeof window !== "undefined" && window.location.hostname !== "localhost"
    ? `http://${window.location.hostname}:8000`
    : "http://localhost:8000");

interface UserProfileFormProps {
  onProfileCreated: (profile: UserProfile) => void;
  onCancel: () => void;
}

interface UserProfile {
  id: number;
  user_id: string;
  education_level: string | null;
  occupation: string | null;
  registered_level: string;
  current_level: string;
  level_description: string;
}

export function UserProfileForm({ onProfileCreated, onCancel }: UserProfileFormProps) {
  const [userId, setUserId] = useState("");
  const [educationLevel, setEducationLevel] = useState("");
  const [occupation, setOccupation] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  // 학력 옵션
  const educationOptions = [
    { value: "", label: "선택하세요" },
    { value: "초등학생", label: "초등학생" },
    { value: "중학생", label: "중학생" },
    { value: "고등학생", label: "고등학생" },
    { value: "대학생", label: "대학생" },
    { value: "대학원생", label: "대학원생" },
    { value: "석사", label: "석사" },
    { value: "박사", label: "박사" },
  ];

  // 직업 옵션
  const occupationOptions = [
    { value: "", label: "선택하세요" },
    { value: "중소기업_실무자", label: "중소기업 실무자" },
    { value: "스타트업_실무자", label: "스타트업 실무자" },
    { value: "기업_기획자", label: "기업 기획자" },
    { value: "사업개발_담당자", label: "사업개발 담당자" },
    { value: "연구원", label: "연구원" },
    { value: "대기업_R&D", label: "대기업 R&D" },
    { value: "R&D_엔지니어", label: "R&D 엔지니어" },
    { value: "기술개발자", label: "기술개발자" },
    { value: "대학_연구원", label: "대학 연구원" },
    { value: "출연연_연구원", label: "출연연 연구원" },
    { value: "변리사", label: "변리사" },
    { value: "특허변호사", label: "특허변호사" },
    { value: "심사관", label: "심사관" },
    { value: "특허심사관", label: "특허심사관" },
    { value: "특허전문가", label: "특허전문가" },
    { value: "IP_매니저", label: "IP 매니저" },
    { value: "기술이전_전문가", label: "기술이전 전문가" },
    { value: "정책담당자", label: "정책담당자" },
    { value: "정부부처_담당자", label: "정부부처 담당자" },
    { value: "연구기획_평가자", label: "연구기획 평가자" },
    { value: "기술정책_연구자", label: "기술정책 연구자" },
    { value: "산업분석가", label: "산업분석가" },
  ];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!userId.trim()) {
      setError("사용자 ID를 입력해주세요");
      return;
    }

    if (!educationLevel && !occupation) {
      setError("학력 또는 직업 중 하나 이상을 선택해주세요");
      return;
    }

    setIsLoading(true);

    try {
      const response = await fetch(`${API_URL}/user/profile`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          user_id: userId,
          education_level: educationLevel || null,
          occupation: occupation || null,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "프로필 생성 실패");
      }

      const profile: UserProfile = await response.json();
      onProfileCreated(profile);
    } catch (err) {
      setError(err instanceof Error ? err.message : "알 수 없는 오류");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="bg-white rounded-2xl shadow-2xl p-8 max-w-2xl w-full">
      <h2 className="text-3xl font-bold text-gray-800 mb-2">사용자 프로필 생성</h2>
      <p className="text-gray-600 mb-6">
        학력과 직업 정보를 기반으로 맞춤형 답변 수준이 자동 설정됩니다
      </p>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* 사용자 ID */}
        <div>
          <label className="block text-sm font-bold text-gray-700 mb-2">
            사용자 ID <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            placeholder="예: user_001"
            className="w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            disabled={isLoading}
          />
        </div>

        {/* 학력 */}
        <div>
          <label className="block text-sm font-bold text-gray-700 mb-2">
            학력
          </label>
          <select
            value={educationLevel}
            onChange={(e) => setEducationLevel(e.target.value)}
            className="w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            disabled={isLoading}
          >
            {educationOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        {/* 직업 */}
        <div>
          <label className="block text-sm font-bold text-gray-700 mb-2">
            직업 (학력보다 우선 적용됨)
          </label>
          <select
            value={occupation}
            onChange={(e) => setOccupation(e.target.value)}
            className="w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            disabled={isLoading}
          >
            {occupationOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        {/* 안내 메시지 */}
        <div className="bg-blue-50 border-2 border-blue-200 rounded-lg p-4">
          <h3 className="font-bold text-blue-800 mb-2">💡 레벨 자동 설정 규칙</h3>
          <ul className="text-sm text-blue-700 space-y-1">
            <li>• 초등/중학생 → L1 (쉬운 설명)</li>
            <li>• 고등/대학생 → L2 (기본 설명)</li>
            <li>• 중소기업 실무자 → L3 (실무 중심)</li>
            <li>• 연구원 → L4 (기술 상세)</li>
            <li>• 변리사/심사관 → L5 (전문가)</li>
            <li>• 정책담당자 → L6 (정책 동향)</li>
          </ul>
        </div>

        {/* 오류 메시지 */}
        {error && (
          <div className="bg-red-50 border-2 border-red-200 rounded-lg p-4 text-red-700">
            {error}
          </div>
        )}

        {/* 버튼 */}
        <div className="flex gap-3">
          <button
            type="submit"
            disabled={isLoading}
            className="flex-1 px-6 py-3 bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold rounded-lg hover:from-blue-700 hover:to-purple-700 disabled:from-gray-400 disabled:to-gray-500 transition-all"
          >
            {isLoading ? "생성 중..." : "프로필 생성"}
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={isLoading}
            className="px-6 py-3 bg-gray-200 hover:bg-gray-300 text-gray-700 font-bold rounded-lg transition-colors disabled:bg-gray-100"
          >
            취소
          </button>
        </div>
      </form>
    </div>
  );
}
