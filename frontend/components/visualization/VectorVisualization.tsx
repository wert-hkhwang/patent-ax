"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";

// Dynamic import for SSR compatibility
const Plot = dynamic(() => import("react-plotly.js"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
    </div>
  ),
});

// Collection colors
const COLLECTION_COLORS: Record<string, string> = {
  patent: "#f97316",
  project: "#22c55e",
  equip: "#3b82f6",
  org: "#a855f7",
  applicant: "#ec4899",
  ipc: "#eab308",
  ancm: "#ef4444",
  evalp: "#6366f1",
  default: "#6b7280",
};

// Collection labels
const COLLECTION_LABELS: Record<string, string> = {
  patent: "특허",
  project: "과제",
  equip: "장비",
  org: "기관",
  applicant: "출원인",
  ipc: "IPC",
  ancm: "공고",
  evalp: "배점표",
};

export interface VectorPoint {
  id: string;
  name: string;
  collection: string;
  x: number;  // UMAP dimension 1
  y: number;  // UMAP dimension 2
  score?: number;
  metadata?: Record<string, any>;
}

export interface VectorData {
  points: VectorPoint[];
  stats?: {
    total_vectors: number;
    collections: string[];
    dimension: number;
  };
}

interface VectorVisualizationProps {
  data: VectorData | null;
  width?: number;
  height?: number;
  onPointClick?: (point: VectorPoint) => void;
  colorBy?: "collection" | "score";
  highlightQuery?: VectorPoint[];
}

