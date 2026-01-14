"use client";

import { useState } from "react";
import { SQLResult, MultiSQLResults } from "@/types/workflow";

// 엔티티별 라벨 및 색상 정의
const ENTITY_CONFIG: Record<string, { label: string; bgColor: string; textColor: string; icon: string }> = {
  patent: { label: "특허", bgColor: "bg-orange-50", textColor: "text-orange-800", icon: "📜" },
  project: { label: "연구과제", bgColor: "bg-green-50", textColor: "text-green-800", icon: "📊" },
  proposal: { label: "제안서", bgColor: "bg-purple-50", textColor: "text-purple-800", icon: "📝" },
  equipment: { label: "연구장비", bgColor: "bg-blue-50", textColor: "text-blue-800", icon: "🔬" },
};

interface SingleResultTableProps {
  result: SQLResult;
  entityType?: string;
  defaultExpanded?: boolean;
}

function SingleResultTable({ result, entityType, defaultExpanded = false }: SingleResultTableProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const config = entityType ? ENTITY_CONFIG[entityType] : null;

  const hasMoreRows = result.row_count > result.rows.length;

  // 기본 스타일 (엔티티 타입 없을 때)
  const headerBg = config?.bgColor || "bg-blue-50";
  const headerText = config?.textColor || "text-blue-800";
  const icon = config?.icon || "🗄️";
  const label = config?.label || "SQL 결과";

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
      {/* Header */}
      <div
        className={`flex items-center justify-between px-4 py-3 ${headerBg} cursor-pointer hover:opacity-90 transition`}
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2">
          <span>{icon}</span>
          <h3 className={`text-sm font-semibold ${headerText}`}>{label}</h3>
          <span className={`px-2 py-0.5 text-xs ${headerBg} ${headerText} rounded border`}>
            {result.row_count}건
          </span>
        </div>
        <div className="flex items-center gap-3">
          {result.execution_time_ms > 0 && (
            <span className={`text-xs ${headerText}`}>
              {result.execution_time_ms.toFixed(0)}ms
            </span>
          )}
          <span className={`${headerText} text-sm`}>
            {isExpanded ? "▼" : "▶"}
          </span>
        </div>
      </div>

      {/* SQL Query */}
      {isExpanded && result.generated_sql && (
        <div className="px-4 py-2 bg-slate-900">
          <pre className="text-xs text-green-400 font-mono whitespace-pre-wrap overflow-x-auto">
            {result.generated_sql}
          </pre>
        </div>
      )}

      {/* Table */}
      {isExpanded && result.columns.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b">
                {result.columns.map((col, i) => (
                  <th
                    key={i}
                    className="px-3 py-2 text-left text-xs font-medium text-gray-600 uppercase tracking-wider"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {result.rows.map((row, rowIdx) => (
                <tr key={rowIdx} className="hover:bg-gray-50">
                  {row.map((cell, cellIdx) => (
                    <td
                      key={cellIdx}
                      className="px-3 py-2 text-gray-700 max-w-xs truncate"
                      title={String(cell)}
                    >
                      {cell === null ? (
                        <span className="text-gray-400 italic">null</span>
                      ) : (
                        String(cell)
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* More rows indicator */}
      {isExpanded && hasMoreRows && (
        <div className="px-4 py-2 text-center text-xs text-gray-500 bg-gray-50 border-t">
          +{result.row_count - result.rows.length}건 더 있음
        </div>
      )}

      {/* Collapsed preview */}
      {!isExpanded && result.columns.length > 0 && (
        <div className="px-4 py-2 text-xs text-gray-500">
          컬럼: {result.columns.slice(0, 4).join(", ")}
          {result.columns.length > 4 && ` 외 ${result.columns.length - 4}개`}
        </div>
      )}
    </div>
  );
}

interface SQLResultTableProps {
  result?: SQLResult | null;
  multiResults?: MultiSQLResults | null;
}

export function SQLResultTable({ result, multiResults }: SQLResultTableProps) {
  // Phase 19: 다중 엔티티 결과 처리
  if (multiResults && Object.keys(multiResults).length > 0) {
    const entries = Object.entries(multiResults);
    const totalRows = entries.reduce((sum, [_, r]) => sum + (r?.row_count || 0), 0);

    return (
      <div className="space-y-3">
        {/* 다중 결과 헤더 */}
        <div className="flex items-center gap-2 px-2">
          <span className="text-sm font-medium text-gray-700">
            다중 검색 결과
          </span>
          <span className="px-2 py-0.5 text-xs bg-gray-200 text-gray-700 rounded">
            {entries.length}개 타입 / 총 {totalRows}건
          </span>
        </div>

        {/* 각 엔티티별 테이블 */}
        {entries.map(([entityType, entityResult]) => (
          entityResult && (
            <SingleResultTable
              key={entityType}
              result={entityResult}
              entityType={entityType}
              defaultExpanded={true}
            />
          )
        ))}
      </div>
    );
  }

  // 단일 결과 처리 (기존 로직)
  if (!result) return null;

  return <SingleResultTable result={result} defaultExpanded={false} />;
}
