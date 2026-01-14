"use client";

import { WorkflowStatus, StageTiming } from "@/types/workflow";

interface WorkflowProgressProps {
  status: WorkflowStatus;
  timing?: StageTiming;
}

interface StageInfo {
  key: string;
  label: string;
  icon: string;
}

const stages: StageInfo[] = [
  { key: "analyzer", label: "분석", icon: "🔍" },
  { key: "sql_node", label: "SQL", icon: "🗄️" },
  { key: "rag_node", label: "RAG", icon: "📚" },
  { key: "merger", label: "병합", icon: "🔗" },
  { key: "generator", label: "생성", icon: "✨" },
];

const statusToStage: Record<WorkflowStatus, string> = {
  idle: "",
  analyzing: "analyzer",
  analyzed: "analyzer",
  vector_enhanced: "sql_node",
  executing_sql: "sql_node",
  searching: "rag_node",
  merging: "merger",
  generating: "generator",
  done: "done",
  error: "error",
};

// status에 따라 완료되어야 할 단계들 반환
const getCompletedStagesByStatus = (status: WorkflowStatus): Set<string> => {
  const completed = new Set<string>();

  const statusCompletions: Record<string, string[]> = {
    analyzed: ["analyzer"],
    vector_enhanced: ["analyzer"],
    executing_sql: ["analyzer"],
    searching: ["analyzer"],
    merging: ["analyzer", "sql_node", "rag_node"],
    generating: ["analyzer", "sql_node", "rag_node", "merger"],
    done: ["analyzer", "sql_node", "rag_node", "merger", "generator"],
  };

  if (statusCompletions[status]) {
    statusCompletions[status].forEach((s) => completed.add(s));
  }

  return completed;
};

export function WorkflowProgress({ status, timing }: WorkflowProgressProps) {
  const currentStage = statusToStage[status] || "";
  const isDone = status === "done";
  const isError = status === "error";

  const getStageStatus = (stageKey: string): "pending" | "active" | "completed" => {
    if (isDone) return "completed";

    // 1. timing에 시간이 기록되면 completed
    if (timing && timing[`${stageKey}_ms`] !== undefined) return "completed";

    // 2. 현재 status 기반 완료 단계 확인 (핵심 수정)
    const completedStages = getCompletedStagesByStatus(status);
    if (completedStages.has(stageKey)) return "completed";

    // 3. 현재 진행 중인 단계
    if (stageKey === currentStage) return "active";

    // 4. 인덱스 비교 (폴백)
    const stageIndex = stages.findIndex((s) => s.key === stageKey);
    const currentIndex = stages.findIndex((s) => s.key === currentStage);
    if (stageIndex < currentIndex) return "completed";

    return "pending";
  };

  const formatTime = (ms?: number) => {
    if (ms === undefined) return "";
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const totalTime = timing
    ? Object.values(timing).reduce((sum: number, val) => sum + (val || 0), 0)
    : 0;

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-700">워크플로우 진행</h3>
        {totalTime > 0 && (
          <span className="text-xs text-gray-500">
            총 {formatTime(totalTime)}
          </span>
        )}
      </div>

      <div className="space-y-2">
        {stages.map((stage, index) => {
          const stageStatus = getStageStatus(stage.key);
          const stageTime = timing?.[`${stage.key}_ms`];

          return (
            <div key={stage.key} className="flex items-center gap-3">
              {/* Status indicator */}
              <div
                className={`w-6 h-6 rounded-full flex items-center justify-center text-xs ${
                  stageStatus === "completed"
                    ? "bg-green-500 text-white"
                    : stageStatus === "active"
                    ? "bg-blue-500 text-white animate-pulse"
                    : "bg-gray-200 text-gray-500"
                }`}
              >
                {stageStatus === "completed" ? "✓" : stage.icon}
              </div>

              {/* Stage name */}
              <span
                className={`text-sm flex-1 ${
                  stageStatus === "active"
                    ? "font-medium text-blue-700"
                    : stageStatus === "completed"
                    ? "text-gray-700"
                    : "text-gray-400"
                }`}
              >
                {stage.label}
              </span>

              {/* Time */}
              {stageTime !== undefined && (
                <span className="text-xs text-gray-500 font-mono">
                  {formatTime(stageTime)}
                </span>
              )}

              {/* Progress bar for active stage */}
              {stageStatus === "active" && (
                <div className="w-12 h-1 bg-gray-200 rounded overflow-hidden">
                  <div className="h-full bg-blue-500 animate-pulse w-full"></div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {isError && (
        <div className="mt-3 px-3 py-2 bg-red-50 text-red-700 text-xs rounded">
          오류가 발생했습니다
        </div>
      )}
    </div>
  );
}
