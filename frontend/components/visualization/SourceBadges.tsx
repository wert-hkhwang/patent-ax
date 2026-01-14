"use client";

import React from "react";

interface ConnectionCounts {
  ipc?: number;
  applicant?: number;
  org?: number;
  related?: number;
}

interface SourceBadgesProps {
  community?: number;
  pagerank?: number;
  connections?: ConnectionCounts;
  compact?: boolean;
}

// 커뮤니티 색상 (GraphVisualization과 동일)
const COMMUNITY_COLORS = [
  "#e11d48", "#db2777", "#c026d3", "#9333ea", "#7c3aed",
  "#6366f1", "#3b82f6", "#0ea5e9", "#06b6d4", "#14b8a6",
  "#10b981", "#22c55e", "#84cc16", "#eab308", "#f59e0b",
  "#f97316", "#ef4444", "#64748b", "#475569", "#334155",
];

// PageRank 백분위 계산 (상위 몇 % 인지)
function getPageRankPercentile(pagerank: number): string {
  // 대략적인 분포 기반 (전체 노드 중 상위 %)
  if (pagerank >= 0.01) return "상위 1%";
  if (pagerank >= 0.005) return "상위 2%";
  if (pagerank >= 0.002) return "상위 5%";
  if (pagerank >= 0.001) return "상위 10%";
  if (pagerank >= 0.0005) return "상위 20%";
  return "";
}

export function SourceBadges({
  community,
  pagerank,
  connections,
  compact = false,
}: SourceBadgesProps) {
  const hasData = community !== undefined || pagerank !== undefined || connections;

  if (!hasData) return null;

  const communityColor = community !== undefined
    ? COMMUNITY_COLORS[community % COMMUNITY_COLORS.length]
    : undefined;

  const pagerankPercentile = pagerank ? getPageRankPercentile(pagerank) : "";
  const totalConnections = connections
    ? (connections.ipc || 0) + (connections.applicant || 0) + (connections.org || 0) + (connections.related || 0)
    : 0;

  if (compact) {
    // 컴팩트 모드: 한 줄에 아이콘+숫자만
    return (
      <div className="flex items-center gap-2 text-[10px] text-gray-500">
        {community !== undefined && (
          <span
            className="flex items-center gap-0.5"
            title={`커뮤니티 #${community}`}
          >
            <span
              className="w-2 h-2 rounded-full inline-block"
              style={{ backgroundColor: communityColor }}
            />
            <span>#{community}</span>
          </span>
        )}
        {pagerank !== undefined && pagerank > 0.0005 && (
          <span title={`PageRank: ${pagerank.toFixed(6)}`}>
            PR:{pagerank.toFixed(4)}
          </span>
        )}
        {totalConnections > 0 && (
          <span title="연결 수">
            {totalConnections}
          </span>
        )}
      </div>
    );
  }

  // 풀 모드: 상세 배지
  return (
    <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
      {/* 커뮤니티 배지 */}
      {community !== undefined && (
        <span
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium"
          style={{
            backgroundColor: `${communityColor}15`,
            color: communityColor,
            border: `1px solid ${communityColor}40`
          }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: communityColor }}
          />
          커뮤니티 #{community}
        </span>
      )}

      {/* PageRank 배지 */}
      {pagerank !== undefined && pagerankPercentile && (
        <span
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200"
          title={`PageRank: ${pagerank.toFixed(6)}`}
        >
          <svg className="w-2.5 h-2.5" fill="currentColor" viewBox="0 0 20 20">
            <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
          </svg>
          {pagerankPercentile}
        </span>
      )}

      {/* 연결 수 배지 */}
      {connections && totalConnections > 0 && (
        <span
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-50 text-blue-700 border border-blue-200"
          title={`IPC: ${connections.ipc || 0}, 출원인: ${connections.applicant || 0}, 기관: ${connections.org || 0}, 기타: ${connections.related || 0}`}
        >
          <svg className="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
          </svg>
          {connections.ipc ? `IPC ${connections.ipc}` : ""}
          {connections.applicant ? ` 출원인 ${connections.applicant}` : ""}
          {connections.org ? ` 기관 ${connections.org}` : ""}
          {!connections.ipc && !connections.applicant && !connections.org && connections.related
            ? `연결 ${connections.related}`
            : ""}
        </span>
      )}
    </div>
  );
}

export default SourceBadges;
