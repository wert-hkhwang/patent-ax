"use client";

import React, { useState, useEffect, useCallback } from "react";
import dynamic from "next/dynamic";
import { SourceBadges } from "./SourceBadges";

// GraphVisualization 동적 임포트
const GraphVisualization = dynamic(
  () => import("./GraphVisualization").then((mod) => mod.GraphVisualization),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center h-[300px] bg-gray-50 rounded">
        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500" />
      </div>
    ),
  }
);

// 엔티티 타입 색상
const ENTITY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  patent: { bg: "bg-orange-50", text: "text-orange-700", border: "border-orange-200" },
  project: { bg: "bg-green-50", text: "text-green-700", border: "border-green-200" },
  equip: { bg: "bg-blue-50", text: "text-blue-700", border: "border-blue-200" },
  org: { bg: "bg-purple-50", text: "text-purple-700", border: "border-purple-200" },
  applicant: { bg: "bg-pink-50", text: "text-pink-700", border: "border-pink-200" },
  ipc: { bg: "bg-yellow-50", text: "text-yellow-700", border: "border-yellow-200" },
  ancm: { bg: "bg-red-50", text: "text-red-700", border: "border-red-200" },
  evalp: { bg: "bg-indigo-50", text: "text-indigo-700", border: "border-indigo-200" },
};

const ENTITY_LABELS: Record<string, string> = {
  patent: "특허",
  project: "과제",
  equip: "장비",
  org: "기관",
  applicant: "출원인",
  ipc: "IPC",
  ancm: "공고",
  evalp: "배점표",
};

// Phase 99.3: 다양한 소스 형식 지원
interface Source {
  // RAG 결과 소스
  node_id?: string;
  name?: string;
  entity_type?: string;
  score?: number;
  community?: number;
  pagerank?: number;
  connections?: {
    ipc?: number;
    applicant?: number;
    org?: number;
    related?: number;
  };
  // Phase 99.3: 추가 메타데이터
  metadata?: {
    community?: number;
    pagerank?: number;
    connections?: {
      ipc?: number;
      applicant?: number;
      org?: number;
      related?: number;
    };
    content?: string;
  };
  // 집계 소스 (sql, rag, graph 등)
  type?: string;
  count?: number;
  tables?: string[];
  strategy?: string;
}

interface StageTiming {
  analyzer_ms?: number;
  vector_enhancer_ms?: number;
  sql_node_ms?: number;
  rag_node_ms?: number;
  merger_ms?: number;
  generator_ms?: number;
}

interface GraphData {
  nodes: any[];
  links: any[];
  stats?: {
    total_nodes: number;
    total_edges: number;
    community_count?: number;
    main_nodes?: number;
  };
}

// Phase 102: SSE에서 전달받는 graph_data 형식
interface SSEGraphData {
  nodes: Array<{
    id: string;
    name: string;
    type: string;
    score: number;
    color?: string;
  }>;
  edges: Array<{
    from_id: string;
    to_id: string;
    relation: string;
  }>;
}

interface MessageVisualizationPanelProps {
  sources: Source[];
  timing?: StageTiming;
  elapsedMs?: number;
  confidenceScore?: number;  // Phase 102
  graphData?: SSEGraphData;  // Phase 102
}

type TabType = "graph" | "sources" | "timing";

const API_BASE = typeof window !== "undefined"
  ? `http://${window.location.hostname}:8000`
  : "http://localhost:8000";

