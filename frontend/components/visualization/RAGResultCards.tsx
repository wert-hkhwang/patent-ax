"use client";

import { useState } from "react";
import { RAGResult, RAGResultItem } from "@/types/workflow";
import { SourceBadges } from "./SourceBadges";

interface RAGResultCardsProps {
  result: RAGResult | null;
}

const entityTypeConfig: Record<string, { label: string; color: string }> = {
  patent: { label: "특허", color: "bg-orange-100 text-orange-800" },
  project: { label: "연구과제", color: "bg-green-100 text-green-800" },
  equip: { label: "장비", color: "bg-blue-100 text-blue-800" },
  org: { label: "기관", color: "bg-purple-100 text-purple-800" },
  applicant: { label: "출원인", color: "bg-pink-100 text-pink-800" },
  ipc: { label: "IPC", color: "bg-yellow-100 text-yellow-800" },
  ancm: { label: "공고", color: "bg-red-100 text-red-800" },
  evalp: { label: "배점표", color: "bg-indigo-100 text-indigo-800" },
};

const searchStrategyLabels: Record<string, string> = {
  HYBRID: "하이브리드 검색",
  VECTOR_ONLY: "벡터 검색",
  GRAPH_ONLY: "그래프 검색",
  GRAPH_ENHANCED: "그래프 강화 검색",
};

function ScoreBadge({ score }: { score: number }) {
  const percentage = Math.round(score * 100);
  const getColor = () => {
    if (percentage >= 90) return "bg-green-500";
    if (percentage >= 70) return "bg-yellow-500";
    return "bg-gray-400";
  };

  return (
    <div className="flex items-center gap-1">
      <div className={`w-2 h-2 rounded-full ${getColor()}`} />
      <span className="text-xs text-gray-600 font-mono">{percentage}%</span>
    </div>
  );
}

function ResultCard({ item }: { item: RAGResultItem }) {
  const typeConfig = entityTypeConfig[item.entity_type] || {
    label: item.entity_type,
    color: "bg-gray-100 text-gray-800",
  };

  // metadata에서 community, pagerank, connections 추출
  const metadata = (item as any).metadata || {};

  return (
    <div className="p-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span
              className={`px-1.5 py-0.5 text-xs font-medium rounded ${typeConfig.color}`}
            >
              {typeConfig.label}
            </span>
            <ScoreBadge score={item.score} />
          </div>
          <p className="text-sm text-gray-800 truncate" title={item.name}>
            {item.name || item.node_id}
          </p>
          {/* 커뮤니티/PageRank 배지 (컴팩트 모드) */}
          <SourceBadges
            community={metadata.community}
            pagerank={metadata.pagerank}
            connections={metadata.connections}
            compact={true}
          />
        </div>
      </div>
    </div>
  );
}

export function RAGResultCards({ result }: RAGResultCardsProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!result) return null;

  const strategyLabel =
    searchStrategyLabels[result.search_strategy] || result.search_strategy;

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 bg-green-50 cursor-pointer hover:bg-green-100 transition"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2">
          <span className="text-green-600">📚</span>
          <h3 className="text-sm font-semibold text-green-800">RAG 검색</h3>
          <span className="px-2 py-0.5 text-xs bg-green-200 text-green-800 rounded">
            {result.result_count}건
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-green-600">{strategyLabel}</span>
          <span className="text-green-600 text-sm">
            {isExpanded ? "▼" : "▶"}
          </span>
        </div>
      </div>

      {/* Results */}
      {isExpanded && result.top_results.length > 0 && (
        <div className="p-3 space-y-2">
          {result.top_results.map((item, index) => (
            <ResultCard key={`${item.node_id}-${index}`} item={item} />
          ))}
        </div>
      )}

      {/* Empty state */}
      {isExpanded && result.top_results.length === 0 && (
        <div className="px-4 py-3 text-sm text-gray-500 text-center">
          검색 결과가 없습니다
        </div>
      )}

      {/* Collapsed preview */}
      {!isExpanded && result.top_results.length > 0 && (
        <div className="px-4 py-2 text-xs text-gray-500">
          상위 결과:{" "}
          {result.top_results
            .slice(0, 2)
            .map((r) => r.name || r.node_id)
            .join(", ")}
          {result.top_results.length > 2 &&
            ` 외 ${result.top_results.length - 2}건`}
        </div>
      )}
    </div>
  );
}
