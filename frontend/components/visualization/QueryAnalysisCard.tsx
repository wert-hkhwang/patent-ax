"use client";

import { AnalysisResult, QueryType } from "@/types/workflow";

interface QueryAnalysisCardProps {
  analysis: AnalysisResult | null;
  expandedKeywords?: string[] | null;  // Phase 43: 벡터 확장 키워드
}

const queryTypeConfig: Record<
  QueryType,
  { label: string; color: string; icon: string }
> = {
  sql: { label: "SQL", color: "bg-blue-500", icon: "🗄️" },
  rag: { label: "RAG", color: "bg-green-500", icon: "🔍" },
  hybrid: { label: "Hybrid", color: "bg-purple-500", icon: "⚡" },
  simple: { label: "Simple", color: "bg-gray-500", icon: "💬" },
};

const entityTypeLabels: Record<string, string> = {
  patent: "특허",
  project: "연구과제",
  equip: "장비",
  org: "기관",
  applicant: "출원인",
  ipc: "IPC분류",
  gis: "지역",
  tech: "기술분류",
  ancm: "공고",
  evalp: "배점표",
  evalp_pref: "우대감점",  // Phase 91: 우대/감점 정보 표시용
  k12: "K12분류",
  "6t": "6T분류",
};

export function QueryAnalysisCard({ analysis, expandedKeywords }: QueryAnalysisCardProps) {
  if (!analysis) return null;

  const typeConfig = queryTypeConfig[analysis.query_type] || queryTypeConfig.simple;

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">쿼리 분석</h3>
        <div className="flex items-center gap-2">
          <span
            className={`px-2 py-1 text-xs font-medium text-white rounded ${typeConfig.color}`}
          >
            {typeConfig.icon} {typeConfig.label}
          </span>
          {analysis.is_compound && (
            <span className="px-2 py-1 text-xs font-medium text-orange-700 bg-orange-100 rounded">
              복합 질의
            </span>
          )}
        </div>
      </div>

      {analysis.query_intent && (
        <div>
          <span className="text-xs text-gray-500">의도:</span>
          <p className="text-sm text-gray-800">{analysis.query_intent}</p>
        </div>
      )}

      {analysis.entity_types.length > 0 && (
        <div>
          <span className="text-xs text-gray-500">엔티티 타입:</span>
          <div className="flex flex-wrap gap-1 mt-1">
            {analysis.entity_types.map((type) => (
              <span
                key={type}
                className="px-2 py-0.5 text-xs bg-gray-100 text-gray-700 rounded"
              >
                {entityTypeLabels[type] || type}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Phase 43: LLM 추출 키워드 */}
      {analysis.keywords.length > 0 && (
        <div>
          <span className="text-xs text-gray-500">LLM 키워드:</span>
          <div className="flex flex-wrap gap-1 mt-1">
            {analysis.keywords.map((keyword, i) => (
              <span
                key={i}
                className="px-2 py-0.5 text-xs bg-blue-50 text-blue-700 rounded"
              >
                {keyword}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Phase 43: 벡터 확장 키워드 (새로 추가된 것만 표시) */}
      {expandedKeywords && expandedKeywords.length > 0 && (
        <>
          {/* 확장된 키워드 (LLM 키워드에 없는 것) */}
          {expandedKeywords.filter(kw => !analysis.keywords.includes(kw)).length > 0 && (
            <div>
              <span className="text-xs text-gray-500">확장 키워드:</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {expandedKeywords
                  .filter(kw => !analysis.keywords.includes(kw))
                  .map((keyword, i) => (
                    <span
                      key={i}
                      className="px-2 py-0.5 text-xs bg-green-50 text-green-700 rounded border border-green-200"
                    >
                      + {keyword}
                    </span>
                  ))}
              </div>
            </div>
          )}

          {/* 최종 검색 키워드 */}
          <div className="pt-2 border-t border-gray-100">
            <span className="text-xs text-gray-500">검색 적용:</span>
            <div className="flex flex-wrap gap-1 mt-1">
              {expandedKeywords.map((keyword, i) => (
                <span
                  key={i}
                  className={`px-2 py-0.5 text-xs rounded ${
                    analysis.keywords.includes(keyword)
                      ? "bg-blue-100 text-blue-800 font-medium"
                      : "bg-gray-100 text-gray-600"
                  }`}
                >
                  {keyword}
                </span>
              ))}
            </div>
          </div>
        </>
      )}

      {analysis.related_tables.length > 0 && (
        <div>
          <span className="text-xs text-gray-500">관련 테이블:</span>
          <div className="flex flex-wrap gap-1 mt-1">
            {analysis.related_tables.map((table) => (
              <span
                key={table}
                className="px-2 py-0.5 text-xs font-mono bg-slate-100 text-slate-700 rounded"
              >
                {table}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
