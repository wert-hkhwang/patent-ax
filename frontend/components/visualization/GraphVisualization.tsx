"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";

// Dynamic import for SSR compatibility
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
    </div>
  ),
});

// Node type colors (matching cuGraph 12 entity types)
const NODE_COLORS: Record<string, string> = {
  patent: "#f97316",    // orange
  project: "#22c55e",   // green
  equip: "#3b82f6",     // blue
  org: "#a855f7",       // purple
  applicant: "#ec4899", // pink
  ipc: "#eab308",       // yellow
  gis: "#06b6d4",       // cyan
  tech: "#14b8a6",      // teal
  ancm: "#ef4444",      // red
  evalp: "#6366f1",     // indigo
  k12: "#8b5cf6",       // violet
  "6t": "#f59e0b",      // amber
  default: "#6b7280",   // gray
};

// Node type labels
const NODE_LABELS: Record<string, string> = {
  patent: "특허",
  project: "과제",
  equip: "장비",
  org: "기관",
  applicant: "출원인",
  ipc: "IPC",
  gis: "지역",
  tech: "기술",
  ancm: "공고",
  evalp: "배점표",
  k12: "K12",
  "6t": "6T",
};

// Relation labels (for link tooltips)
const RELATION_LABELS: Record<string, string> = {
  has_ipc: "IPC 분류",
  ipc_of: "IPC 대상",
  applied_by: "출원인",
  applied: "출원",
  owned_by: "소유 기관",
  owns: "소유",
  conducted_by: "수행 기관",
  conducts: "수행",
  uses_tech: "사용 기술",
  tech_of: "기술 적용",
  owns_equip: "보유 장비",
  related_tech: "관련 기술",
  tech_in_patent: "특허 기술",
  has_criteria: "평가 기준",
  criteria_of: "평가 대상",
  located_in: "소재지",
  location_of: "소재",
  related: "관련",
};

export interface GraphNode {
  id: string;
  name: string;
  entity_type: string;
  community?: number;
  pagerank?: number;
  val?: number;
  x?: number;
  y?: number;
}

export interface GraphLink {
  source: string;
  target: string;
  relation?: string;
  weight?: number;
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
  communities?: number[];
  stats?: {
    total_nodes: number;
    total_edges: number;
    community_count?: number;
    main_nodes?: number;
  };
}

interface GraphVisualizationProps {
  data: GraphData | null;
  width?: number;
  height?: number;
  onNodeClick?: (node: GraphNode) => void;
  showCommunities?: boolean;
  highlightCentralNodes?: boolean;
}

// Community colors (for Louvain communities)
const COMMUNITY_COLORS = [
  "#e11d48", "#db2777", "#c026d3", "#9333ea", "#7c3aed",
  "#6366f1", "#3b82f6", "#0ea5e9", "#06b6d4", "#14b8a6",
  "#10b981", "#22c55e", "#84cc16", "#eab308", "#f59e0b",
  "#f97316", "#ef4444", "#64748b", "#475569", "#334155",
];

