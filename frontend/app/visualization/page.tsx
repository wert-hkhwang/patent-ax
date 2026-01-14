"use client";

import { useState, useEffect } from "react";
import dynamic from "next/dynamic";

// Dynamic imports for visualization components
const GraphVisualization = dynamic(
  () => import("@/components/visualization/GraphVisualization"),
  { ssr: false }
);

const VectorVisualization = dynamic(
  () => import("@/components/visualization/VectorVisualization"),
  { ssr: false }
);

interface GraphData {
  nodes: any[];
  links: any[];
  stats?: {
    total_nodes: number;
    total_edges: number;
    community_count: number;
  };
}

interface VectorData {
  points: any[];
  stats?: {
    total_vectors: number;
    collections: string[];
    dimension: number;
  };
}

interface VisualizationStats {
  graph: {
    available: boolean;
    node_count?: number;
    edge_count?: number;
    community_count?: number;
  };
  vectors: {
    available: boolean;
    total_vectors?: number;
    collections?: number;
    dimension?: number;
  };
  available_features: string[];
}

// 클라이언트에서 접속할 API 주소 (브라우저 기준)
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://3.34.237.73:8000";

export default function VisualizationPage() {
  const [activeTab, setActiveTab] = useState<"graph" | "vector">("graph");
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [vectorData, setVectorData] = useState<VectorData | null>(null);
  const [stats, setStats] = useState<VisualizationStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Graph options
  const [entityType, setEntityType] = useState<string>("");
  const [graphLimit, setGraphLimit] = useState(100);
  const [showCommunities, setShowCommunities] = useState(true);

  // Vector options
  const [searchQuery, setSearchQuery] = useState("");
  const [vectorCollection, setVectorCollection] = useState<string>("");

  // Fetch stats on mount
  useEffect(() => {
    fetchStats();
  }, []);

  const fetchStats = async () => {
    try {
      const res = await fetch(`${API_BASE}/visualization/stats`);
      if (res.ok) {
        const data = await res.json();
        setStats(data);
      }
    } catch (e) {
      console.error("Stats fetch error:", e);
    }
  };

  const fetchGraphData = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (entityType) params.append("entity_type", entityType);
      params.append("limit", graphLimit.toString());
      params.append("include_edges", "true");

      const res = await fetch(`${API_BASE}/visualization/graph?${params}`);
      if (!res.ok) throw new Error(await res.text());

      const data = await res.json();
      setGraphData(data);
    } catch (e: any) {
      setError(e.message || "그래프 데이터 로드 실패");
    } finally {
      setLoading(false);
    }
  };

  const fetchVectorData = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (searchQuery) params.append("query", searchQuery);
      if (vectorCollection) params.append("collection", vectorCollection);
      params.append("limit", "200");

      const res = await fetch(`${API_BASE}/visualization/vectors?${params}`);
      if (!res.ok) throw new Error(await res.text());

      const data = await res.json();
      setVectorData(data);
    } catch (e: any) {
      setError(e.message || "벡터 데이터 로드 실패");
    } finally {
      setLoading(false);
    }
  };

  const entityTypes = [
    { value: "", label: "전체" },
    { value: "patent", label: "특허" },
    { value: "project", label: "과제" },
    { value: "equip", label: "장비" },
    { value: "org", label: "기관" },
    { value: "applicant", label: "출원인" },
    { value: "ipc", label: "IPC" },
    { value: "ancm", label: "공고" },
    { value: "evalp", label: "배점표" },
  ];

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-bold text-gray-800">
                AX 시각화 대시보드
              </h1>
              <p className="text-sm text-gray-500">
                cuGraph + Qdrant 데이터 탐색
              </p>
            </div>
            <a
              href="/"
              className="text-sm text-blue-600 hover:text-blue-800"
            >
              채팅으로 돌아가기
            </a>
          </div>
        </div>
      </header>

      {/* Tab Navigation */}
      <div className="bg-white border-b">
        <div className="max-w-7xl mx-auto px-4">
          <nav className="flex space-x-8">
            <button
              onClick={() => setActiveTab("graph")}
              className={`py-4 px-1 border-b-2 font-medium text-sm ${
                activeTab === "graph"
                  ? "border-blue-500 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              지식그래프 (cuGraph)
            </button>
            <button
              onClick={() => setActiveTab("vector")}
              className={`py-4 px-1 border-b-2 font-medium text-sm ${
                activeTab === "vector"
                  ? "border-blue-500 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              벡터 공간 (Qdrant)
            </button>
          </nav>
        </div>
      </div>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 py-6">
        {/* Stats Overview */}
        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="bg-white rounded-lg p-4 shadow-sm">
              <p className="text-xs text-gray-500">그래프 노드</p>
              <p className="text-2xl font-bold text-gray-800">
                {(stats.graph.node_count || 0).toLocaleString()}
              </p>
            </div>
            <div className="bg-white rounded-lg p-4 shadow-sm">
              <p className="text-xs text-gray-500">그래프 엣지</p>
              <p className="text-2xl font-bold text-gray-800">
                {(stats.graph.edge_count || 0).toLocaleString()}
              </p>
            </div>
            <div className="bg-white rounded-lg p-4 shadow-sm">
              <p className="text-xs text-gray-500">벡터 수</p>
              <p className="text-2xl font-bold text-gray-800">
                {(stats.vectors.total_vectors || 0).toLocaleString()}
              </p>
            </div>
            <div className="bg-white rounded-lg p-4 shadow-sm">
              <p className="text-xs text-gray-500">커뮤니티</p>
              <p className="text-2xl font-bold text-gray-800">
                {stats.graph.community_count || 0}
              </p>
            </div>
          </div>
        )}

        {/* Error Display */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
            <p className="text-red-700 text-sm">{error}</p>
          </div>
        )}

        {/* Graph Tab */}
        {activeTab === "graph" && (
          <div className="space-y-4">
            {/* Controls */}
            <div className="bg-white rounded-lg p-4 shadow-sm">
              <div className="flex flex-wrap gap-4 items-end">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">
                    엔티티 타입
                  </label>
                  <select
                    value={entityType}
                    onChange={(e) => setEntityType(e.target.value)}
                    className="px-3 py-2 border rounded-lg text-sm"
                  >
                    {entityTypes.map((t) => (
                      <option key={t.value} value={t.value}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">
                    노드 수
                  </label>
                  <input
                    type="number"
                    value={graphLimit}
                    onChange={(e) => setGraphLimit(Number(e.target.value))}
                    className="w-24 px-3 py-2 border rounded-lg text-sm"
                    min={10}
                    max={500}
                  />
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="showCommunities"
                    checked={showCommunities}
                    onChange={(e) => setShowCommunities(e.target.checked)}
                    className="rounded"
                  />
                  <label htmlFor="showCommunities" className="text-sm text-gray-600">
                    커뮤니티 색상
                  </label>
                </div>
                <button
                  onClick={fetchGraphData}
                  disabled={loading}
                  className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm hover:bg-blue-600 disabled:opacity-50"
                >
                  {loading ? "로딩..." : "그래프 로드"}
                </button>
              </div>
            </div>

            {/* Graph Visualization */}
            <div className="bg-white rounded-lg shadow-sm overflow-hidden" style={{ height: "600px" }}>
              <GraphVisualization
                data={graphData}
                width={1200}
                height={600}
                showCommunities={showCommunities}
                highlightCentralNodes={true}
                onNodeClick={(node) => console.log("Node clicked:", node)}
              />
            </div>
          </div>
        )}

        {/* Vector Tab */}
        {activeTab === "vector" && (
          <div className="space-y-4">
            {/* Controls */}
            <div className="bg-white rounded-lg p-4 shadow-sm">
              <div className="flex flex-wrap gap-4 items-end">
                <div className="flex-1 min-w-[200px]">
                  <label className="block text-xs text-gray-500 mb-1">
                    검색 쿼리
                  </label>
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="예: 인공지능 반도체"
                    className="w-full px-3 py-2 border rounded-lg text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">
                    컬렉션
                  </label>
                  <select
                    value={vectorCollection}
                    onChange={(e) => setVectorCollection(e.target.value)}
                    className="px-3 py-2 border rounded-lg text-sm"
                  >
                    <option value="">전체</option>
                    <option value="patent">특허</option>
                    <option value="project">과제</option>
                    <option value="equip">장비</option>
                    <option value="org">기관</option>
                  </select>
                </div>
                <button
                  onClick={fetchVectorData}
                  disabled={loading}
                  className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm hover:bg-blue-600 disabled:opacity-50"
                >
                  {loading ? "로딩..." : "벡터 로드"}
                </button>
              </div>
            </div>

            {/* Vector Visualization */}
            <div className="bg-white rounded-lg shadow-sm overflow-hidden">
              <VectorVisualization
                data={vectorData}
                width={1200}
                height={600}
                colorBy="collection"
                onPointClick={(point) => console.log("Point clicked:", point)}
              />
            </div>
          </div>
        )}

        {/* Features Info */}
        <div className="mt-6 bg-white rounded-lg p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">
            시각화 기능
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-500"></span>
              <span>Louvain 커뮤니티 탐지</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-500"></span>
              <span>PageRank 중심성</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-500"></span>
              <span>Hybrid Search 결과</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-500"></span>
              <span>12종 엔티티 타입</span>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
