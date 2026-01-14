"use client";

import { useState } from "react";
import { MyAssistant } from "@/components/MyAssistant";

// 검색 모드 타입
export type SearchMode = "ax" | "unified";

// Phase 103: 수준 타입
export type UserLevel = "초등" | "일반인" | "전문가";

export default function Home() {
  const [searchMode, setSearchMode] = useState<SearchMode>("ax");
  const [level, setLevel] = useState<UserLevel>("일반인");  // Phase 103: 수준 선택

  return (
    <main className="h-screen flex flex-col">
      {/* 헤더 */}
      <header className="bg-gradient-to-r from-blue-600 to-purple-600 text-white p-4 shadow-lg">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold">AX Agent</h1>
            <p className="text-sm text-blue-100">AI 연구 데이터 어시스턴트</p>
          </div>

          {/* 모드 전환 탭 */}
          <div className="flex items-center gap-1 bg-white/10 rounded-lg p-1">
            <button
              onClick={() => setSearchMode("ax")}
              className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${
                searchMode === "ax"
                  ? "bg-white text-blue-600 shadow"
                  : "text-white/80 hover:text-white hover:bg-white/10"
              }`}
            >
              AX (특허)
            </button>
            <button
              onClick={() => setSearchMode("unified")}
              className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${
                searchMode === "unified"
                  ? "bg-white text-blue-600 shadow"
                  : "text-white/80 hover:text-white hover:bg-white/10"
              }`}
            >
              통합검색
            </button>
          </div>

          {/* Phase 103: 수준 선택 드롭다운 */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-blue-100">답변 수준:</span>
            <select
              value={level}
              onChange={(e) => setLevel(e.target.value as UserLevel)}
              className="px-3 py-1.5 text-sm bg-white/10 text-white border border-white/20 rounded-md focus:outline-none focus:ring-2 focus:ring-white/30 cursor-pointer"
            >
              <option value="초등" className="text-gray-800">초등</option>
              <option value="일반인" className="text-gray-800">일반인</option>
              <option value="전문가" className="text-gray-800">전문가</option>
            </select>
          </div>

          <div className="text-sm text-blue-100">
            {searchMode === "ax" ? "특허 전용" : "특허 | 연구과제 | 장비 | 공고"}
          </div>
        </div>
      </header>

      {/* 채팅 영역 */}
      <div className="flex-1 overflow-hidden">
        <MyAssistant searchMode={searchMode} level={level} />
      </div>

      {/* 푸터 */}
      <footer className="bg-gray-100 text-gray-600 text-xs p-2 text-center border-t">
        Powered by LangGraph + EXAONE | Phase 3: Workflow Visualization
      </footer>
    </main>
  );
}