export function VectorVisualization({
  data,
  width = 800,
  height = 600,
  onPointClick,
  colorBy = "collection",
  highlightQuery,
}: VectorVisualizationProps) {
  const [selectedPoint, setSelectedPoint] = useState<VectorPoint | null>(null);

  // Group points by collection for different traces
  const traces = useMemo(() => {
    if (!data?.points.length) return [];

    if (colorBy === "collection") {
      // Group by collection
      const grouped = data.points.reduce((acc, point) => {
        const key = point.collection || "default";
        if (!acc[key]) acc[key] = [];
        acc[key].push(point);
        return acc;
      }, {} as Record<string, VectorPoint[]>);

      return Object.entries(grouped).map(([collection, points]) => ({
        x: points.map((p) => p.x),
        y: points.map((p) => p.y),
        text: points.map(
          (p) =>
            `${p.name}<br>Collection: ${COLLECTION_LABELS[collection] || collection}${
              p.score !== undefined ? `<br>Score: ${p.score.toFixed(3)}` : ""
            }`
        ),
        customdata: points,
        mode: "markers" as const,
        type: "scatter" as const,
        name: COLLECTION_LABELS[collection] || collection,
        marker: {
          size: 8,
          color: COLLECTION_COLORS[collection] || COLLECTION_COLORS.default,
          opacity: 0.7,
          line: {
            width: 1,
            color: "white",
          },
        },
        hoverinfo: "text" as const,
      }));
    } else {
      // Color by score
      const scores = data.points.map((p) => p.score || 0);
      return [
        {
          x: data.points.map((p) => p.x),
          y: data.points.map((p) => p.y),
          text: data.points.map(
            (p) =>
              `${p.name}<br>Collection: ${
                COLLECTION_LABELS[p.collection] || p.collection
              }${p.score !== undefined ? `<br>Score: ${p.score.toFixed(3)}` : ""}`
          ),
          customdata: data.points,
          mode: "markers" as const,
          type: "scatter" as const,
          name: "Vectors",
          marker: {
            size: 8,
            color: scores,
            colorscale: "Viridis",
            showscale: true,
            colorbar: {
              title: "Score",
              thickness: 15,
            },
            opacity: 0.7,
            line: {
              width: 1,
              color: "white",
            },
          },
          hoverinfo: "text" as const,
        },
      ];
    }
  }, [data, colorBy]);

  // Add highlight trace for query results
  const highlightTrace = useMemo(() => {
    if (!highlightQuery?.length) return null;

    return {
      x: highlightQuery.map((p) => p.x),
      y: highlightQuery.map((p) => p.y),
      text: highlightQuery.map(
        (p) => `<b>검색 결과</b><br>${p.name}<br>Score: ${p.score?.toFixed(3) || "N/A"}`
      ),
      customdata: highlightQuery,
      mode: "markers" as const,
      type: "scatter" as const,
      name: "검색 결과",
      marker: {
        size: 14,
        color: "#ef4444",
        symbol: "star",
        opacity: 1,
        line: {
          width: 2,
          color: "white",
        },
      },
      hoverinfo: "text" as const,
    };
  }, [highlightQuery]);

  const allTraces = highlightTrace ? [...traces, highlightTrace] : traces;

  const layout = useMemo(
    () => ({
      width,
      height,
      title: {
        text: "벡터 공간 시각화 (UMAP 2D)",
        font: { size: 14, color: "#374151" },
      },
      xaxis: {
        title: "UMAP Dimension 1",
        showgrid: true,
        gridcolor: "#e5e7eb",
        zeroline: false,
      },
      yaxis: {
        title: "UMAP Dimension 2",
        showgrid: true,
        gridcolor: "#e5e7eb",
        zeroline: false,
      },
      paper_bgcolor: "white",
      plot_bgcolor: "#f9fafb",
      legend: {
        x: 1,
        y: 1,
        xanchor: "right" as const,
        bgcolor: "rgba(255,255,255,0.8)",
      },
      margin: { l: 60, r: 30, t: 50, b: 60 },
      hovermode: "closest" as const,
    }),
    [width, height]
  );

  const handleClick = (event: any) => {
    if (event.points?.[0]) {
      const point = event.points[0].customdata as VectorPoint;
      setSelectedPoint(point);
      onPointClick?.(point);
    }
  };

  if (!data) {
    return (
      <div className="flex items-center justify-center h-full bg-gray-50 rounded-lg">
        <p className="text-gray-500">벡터 데이터를 로드하세요</p>
      </div>
    );
  }

  return (
    <div className="relative bg-white rounded-lg overflow-hidden shadow-sm border border-gray-200">
      {/* Plot */}
      <Plot
        data={allTraces as any}
        layout={layout}
        config={{
          displayModeBar: true,
          displaylogo: false,
          modeBarButtonsToRemove: ["lasso2d", "select2d"],
          responsive: true,
        }}
        onClick={handleClick}
      />

      {/* Stats */}
      {data.stats && (
        <div className="absolute top-16 right-4 bg-white/90 backdrop-blur rounded-lg p-3 shadow-lg">
          <h4 className="text-xs font-semibold text-gray-700 mb-2">Qdrant 통계</h4>
          <div className="space-y-1 text-xs text-gray-600">
            <p>총 벡터: {data.stats.total_vectors.toLocaleString()}</p>
            <p>차원: {data.stats.dimension}</p>
            <p>컬렉션: {data.stats.collections.length}개</p>
          </div>
        </div>
      )}

      {/* Selected Point Info */}
      {selectedPoint && (
        <div className="absolute bottom-4 left-4 right-4 bg-white/95 backdrop-blur rounded-lg p-4 shadow-lg">
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <div
                  className="w-3 h-3 rounded-full"
                  style={{
                    backgroundColor:
                      COLLECTION_COLORS[selectedPoint.collection] ||
                      COLLECTION_COLORS.default,
                  }}
                />
                <span className="text-sm font-semibold text-gray-800">
                  {selectedPoint.name}
                </span>
                <span className="px-2 py-0.5 text-xs bg-gray-100 rounded">
                  {COLLECTION_LABELS[selectedPoint.collection] ||
                    selectedPoint.collection}
                </span>
              </div>
              <p className="text-xs text-gray-500">ID: {selectedPoint.id}</p>
              {selectedPoint.score !== undefined && (
                <p className="text-xs text-gray-500">
                  유사도: {(selectedPoint.score * 100).toFixed(1)}%
                </p>
              )}
              <p className="text-xs text-gray-500">
                좌표: ({selectedPoint.x.toFixed(2)}, {selectedPoint.y.toFixed(2)})
              </p>
            </div>
            <button
              onClick={() => setSelectedPoint(null)}
              className="text-gray-400 hover:text-gray-600"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Color Mode Toggle */}
      <div className="absolute top-16 left-4 bg-white/90 backdrop-blur rounded-lg p-2 shadow-lg">
        <span className="text-xs text-gray-500">색상 기준</span>
        <div className="flex gap-1 mt-1">
          <button
            className={`px-2 py-1 text-xs rounded ${
              colorBy === "collection"
                ? "bg-blue-500 text-white"
                : "bg-gray-100 text-gray-600"
            }`}
          >
            컬렉션
          </button>
          <button
            className={`px-2 py-1 text-xs rounded ${
              colorBy === "score"
                ? "bg-blue-500 text-white"
                : "bg-gray-100 text-gray-600"
            }`}
          >
            유사도
          </button>
        </div>
      </div>
    </div>
  );
}

export default VectorVisualization;
