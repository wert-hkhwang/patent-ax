"use client";

import { SubQueryData, SubQueryInfo } from "@/types/workflow";

interface SubQueryTreeProps {
  data: SubQueryData | null;
}

const queryTypeIcons: Record<string, string> = {
  sql: "🗄️",
  rag: "🔍",
  hybrid: "⚡",
  simple: "💬",
};

// Phase 92: subtype 한글 라벨
const subtypeLabels: Record<string, string> = {
  list: "목록 조회",
  recommendation: "추천",
  trend_analysis: "동향 분석",
  aggregation: "통계/집계",
  ranking: "순위",
  concept: "개념 설명",
  sql: "SQL",
  rag: "RAG",
  hybrid: "하이브리드",
};

function SubQueryItem({ query, index }: { query: SubQueryInfo; index: number }) {
  const icon = queryTypeIcons[query.type] || "❓";
  const subtypeLabel = subtypeLabels[query.type] || query.type.toUpperCase();

  const statusConfig = {
    pending: { bg: "bg-gray-100", text: "text-gray-600", label: "대기" },
    executing: {
      bg: "bg-blue-100",
      text: "text-blue-700",
      label: "실행 중",
    },
    completed: {
      bg: "bg-green-100",
      text: "text-green-700",
      label: "완료",
    },
    error: { bg: "bg-red-100", text: "text-red-700", label: "오류" },
  };

  const config = statusConfig[query.status] || statusConfig.pending;

  // Phase 92: keywords 필드 지원
  const keywords = (query as any).keywords || [];

  return (
    <div className={`p-3 rounded-lg ${config.bg}`}>
      <div className="flex items-start gap-2">
        <span className="text-lg">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-xs font-medium ${config.text}`}>
              [{index + 1}] {subtypeLabel}
            </span>
            <span
              className={`px-1.5 py-0.5 text-xs rounded ${config.bg} ${config.text}`}
            >
              {config.label}
            </span>
          </div>
          <p className="text-sm text-gray-800" title={query.query}>
            {query.query}
          </p>
          {/* Phase 92: 키워드 표시 */}
          {keywords.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1">
              {keywords.map((kw: string) => (
                <span
                  key={kw}
                  className="px-1.5 py-0.5 text-xs bg-blue-100 text-blue-700 rounded"
                >
                  {kw}
                </span>
              ))}
            </div>
          )}
          {query.entity_types.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1">
              {query.entity_types.map((type) => (
                <span
                  key={type}
                  className="px-1.5 py-0.5 text-xs bg-white/50 text-gray-600 rounded"
                >
                  {type}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function SubQueryTree({ data }: SubQueryTreeProps) {
  if (!data || data.sub_queries.length === 0) return null;

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-700">복합 질의 분해</h3>
        <span
          className={`px-2 py-0.5 text-xs rounded ${
            data.merge_strategy === "parallel"
              ? "bg-purple-100 text-purple-700"
              : "bg-amber-100 text-amber-700"
          }`}
        >
          {data.merge_strategy === "parallel" ? "병렬 실행" : "순차 실행"}
        </span>
      </div>

      {data.complexity_reason && (
        <p className="text-xs text-gray-500 mb-3 italic">
          {data.complexity_reason}
        </p>
      )}

      <div className="space-y-2">
        {data.sub_queries.map((query, index) => (
          <SubQueryItem key={index} query={query} index={index} />
        ))}
      </div>
    </div>
  );
}
