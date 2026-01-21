"use client";

import React, { useState } from "react";

/**
 * 관점별 요약 데이터 타입
 */
export interface PerspectiveItem {
  original: string;
  explanation: string;
}

export interface PerspectiveSummary {
  purpose: PerspectiveItem;
  material: PerspectiveItem;
  method: PerspectiveItem;
  effect: PerspectiveItem;
}

interface PerspectiveTableProps {
  summary: PerspectiveSummary;
  level?: string;
  className?: string;
}

const perspectives = [
  { id: "purpose", label: "목적", icon: "🎯" },
  { id: "material", label: "소재", icon: "🧪" },
  { id: "method", label: "공법", icon: "⚙️" },
  { id: "effect", label: "효과", icon: "✨" },
] as const;

type PerspectiveId = typeof perspectives[number]["id"];

/**
 * 관점별 요약 표 컴포넌트
 *
 * 4가지 관점(목적/소재/공법/효과)을 표 형식으로 한눈에 보여줍니다.
 * 원문은 토글로 펼쳐볼 수 있습니다.
 */
export function PerspectiveTable({ summary, className = "" }: PerspectiveTableProps) {
  const [showOriginal, setShowOriginal] = useState(false);

  const hasAnyContent = perspectives.some((p) => {
    const item = summary[p.id as PerspectiveId];
    return item?.explanation?.trim() || item?.original?.trim();
  });

  if (!hasAnyContent) return null;

  const hasAnyOriginal = perspectives.some(
    (p) => summary[p.id as PerspectiveId]?.original?.trim()
  );

  return (
    <div className={`rounded-xl overflow-hidden border border-gray-200 ${className}`}>
      {/* 표 형식 요약 */}
      <table className="w-full text-left">
        <tbody>
          {perspectives.map((p) => {
            const item = summary[p.id as PerspectiveId];
            const content = item?.explanation?.trim() || item?.original?.trim();
            if (!content) return null;

            return (
              <tr key={p.id} className="border-b border-gray-100 last:border-b-0">
                <td className="py-3 px-4 w-24 bg-gray-50 font-medium text-gray-700 align-top">
                  <div className="flex items-center gap-1">
                    <span>{p.icon}</span>
                    <span className="text-sm">{p.label}</span>
                  </div>
                </td>
                <td className="py-3 px-4 text-gray-800 text-base leading-relaxed">
                  {content}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {/* 원문 보기 토글 */}
      {hasAnyOriginal && (
        <div className="border-t border-gray-200">
          <button
            onClick={() => setShowOriginal(!showOriginal)}
            className="w-full py-2 px-4 text-sm text-gray-500 hover:bg-gray-50 flex items-center justify-center gap-1 transition-colors"
          >
            <span>{showOriginal ? "▲" : "▼"}</span>
            <span>원문 {showOriginal ? "접기" : "보기"}</span>
          </button>

          {showOriginal && (
            <div className="p-4 bg-gray-50 text-sm text-gray-600 space-y-4 border-t border-gray-100">
              {perspectives.map((p) => {
                const original = summary[p.id as PerspectiveId]?.original?.trim();
                if (!original) return null;
                return (
                  <div key={p.id}>
                    <div className="font-medium text-gray-700 mb-1">
                      {p.icon} {p.label}
                    </div>
                    <p className="whitespace-pre-line text-gray-600 leading-relaxed pl-2 border-l-2 border-gray-200">
                      {original}
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default PerspectiveTable;