export function MessageVisualizationPanel({
  sources,
  timing,
  elapsedMs,
  confidenceScore,  // Phase 102
  graphData: sseGraphData,  // Phase 102: SSE에서 전달받은 graph_data
}: MessageVisualizationPanelProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState<TabType>("sources");
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [isLoadingGraph, setIsLoadingGraph] = useState(false);

  // Phase 102: SSE graph_data를 GraphVisualization 형식으로 변환
  useEffect(() => {
    if (sseGraphData && sseGraphData.nodes.length > 0) {
      const convertedData: GraphData = {
        nodes: sseGraphData.nodes.map((n) => ({
          id: n.id,
          name: n.name,
          entity_type: n.type,
          val: n.score * 10,  // 노드 크기
        })),
        links: sseGraphData.edges.map((e) => ({
          source: e.from_id,
          target: e.to_id,
          relation: e.relation,
        })),
        stats: {
          total_nodes: sseGraphData.nodes.length,
          total_edges: sseGraphData.edges.length,
          main_nodes: sseGraphData.nodes.filter((n) => n.type === "patent").length,
        },
      };
      setGraphData(convertedData);
    }
  }, [sseGraphData]);

  // 그래프 데이터 로드 (SSE에서 데이터가 없을 때만)
  const loadGraphData = useCallback(async () => {
    if (!sources.length || graphData) return;  // Phase 102: 이미 데이터 있으면 스킵

    setIsLoadingGraph(true);
    try {
      const nodeIds = sources
        .filter((s) => s.node_id)
        .map((s) => s.node_id)
        .join(",");

      if (!nodeIds) return;

      const response = await fetch(
        `${API_BASE}/visualization/graph/subgraph?node_ids=${encodeURIComponent(nodeIds)}&depth=1`
      );

      if (response.ok) {
        const data = await response.json();
        setGraphData(data);
      }
    } catch (error) {
      console.error("그래프 데이터 로드 실패:", error);
    } finally {
      setIsLoadingGraph(false);
    }
  }, [sources, graphData]);

  // 그래프 탭 선택 시 데이터 로드
  useEffect(() => {
    if (activeTab === "graph" && isExpanded && !graphData && !isLoadingGraph) {
      loadGraphData();
    }
  }, [activeTab, isExpanded, graphData, isLoadingGraph, loadGraphData]);

  // Phase 99.3: timing만 있어도 패널 표시
  const hasData = sources.length > 0 || (timing && Object.keys(timing).length > 0) || elapsedMs;
  if (!hasData) return null;

  const tabs = [
    { id: "sources" as TabType, label: "소스 목록", icon: "📋", count: sources.length },
    { id: "graph" as TabType, label: "관계 그래프", icon: "📊" },
    { id: "timing" as TabType, label: "처리 시간", icon: "⏱️" },
  ];

  return (
    <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden bg-white">
      {/* 헤더 - 토글 버튼 */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors"
      >
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <span>{isExpanded ? "▼" : "▶"}</span>
          <span className="font-medium">시각화 및 상세 정보</span>
          {sources.length > 0 && (
            <span className="px-1.5 py-0.5 text-xs bg-blue-100 text-blue-700 rounded">
              {sources.length}개 소스
            </span>
          )}
          {/* Phase 102: 신뢰도 점수 표시 */}
          {confidenceScore !== undefined && (
            <span className={`px-1.5 py-0.5 text-xs rounded ${
              confidenceScore >= 0.7 ? "bg-green-100 text-green-700" :
              confidenceScore >= 0.4 ? "bg-yellow-100 text-yellow-700" :
              "bg-red-100 text-red-700"
            }`}>
              신뢰도 {(confidenceScore * 100).toFixed(0)}%
            </span>
          )}
          {/* Phase 102: 그래프 노드 수 표시 */}
          {sseGraphData && sseGraphData.nodes.length > 0 && (
            <span className="px-1.5 py-0.5 text-xs bg-purple-100 text-purple-700 rounded">
              {sseGraphData.nodes.length}개 노드
            </span>
          )}
          {elapsedMs && (
            <span className="text-xs text-gray-400">
              {(elapsedMs / 1000).toFixed(1)}초
            </span>
          )}
        </div>
      </button>

      {/* 확장된 패널 */}
      {isExpanded && (
        <div className="border-t border-gray-200">
          {/* 탭 버튼 */}
          <div className="flex border-b border-gray-200">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium transition-colors ${
                  activeTab === tab.id
                    ? "text-blue-600 border-b-2 border-blue-600 -mb-px bg-white"
                    : "text-gray-500 hover:text-gray-700 hover:bg-gray-50"
                }`}
              >
                <span>{tab.icon}</span>
                <span>{tab.label}</span>
                {tab.count !== undefined && (
                  <span className="text-xs text-gray-400">({tab.count})</span>
                )}
              </button>
            ))}
          </div>

          {/* 탭 콘텐츠 */}
          <div className="p-3">
            {/* 소스 목록 탭 */}
            {activeTab === "sources" && (
              <div className="space-y-2 max-h-[400px] overflow-y-auto">
                {sources.length === 0 ? (
                  <div className="text-center py-4 text-gray-500 text-sm">
                    검색 소스 정보가 없습니다
                  </div>
                ) : (
                  sources.map((source, idx) => {
                    // Phase 99.3: 집계 소스 (type 기반) 처리
                    if (source.type && !source.node_id) {
                      const typeLabels: Record<string, string> = {
                        sql: "SQL",
                        rag: "RAG",
                        graph: "Graph",
                      };
                      const typeLabel = typeLabels[source.type] || source.type.toUpperCase();

                      return (
                        <div
                          key={`${source.type}-${idx}`}
                          className="p-2.5 rounded-lg border bg-gray-50 border-gray-200"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="px-2 py-0.5 text-xs font-medium rounded bg-gray-200 text-gray-700">
                                {typeLabel}
                              </span>
                              {source.tables && source.tables.length > 0 && (
                                <span className="text-xs text-gray-500">
                                  테이블: {source.tables.join(", ")}
                                </span>
                              )}
                              {source.strategy && (
                                <span className="text-xs text-gray-500">
                                  전략: {source.strategy}
                                </span>
                              )}
                            </div>
                            <span className="text-sm font-bold text-blue-600">
                              {source.count ?? 0}건
                            </span>
                          </div>
                        </div>
                      );
                    }

                    // RAG 결과 소스 (node_id 기반)
                    const colors = ENTITY_COLORS[source.entity_type || ""] || {
                      bg: "bg-gray-50",
                      text: "text-gray-700",
                      border: "border-gray-200",
                    };
                    const label = ENTITY_LABELS[source.entity_type || ""] || source.entity_type || "기타";

                    // Phase 99.3: metadata에서 community/pagerank 추출
                    const community = source.community ?? source.metadata?.community;
                    const pagerank = source.pagerank ?? source.metadata?.pagerank;
                    const connections = source.connections ?? source.metadata?.connections;

                    return (
                      <div
                        key={source.node_id || idx}
                        className={`p-2.5 rounded-lg border ${colors.bg} ${colors.border}`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <span
                                className={`px-1.5 py-0.5 text-[10px] font-medium rounded ${colors.text} ${colors.bg} border ${colors.border}`}
                              >
                                {label}
                              </span>
                              <span className="text-sm font-medium text-gray-800 truncate">
                                {source.name || source.node_id}
                              </span>
                            </div>
                            <SourceBadges
                              community={community}
                              pagerank={pagerank}
                              connections={connections}
                            />
                          </div>
                          {source.score !== undefined && (
                            <div className="flex flex-col items-end">
                              <span className="text-sm font-bold text-blue-600">
                                {(source.score * 100).toFixed(0)}%
                              </span>
                              <div className="w-12 h-1.5 bg-gray-200 rounded-full mt-1">
                                <div
                                  className="h-full bg-blue-500 rounded-full"
                                  style={{ width: `${source.score * 100}%` }}
                                />
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            )}

            {/* 관계 그래프 탭 */}
            {activeTab === "graph" && (
              <div>
                {isLoadingGraph ? (
                  <div className="flex items-center justify-center h-[300px] bg-gray-50 rounded">
                    <div className="text-center">
                      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-2" />
                      <p className="text-sm text-gray-500">그래프 로딩 중...</p>
                    </div>
                  </div>
                ) : graphData ? (
                  <div className="rounded overflow-hidden">
                    <GraphVisualization
                      data={graphData}
                      width={600}
                      height={350}
                      showCommunities={true}
                      highlightCentralNodes={true}
                    />
                    {graphData.stats && (
                      <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
                        <span>노드: {graphData.stats.total_nodes}</span>
                        <span>엣지: {graphData.stats.total_edges}</span>
                        {graphData.stats.main_nodes && (
                          <span>검색 결과: {graphData.stats.main_nodes}</span>
                        )}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="flex items-center justify-center h-[300px] bg-gray-50 rounded">
                    <p className="text-sm text-gray-500">그래프 데이터 없음</p>
                  </div>
                )}
              </div>
            )}

            {/* 처리 시간 탭 */}
            {activeTab === "timing" && timing && (
              <div className="space-y-2">
                {Object.entries(timing).map(([stage, ms]) => {
                  if (ms === undefined || ms === null) return null;

                  const stageLabels: Record<string, string> = {
                    analyzer_ms: "쿼리 분석",
                    vector_enhancer_ms: "벡터 강화",
                    sql_node_ms: "SQL 실행",
                    rag_node_ms: "RAG 검색",
                    merger_ms: "결과 병합",
                    generator_ms: "응답 생성",
                  };

                  const label = stageLabels[stage] || stage;
                  const seconds = (ms as number) / 1000;
                  const maxMs = Math.max(...Object.values(timing).filter((v): v is number => typeof v === "number"));
                  const percentage = maxMs > 0 ? ((ms as number) / maxMs) * 100 : 0;

                  return (
                    <div key={stage} className="flex items-center gap-3">
                      <span className="text-xs text-gray-600 w-20 truncate">
                        {label}
                      </span>
                      <div className="flex-1 h-4 bg-gray-100 rounded overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-blue-400 to-blue-600 rounded"
                          style={{ width: `${percentage}%` }}
                        />
                      </div>
                      <span className="text-xs text-gray-500 w-16 text-right">
                        {seconds.toFixed(2)}초
                      </span>
                    </div>
                  );
                })}
                {elapsedMs && (
                  <div className="pt-2 mt-2 border-t border-gray-200">
                    <div className="flex items-center justify-between text-sm">
                      <span className="font-medium text-gray-700">전체 시간</span>
                      <span className="font-bold text-blue-600">
                        {(elapsedMs / 1000).toFixed(2)}초
                      </span>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default MessageVisualizationPanel;
