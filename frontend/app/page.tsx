"use client";

import { useState } from "react";
import { MyAssistant } from "@/components/MyAssistant";
import { UserProfileModal } from "@/components/user/UserProfileModal";
import { UserProfileDisplay } from "@/components/user/UserProfileDisplay";

// 검색 모드 타입
export type SearchMode = "ax" | "unified";

// Phase 103: 수준 타입 (v1.3 리터러시 시스템)
export type UserLevel = "L1" | "L2" | "L3" | "L4" | "L5" | "L6" | "초등" | "일반인" | "전문가";

interface UserProfile {
  id: number;
  user_id: string;
  education_level: string | null;
  occupation: string | null;
  registered_level: string;
  current_level: string;
  level_description: string;
}

export default function Home() {
  const [level, setLevel] = useState<UserLevel>("L2");  // Phase 103: 기본값 L2 (일반인)
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [showProfileModal, setShowProfileModal] = useState(false);

  const handleProfileCreated = (profile: UserProfile) => {
    setUserProfile(profile);
    setLevel(profile.current_level as UserLevel);
  };

  return (
    <main className="h-screen flex flex-col">
      {/* 헤더 */}
      <header className="bg-gradient-to-r from-blue-600 to-purple-600 text-white p-4 shadow-lg">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold">Easy 특허 Agent</h1>
            <p className="text-sm text-blue-100">특허 맞춤형 AI 어시스턴트</p>
          </div>

          {/* 사용자 프로필 및 레벨 선택 */}
          <div className="flex items-center gap-3">
            {/* 쉬운 모드 버튼 */}
            <a
              href="/easy"
              className="px-4 py-2 bg-yellow-400 hover:bg-yellow-300 text-gray-800 font-bold rounded-lg transition-colors flex items-center gap-2"
            >
              <span className="text-xl">🎓</span>
              쉬운 모드
            </a>

            {/* 사용자 프로필 표시/생성 */}
            <UserProfileDisplay
              profile={userProfile}
              onCreateProfile={() => setShowProfileModal(true)}
            />

            {/* 레벨 수동 선택 */}
            <select
              value={level}
              onChange={(e) => setLevel(e.target.value as UserLevel)}
              className="px-4 py-2 text-sm bg-white/10 text-white border border-white/20 rounded-lg focus:outline-none focus:ring-2 focus:ring-white/30 cursor-pointer font-medium"
            >
              <optgroup label="리터러시 레벨" className="text-gray-800">
                <option value="L1" className="text-gray-800">🎓 초등학생</option>
                <option value="L2" className="text-gray-800">📚 대학생/일반인</option>
                <option value="L3" className="text-gray-800">💼 중소기업 실무자</option>
                <option value="L4" className="text-gray-800">🔬 연구자</option>
                <option value="L5" className="text-gray-800">⚖️ 변리사/심사관</option>
                <option value="L6" className="text-gray-800">📊 정책담당자</option>
              </optgroup>
            </select>
          </div>
        </div>
      </header>

      {/* 채팅 영역 */}
      <div className="flex-1 overflow-hidden">
        <MyAssistant searchMode="ax" level={level} />
      </div>

      {/* 푸터 */}
      <footer className="bg-gray-100 text-gray-600 text-xs p-2 text-center border-t">
        Easy 특허 Agent v1.3 | Powered by EXAONE
      </footer>

      {/* 프로필 생성 모달 */}
      <UserProfileModal
        isOpen={showProfileModal}
        onClose={() => setShowProfileModal(false)}
        onProfileCreated={handleProfileCreated}
      />
    </main>
  );
}