export function GraphVisualization({
  data,
  width = 800,
  height = 600,
  onNodeClick,
  showCommunities = true,
  highlightCentralNodes = true,
}: GraphVisualizationProps) {
  const fgRef = useRef<any>();
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [isStabilized, setIsStabilized] = useState(false);

  // Process data for visualization - memoized to prevent unnecessary recalculations
  const processedData = useMemo(() => {
    if (!data) return { nodes: [], links: [] };

    const nodes = data.nodes.map((node) => ({
      ...node,
      val: highlightCentralNodes && node.pagerank
        ? Math.max(3, node.pagerank * 1000)
        : 5,
    }));

    const links = data.links.map((link) => ({
      ...link,
      color: "rgba(156, 163, 175, 0.3)",
    }));

    return { nodes, links };
  }, [data, highlightCentralNodes]);

  // Reset stabilization when data changes
  useEffect(() => {
    setIsStabilized(false);
  }, [data]);

  // Calculate community statistics for legend
  const communityStats = useMemo(() => {
    if (!data?.nodes.length) return [];

    const stats: Record<number, { count: number; types: Record<string, number> }> = {};

    data.nodes.forEach((node) => {
      if (node.community !== undefined) {
        if (!stats[node.community]) {
          stats[node.community] = { count: 0, types: {} };
        }
        stats[node.community].count++;
        const type = node.entity_type || "unknown";
        stats[node.community].types[type] = (stats[node.community].types[type] || 0) + 1;
      }
    });

    // Sort by count descending and take top 10
    return Object.entries(stats)
      .map(([id, data]) => {
        // Find dominant type
        const sortedTypes = Object.entries(data.types).sort((a, b) => b[1] - a[1]);
        const dominantType = sortedTypes[0]?.[0] || "unknown";
        const typeCount = sortedTypes.length;

        return {
          id: parseInt(id),
          count: data.count,
          dominantType,
          typeCount,
          types: data.types,
        };
      })
      .sort((a, b) => b.count - a.count)
      .slice(0, 10);
  }, [data?.nodes]);

  // Node color based on community or entity type
  const getNodeColor = useCallback(
    (node: GraphNode) => {
      if (showCommunities && node.community !== undefined) {
        return COMMUNITY_COLORS[node.community % COMMUNITY_COLORS.length];
      }
      return NODE_COLORS[node.entity_type] || NODE_COLORS.default;
    },
    [showCommunities]
  );

  // Handle node click
  const handleNodeClick = useCallback(
    (node: GraphNode) => {
      setSelectedNode(node);
      onNodeClick?.(node);

      // Center on node
      if (fgRef.current) {
        fgRef.current.centerAt(node.x, node.y, 1000);
        fgRef.current.zoom(2, 1000);
      }
    },
    [onNodeClick]
  );

  // Handle engine stop - fix node positions to prevent jumping
  const handleEngineStop = useCallback(() => {
    if (fgRef.current && !isStabilized) {
      const fg = fgRef.current;

      // Fix all node positions after simulation stops
      processedData.nodes.forEach((node: any) => {
        if (node.x !== undefined && node.y !== undefined) {
          node.fx = node.x;
          node.fy = node.y;
        }
      });

      setIsStabilized(true);
      fg?.zoomToFit(400, 50);
    }
  }, [isStabilized, processedData.nodes]);

  // Handle node hover without triggering simulation restart
  const handleNodeHover = useCallback((node: any) => {
    setHoveredNode(node as GraphNode | null);
  }, []);

  // Zoom to fit on data change - with stabilization
  useEffect(() => {
    if (fgRef.current && data?.nodes.length) {
      const fg = fgRef.current;

      // 초기 줌 조정 - 시뮬레이션 안정화 후
      const timer = setTimeout(() => {
        fg?.zoomToFit(400, 50);
      }, 2000);

      return () => clearTimeout(timer);
    }
  }, [data]);

  if (!data) {
    return (
      <div className="flex items-center justify-center h-full bg-gray-50 rounded-lg">
        <p className="text-gray-500">그래프 데이터를 로드하세요</p>
      </div>
    );
  }

  return (
    <div className="relative bg-gray-900 rounded-lg overflow-hidden">
      {/* Graph Canvas */}
      <ForceGraph2D
        ref={fgRef}
        graphData={processedData}
        width={width}
        height={height}
        nodeLabel={(node: any) =>
          `${node.name || ''}\n(${NODE_LABELS[node.entity_type] || node.entity_type || ''})${
            node.pagerank ? `\nPageRank: ${node.pagerank.toFixed(4)}` : ""
          }${node.community !== undefined ? `\n커뮤니티: ${node.community}` : ""}`
        }
        nodeColor={(node: any) => getNodeColor(node as GraphNode)}
        nodeRelSize={4}
        linkLabel={(link: any) => RELATION_LABELS[link.relation] || link.relation || ""}
        linkColor={() => "rgba(156, 163, 175, 0.5)"}
        linkWidth={(link: any) => (link.weight ? link.weight * 2 : 1)}
        linkDirectionalArrowLength={3}
        linkDirectionalArrowRelPos={1}
        onNodeClick={(node: any) => handleNodeClick(node as GraphNode)}
        onNodeHover={handleNodeHover}
        cooldownTicks={100}
        cooldownTime={2000}
        d3AlphaDecay={0.05}
        d3VelocityDecay={0.4}
        warmupTicks={50}
        onEngineStop={handleEngineStop}
        enableNodeDrag={true}
        enableZoomInteraction={true}
        enablePanInteraction={true}
        autoPauseRedraw={false}
        minZoom={0.1}
        maxZoom={10}
      />

      {/* Legend */}
      <div className="absolute top-4 left-4 bg-white/90 backdrop-blur rounded-lg p-3 shadow-lg max-h-[280px] overflow-y-auto">
        <h4 className="text-xs font-semibold text-gray-700 mb-2">
          {showCommunities ? "커뮤니티 (Louvain)" : "엔티티 타입"}
        </h4>
        <div className="space-y-1.5">
          {showCommunities && communityStats.length > 0
            ? communityStats.map((comm) => (
                <div key={comm.id} className="flex items-start gap-2">
                  <div
                    className="w-3 h-3 rounded-full mt-0.5 flex-shrink-0"
                    style={{ backgroundColor: COMMUNITY_COLORS[comm.id % COMMUNITY_COLORS.length] }}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1">
                      <span className="text-xs font-medium text-gray-700">#{comm.id}</span>
                      <span className="text-xs text-gray-400">({comm.count}개)</span>
                    </div>
                    <div className="text-[10px] text-gray-500 truncate">
                      {NODE_LABELS[comm.dominantType] || comm.dominantType}
                      {comm.typeCount > 1 && ` 외 ${comm.typeCount - 1}종`}
                    </div>
                  </div>
                </div>
              ))
            : Object.entries(NODE_LABELS).slice(0, 8).map(([type, label]) => (
                <div key={type} className="flex items-center gap-2">
                  <div
                    className="w-3 h-3 rounded-full"
                    style={{ backgroundColor: NODE_COLORS[type] }}
                  />
                  <span className="text-xs text-gray-600">{label}</span>
                </div>
              ))}
        </div>
        {showCommunities && communityStats.length > 0 && (
          <div className="mt-2 pt-2 border-t border-gray-200">
            <p className="text-[10px] text-gray-400">
              노드 수 기준 상위 {communityStats.length}개
            </p>
          </div>
        )}
      </div>

      {/* Stats */}
      {data.stats && (
        <div className="absolute top-4 right-4 bg-white/90 backdrop-blur rounded-lg p-3 shadow-lg">
          <h4 className="text-xs font-semibold text-gray-700 mb-2">통계</h4>
          <div className="space-y-1 text-xs text-gray-600">
            <p>노드: {data.stats.total_nodes.toLocaleString()}</p>
            <p>엣지: {data.stats.total_edges.toLocaleString()}</p>
            {data.stats.community_count !== undefined && (
              <p>커뮤니티: {data.stats.community_count}</p>
            )}
            {data.stats.main_nodes !== undefined && (
              <p>검색 결과: {data.stats.main_nodes}</p>
            )}
          </div>
        </div>
      )}

      {/* Selected Node Info */}
      {selectedNode && (
        <div className="absolute bottom-4 left-4 right-4 bg-white/95 backdrop-blur rounded-lg p-4 shadow-lg">
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <div
                  className="w-3 h-3 rounded-full"
                  style={{ backgroundColor: getNodeColor(selectedNode) }}
                />
                <span className="text-sm font-semibold text-gray-800">
                  {selectedNode.name}
                </span>
                <span className="px-2 py-0.5 text-xs bg-gray-100 rounded">
                  {NODE_LABELS[selectedNode.entity_type] || selectedNode.entity_type}
                </span>
              </div>
              <p className="text-xs text-gray-500">ID: {selectedNode.id}</p>
              {selectedNode.pagerank !== undefined && (
                <p className="text-xs text-gray-500">
                  PageRank: {selectedNode.pagerank.toFixed(6)}
                </p>
              )}
              {selectedNode.community !== undefined && (
                <p className="text-xs text-gray-500">
                  커뮤니티: {selectedNode.community}
                </p>
              )}
            </div>
            <button
              onClick={() => setSelectedNode(null)}
              className="text-gray-400 hover:text-gray-600"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Hover Tooltip */}
      {hoveredNode && !selectedNode && (
        <div className="absolute bottom-4 left-4 bg-black/75 text-white rounded px-3 py-2 text-xs">
          {hoveredNode.name} ({NODE_LABELS[hoveredNode.entity_type] || hoveredNode.entity_type})
        </div>
      )}
    </div>
  );
}

export default GraphVisualization;
