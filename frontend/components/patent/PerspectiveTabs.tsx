"use client";

import React, { useState } from "react";

/**
 * Phase 104: 관점별 요약 데이터 타입
 * 원본 데이터 + 레벨별 부연 설명 구조
 */
export interface PerspectiveItem {
  original: string;     // 원본 특허 문서 텍스트
  explanation: string;  // 레벨에 맞는 부연 설명
}

export interface PerspectiveSummary {
  purpose: PerspectiveItem;   // 목적 (objectko 기반)
  material: PerspectiveItem;  // 소재 (solutionko 기반)
  method: PerspectiveItem;    // 공법 (solutionko 기반)
  effect: PerspectiveItem;    // 효과 (초록 기반)
}

interface PerspectiveTabsProps {
  summary: PerspectiveSummary;
  level?: string;
  className?: string;
}

/**
 * 탭 정의
 */
const tabs = [
  {
    id: "purpose" as const,
    label: "목적",
    icon: "🎯",
    color: "blue",
    description: "특허가 해결하려는 과제"
  },
  {
    id: "material" as const,
    label: "소재",
    icon: "🧪",
    color: "green",
    description: "사용되는 주요 소재/기술"
  },
  {
    id: "method" as const,
    label: "공법",
    icon: "⚙️",
    color: "orange",
    description: "기술 구현 방법/절차"
  },
  {
    id: "effect" as const,
    label: "효과",
    icon: "✨",
    color: "purple",
    description: "기술의 성과/개선점"
  },
];

type TabId = typeof tabs[number]["id"];

/**
 * 레벨별 설명 라벨
 */
const levelLabels: Record<string, string> = {
  "L1": "쉽게 설명하면",
  "L2": "쉽게 설명하면",
  "L3": "실무 관점에서",
  "L4": "기술적으로",
  "L5": "법적 관점에서",
  "L6": "정책적 관점에서",
};

/**
 * 관점별 요약 탭 컴포넌트
 *
 * 특허 문서의 구조적 특성을 활용하여 4가지 관점으로 정보를 표시합니다.
 * - 원본 텍스트: 검색된 특허 문서의 실제 데이터
 * - 부연 설명: 사용자 리터러시 레벨에 맞는 설명
 */
export function PerspectiveTabs({ summary, level = "L2", className = "" }: PerspectiveTabsProps) {
  const [activeTab, setActiveTab] = useState<TabId>("purpose");

  // 내용이 없는 탭 확인 (원본 또는 설명이 있으면 true)
  const hasContent = (tabId: TabId): boolean => {
    const item = summary[tabId];
    if (!item) return false;
    return (item.original && item.original.trim().length > 0) ||
           (item.explanation && item.explanation.trim().length > 0);
  };

  // 활성화된 탭의 색상 클래스 반환
  const getActiveColorClass = (tabId: TabId, color: string): string => {
    if (activeTab !== tabId) return "";

    const colorMap: Record<string, string> = {
      blue: "bg-blue-50 border-b-4 border-blue-500 text-blue-700",
      green: "bg-green-50 border-b-4 border-green-500 text-green-700",
      orange: "bg-orange-50 border-b-4 border-orange-500 text-orange-700",
      purple: "bg-purple-50 border-b-4 border-purple-500 text-purple-700",
    };

    return colorMap[color] || "";
  };

  // 레벨별 설명 라벨 가져오기
  const getExplanationLabel = (): string => {
    return levelLabels[level] || "쉽게 설명하면";
  };

  // 현재 탭의 데이터 가져오기
  const getCurrentItem = (): PerspectiveItem | null => {
    return summary[activeTab] || null;
  };

  const currentItem = getCurrentItem();

  return (
    <div className={`border border-gray-200 rounded-xl overflow-hidden shadow-sm ${className}`}>
      {/* 탭 헤더 */}
      <div className="flex border-b border-gray-200 bg-gray-50">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            disabled={!hasContent(tab.id)}
            className={`
              flex-1 px-4 py-4 text-center transition-all duration-200
              ${activeTab === tab.id
                ? getActiveColorClass(tab.id, tab.color)
                : hasContent(tab.id)
                  ? "hover:bg-gray-100 text-gray-600"
                  : "text-gray-300 cursor-not-allowed"
              }
            `}
            title={tab.description}
          >
            <span className="text-2xl block mb-1">{tab.icon}</span>
            <span className="font-medium text-sm">{tab.label}</span>
          </button>
        ))}
      </div>

      {/* 탭 콘텐츠 */}
      <div className="p-6 bg-white min-h-[200px]">
        {hasContent(activeTab) && currentItem ? (
          <div className="space-y-4">
            {/* 원본 텍스트 */}
            {currentItem.original && currentItem.original.trim() && (
              <div className="bg-gray-50 p-4 rounded-lg border border-gray-200">
                <div className="text-xs text-gray-500 mb-2 font-medium flex items-center gap-1">
                  <span>📄</span> 원문
                </div>
                <p className="text-gray-700 text-sm leading-relaxed whitespace-pre-line">
                  {currentItem.original}
                </p>
              </div>
            )}

            {/* 레벨별 부연 설명 */}
            {currentItem.explanation && currentItem.explanation.trim() && (
              <div className="bg-blue-50 p-4 rounded-lg border border-blue-200">
                <div className="text-xs text-blue-600 mb-2 font-medium flex items-center gap-1">
                  <span>💡</span> {getExplanationLabel()}
                </div>
                <p className="text-blue-800 text-base font-medium leading-relaxed">
                  {currentItem.explanation}
                </p>
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center justify-center h-32 text-gray-400">
            <p>해당 관점의 정보가 없습니다.</p>
          </div>
        )}
      </div>

      {/* 하단 설명 */}
      <div className="px-6 py-3 bg-gray-50 border-t border-gray-200">
        <p className="text-xs text-gray-500 text-center">
          {tabs.find(t => t.id === activeTab)?.description}
          {level && <span className="ml-2 text-gray-400">| 수준: {level}</span>}
        </p>
      </div>
    </div>
  );
}

export default PerspectiveTabs;
