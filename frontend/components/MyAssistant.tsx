"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  QueryAnalysisCard,
  WorkflowProgress,
  SQLResultTable,
  RAGResultCards,
  SubQueryTree,
} from "./visualization";
import { MessageVisualizationPanel } from "./visualization/MessageVisualizationPanel";
import {
  ExtendedMessage,
  WorkflowStatus,
  AnalysisResult,
  SubQueryData,
  SQLResult,
  MultiSQLResults,
  RAGResult,
  StageTiming,
} from "@/types/workflow";
import type { SearchMode, UserLevel } from "@/app/page";

// 백엔드 API URL (프록시 사용)
const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api";

// 워크플로우 상태
interface WorkflowState {
  status: WorkflowStatus;
  analysis: AnalysisResult | null;
  subqueries: SubQueryData | null;
  sql_result: SQLResult | null;
  multi_sql_results: MultiSQLResults | null;  // Phase 19: 다중 엔티티 SQL 결과
  rag_result: RAGResult | null;
  timing: StageTiming | null;
  elapsed_ms: number;
  expanded_keywords: string[] | null;  // Phase 43: 벡터 확장 키워드
}

// 채팅 상태
interface ChatState {
  messages: ExtendedMessage[];
  isLoading: boolean;
  workflow: WorkflowState;
}

const initialWorkflowState: WorkflowState = {
  status: "idle",
  analysis: null,
  subqueries: null,
  sql_result: null,
  multi_sql_results: null,
  rag_result: null,
  timing: null,
  elapsed_ms: 0,
  expanded_keywords: null,  // Phase 43
};

// SSE 기반 스트리밍 채팅 훅
function useStreamingChat(searchMode: SearchMode, level: UserLevel) {
  const [state, setState] = useState<ChatState>({
    messages: [],
    isLoading: false,
    workflow: initialWorkflowState,
  });

  const sendMessage = useCallback(async (content: string) => {
    // 워크플로우 상태 초기화
    setState((prev) => ({
      ...prev,
      messages: [
        ...prev.messages,
        { role: "user", content },
        { role: "assistant", content: "" },
      ],
      isLoading: true,
      workflow: { ...initialWorkflowState, status: "analyzing" },
    }));

    try {
      // 모드에 따른 API 요청 본문 구성
      const requestBody: Record<string, unknown> = {
        query: content,
        session_id: "default",
        level: level,  // Phase 103: 수준 전달
      };

      // entity_types는 백엔드에서 자동으로 ["patent"]로 설정됨

      const response = await fetch(`${API_URL}/workflow/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) throw new Error("No response body");

      let accumulatedText = "";
      let currentMetadata: ExtendedMessage["metadata"] = {};
      let currentEventType = "";  // Phase 50: SSE 이벤트 타입 저장
      let pendingJsonBuffer = "";  // Phase 51.3: 불완전한 JSON 버퍼링

      let lineBuffer = "";  // Phase 51.3: 불완전한 라인 버퍼

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        // 이전 청크에서 남은 불완전한 라인과 합침
        const fullChunk = lineBuffer + chunk;
        const lines = fullChunk.split("\n");

        // 마지막 라인이 불완전할 수 있음 (줄바꿈으로 끝나지 않은 경우)
        if (!fullChunk.endsWith("\n") && lines.length > 0) {
          lineBuffer = lines.pop() || "";  // 마지막 불완전한 라인 저장
        } else {
          lineBuffer = "";
        }

        for (const line of lines) {
          // Phase 50: 이벤트 타입 저장
          if (line.startsWith("event: ")) {
            currentEventType = line.slice(7).trim();
            console.log("[SSE] event type:", currentEventType);
            continue;
          }

          if (line.startsWith("data: ")) {
            let data = line.slice(6);
            if (data === "[DONE]") continue;

            // Phase 51.3: 버퍼에 저장된 불완전한 JSON과 합치기
            if (pendingJsonBuffer) {
              data = pendingJsonBuffer + data;
              pendingJsonBuffer = "";
            }

            try {
              // JSON 파싱 시도
              if (data.startsWith("{")) {
                const parsed = JSON.parse(data);

                // Phase 50: SSE 이벤트 타입 기반 라우팅 (개선)
                console.log("[SSE] event:", currentEventType, "data:", JSON.stringify(parsed).substring(0, 150));

                // Phase 50: 이벤트 타입 명시적 라우팅 (우선 처리)
                if (currentEventType === "sql_complete") {
                  console.log("[SSE] sql_complete (explicit):", parsed.row_count, "rows");
                  const sql_result: SQLResult = {
                    generated_sql: parsed.generated_sql || "",
                    columns: parsed.columns || [],
                    row_count: parsed.row_count || 0,
                    rows: parsed.rows || [],
                    execution_time_ms: parsed.execution_time_ms || 0,
                  };
                  currentMetadata.sql_result = sql_result;
                  setState((prev) => ({
                    ...prev,
                    workflow: { ...prev.workflow, sql_result },
                  }));
                  currentEventType = "";  // 리셋
                  continue;
                }

                if (currentEventType === "rag_complete") {
                  console.log("[SSE] rag_complete (explicit):", parsed.result_count, "results");
                  const rag_result: RAGResult = {
                    search_strategy: parsed.search_strategy || "",
                    result_count: parsed.result_count || 0,
                    top_results: parsed.top_results || [],
                  };
                  currentMetadata.rag_result = rag_result;
                  setState((prev) => ({
                    ...prev,
                    workflow: { ...prev.workflow, rag_result },
                  }));
                  currentEventType = "";  // 리셋
                  continue;
                }

                if (currentEventType === "multi_sql_complete") {
                  console.log("[SSE] multi_sql_complete (explicit):", Object.keys(parsed.multi_sql_results || {}));
                  const multi_sql_results: MultiSQLResults = parsed.multi_sql_results || {};
                  currentMetadata.multi_sql_results = multi_sql_results;
                  setState((prev) => ({
                    ...prev,
                    workflow: { ...prev.workflow, multi_sql_results },
                  }));
                  currentEventType = "";  // 리셋
                  continue;
                }

                if (currentEventType === "sub_query_complete") {
                  console.log("[SSE] sub_query_complete (explicit):", parsed.index, parsed.subtype);

                  // Phase 93: 하위 쿼리 상태를 "completed"로 업데이트
                  const subQueryIndex = parsed.index;
                  setState((prev) => {
                    if (!prev.workflow.subqueries) return prev;
                    const updatedSubqueries = {
                      ...prev.workflow.subqueries,
                      sub_queries: prev.workflow.subqueries.sub_queries.map((sq, idx) =>
                        idx === subQueryIndex ? { ...sq, status: "completed" as const } : sq
                      ),
                    };
                    currentMetadata.subqueries = updatedSubqueries;
                    return {
                      ...prev,
                      workflow: { ...prev.workflow, subqueries: updatedSubqueries },
                    };
                  });

                  // compound 쿼리 하위 결과 - sql_result와 rag_result 모두 처리
                  if (parsed.sql_result) {
                    const sql_result: SQLResult = {
                      generated_sql: parsed.sql_result.generated_sql || "",
                      columns: parsed.sql_result.columns || [],
                      row_count: parsed.sql_result.row_count || 0,
                      rows: parsed.sql_result.rows || [],
                      execution_time_ms: 0,
                    };
                    currentMetadata.sql_result = sql_result;
                    setState((prev) => ({
                      ...prev,
                      workflow: { ...prev.workflow, sql_result },
                    }));
                  }
                  if (parsed.rag_result) {
                    const rag_result: RAGResult = {
                      search_strategy: "",
                      result_count: parsed.rag_result.result_count || 0,
                      top_results: parsed.rag_result.results || [],
                    };
                    currentMetadata.rag_result = rag_result;
                    setState((prev) => ({
                      ...prev,
                      workflow: { ...prev.workflow, rag_result },
                    }));
                  }
                  currentEventType = "";  // 리셋
                  continue;
                }

                // 이벤트 타입 리셋 (다음 이벤트를 위해)
                currentEventType = "";

                // 기존 필드 기반 폴백 처리

                // status 이벤트
                if (parsed.status) {
                  console.log("[SSE] status update:", parsed.status);
                  setState((prev) => ({
                    ...prev,
                    workflow: {
                      ...prev.workflow,
                      status: parsed.status as WorkflowStatus,
                    },
                  }));

                  // 진행 상태 텍스트는 사이드 패널에서 표시하므로 여기서는 건너뜀
                  // (accumulatedText를 덮어쓰지 않음)
                }

                // analysis_complete 이벤트
                if (parsed.query_type && parsed.entity_types !== undefined) {
                  const analysis: AnalysisResult = {
                    query_type: parsed.query_type,
                    query_intent: parsed.query_intent || "",
                    entity_types: parsed.entity_types || [],
                    keywords: parsed.keywords || [],
                    related_tables: parsed.related_tables || [],
                    is_compound: parsed.is_compound || false,
                  };
                  currentMetadata.analysis = analysis;
                  setState((prev) => ({
                    ...prev,
                    workflow: { ...prev.workflow, analysis },
                  }));
                }

                // subquery_info 이벤트
                if (parsed.sub_queries) {
                  const subqueries: SubQueryData = {
                    sub_queries: parsed.sub_queries,
                    merge_strategy: parsed.merge_strategy || "parallel",
                    complexity_reason: parsed.complexity_reason || "",
                  };
                  currentMetadata.subqueries = subqueries;
                  setState((prev) => ({
                    ...prev,
                    workflow: { ...prev.workflow, subqueries },
                  }));
                }

                // subquery_progress 이벤트 (하위 쿼리 상태 업데이트)
                if (parsed.index !== undefined && parsed.status && !parsed.sub_queries) {
                  setState((prev) => {
                    if (!prev.workflow.subqueries) return prev;
                    const updatedSubqueries = {
                      ...prev.workflow.subqueries,
                      sub_queries: prev.workflow.subqueries.sub_queries.map((sq, idx) =>
                        idx === parsed.index ? { ...sq, status: parsed.status } : sq
                      ),
                    };
                    currentMetadata.subqueries = updatedSubqueries;
                    return {
                      ...prev,
                      workflow: { ...prev.workflow, subqueries: updatedSubqueries },
                    };
                  });
                }

                // sql_complete 이벤트 (단일 결과)
                if (parsed.generated_sql !== undefined && parsed.columns !== undefined) {
                  console.log("[SSE] sql_complete:", parsed.row_count, "rows");
                  const sql_result: SQLResult = {
                    generated_sql: parsed.generated_sql,
                    columns: parsed.columns,
                    row_count: parsed.row_count || 0,
                    rows: parsed.rows || [],
                    execution_time_ms: parsed.execution_time_ms || 0,
                  };
                  currentMetadata.sql_result = sql_result;
                  setState((prev) => ({
                    ...prev,
                    workflow: { ...prev.workflow, sql_result },
                  }));
                  continue;  // Phase 51.1: 다른 핸들러로 이동 방지
                }

                // Phase 19: multi_sql_complete 이벤트 (다중 엔티티 결과)
                if (parsed.multi_sql_results !== undefined) {
                  console.log("[SSE] multi_sql_complete:", Object.keys(parsed.multi_sql_results));
                  const multi_sql_results: MultiSQLResults = parsed.multi_sql_results;
                  currentMetadata.multi_sql_results = multi_sql_results;
                  setState((prev) => ({
                    ...prev,
                    workflow: { ...prev.workflow, multi_sql_results },
                  }));
                  continue;  // Phase 51.1: 다른 핸들러로 이동 방지
                }
                // Phase 51: entity 키로 직접 감지하는 폴백 (이벤트 타입 손실 시)
                // 예: {"patent": {...}, "project": {...}} 형식
                if (
                  Object.keys(parsed).some(k => ['patent', 'project', 'equip', 'proposal', 'evalp', 'ancm'].includes(k)) &&
                  !parsed.status && !parsed.query_type && !parsed.elapsed_ms && !parsed.generated_sql
                ) {
                  console.log("[SSE] multi_sql_results detected from entity keys:", Object.keys(parsed));
                  const multi_sql_results: MultiSQLResults = parsed;
                  currentMetadata.multi_sql_results = multi_sql_results;
                  setState((prev) => ({
                    ...prev,
                    workflow: { ...prev.workflow, multi_sql_results },
                  }));
                  continue;  // Phase 51.1: 다른 핸들러로 이동 방지
                }

                // rag_complete 이벤트
                if (parsed.search_strategy !== undefined && parsed.top_results !== undefined) {
                  const rag_result: RAGResult = {
                    search_strategy: parsed.search_strategy,
                    result_count: parsed.result_count || 0,
                    top_results: parsed.top_results || [],
                  };
                  currentMetadata.rag_result = rag_result;
                  setState((prev) => ({
                    ...prev,
                    workflow: { ...prev.workflow, rag_result },
                  }));
                }

                // Phase 43: vector_complete 이벤트 (확장 키워드)
                if (parsed.expanded_keywords !== undefined && parsed.doc_count !== undefined) {
                  const expanded_keywords = parsed.expanded_keywords as string[];
                  setState((prev) => ({
                    ...prev,
                    workflow: { ...prev.workflow, expanded_keywords },
                  }));
                  // analysis에도 연결 (QueryAnalysisCard에서 사용)
                  if (currentMetadata.analysis) {
                    currentMetadata.analysis.expanded_keywords = expanded_keywords;
                  }
                }

                // stage_timing 이벤트
                if (
                  parsed.analyzer_ms !== undefined ||
                  parsed.sql_node_ms !== undefined ||
                  parsed.rag_node_ms !== undefined
                ) {
                  currentMetadata.timing = parsed;
                  setState((prev) => ({
                    ...prev,
                    workflow: { ...prev.workflow, timing: parsed },
                  }));
                }

                // done 이벤트
                if (parsed.elapsed_ms !== undefined && parsed.sources !== undefined) {
                  currentMetadata.elapsed_ms = parsed.elapsed_ms;
                  currentMetadata.sources = parsed.sources;
                  if (parsed.timing) {
                    currentMetadata.timing = parsed.timing;
                  }
                  // Phase 102: confidence_score와 graph_data 저장
                  if (parsed.confidence_score !== undefined) {
                    currentMetadata.confidence_score = parsed.confidence_score;
                  }
                  if (parsed.graph_data) {
                    currentMetadata.graph_data = parsed.graph_data;
                  }
                  setState((prev) => ({
                    ...prev,
                    workflow: {
                      ...prev.workflow,
                      status: "done",
                      elapsed_ms: parsed.elapsed_ms,
                      timing: parsed.timing || prev.workflow.timing,
                    },
                  }));
                }
              } else {
                // 텍스트 데이터 (응답) - 줄바꿈 복원 후 표시
                const unescapedData = data.replace(/\\n/g, "\n");

                // Phase 51: JSON 데이터가 텍스트로 잘못 처리되는 것 방지
                // SSE 청크 분리로 event 타입이 손실된 경우 JSON이 여기로 올 수 있음
                const trimmedData = unescapedData.trim();
                if (trimmedData.startsWith("{") && trimmedData.endsWith("}")) {
                  console.warn("[SSE] JSON data in text block, skipping:", trimmedData.substring(0, 100));
                  continue;  // 텍스트로 표시하지 않고 건너뜀
                }

                accumulatedText = unescapedData;
                updateAssistantMessage(accumulatedText, currentMetadata);
              }
            } catch {
              // JSON 파싱 실패 시 처리
              if (data && data !== "[DONE]") {
                const trimmedData = data.trim();

                // Phase 51.3: 불완전한 JSON은 버퍼에 저장하고 다음 청크와 합침
                if (trimmedData.startsWith("{") || trimmedData.startsWith("[")) {
                  // 이벤트 타입이 설정된 상태에서 JSON 파싱 실패 = 불완전한 JSON
                  if (currentEventType) {
                    console.log("[SSE] Buffering incomplete JSON for event:", currentEventType, "length:", trimmedData.length);
                    pendingJsonBuffer = data;  // 다음 청크와 합치기 위해 저장
                  } else {
                    console.warn("[SSE] Incomplete JSON without event type, skipping:", trimmedData.substring(0, 80));
                  }
                  continue;
                }

                // 순수 텍스트 데이터
                const unescapedData = data.replace(/\\n/g, "\n");
                accumulatedText = unescapedData;
                updateAssistantMessage(accumulatedText, currentMetadata);
              }
            }
          }
        }
      }

      // 최종 메타데이터 업데이트
      updateAssistantMessage(accumulatedText, currentMetadata);
    } catch (error) {
      console.error("Streaming error:", error);
      setState((prev) => {
        const newMessages = [...prev.messages];
        const lastIdx = newMessages.length - 1;
        if (lastIdx >= 0 && newMessages[lastIdx].role === "assistant") {
          newMessages[lastIdx] = {
            ...newMessages[lastIdx],
            content: `오류가 발생했습니다: ${
              error instanceof Error ? error.message : "알 수 없는 오류"
            }`,
          };
        }
        return {
          ...prev,
          messages: newMessages,
          workflow: { ...prev.workflow, status: "error" },
        };
      });
    } finally {
      setState((prev) => ({ ...prev, isLoading: false }));
    }

    function updateAssistantMessage(
      text: string,
      metadata: ExtendedMessage["metadata"]
    ) {
      setState((prev) => {
        const newMessages = [...prev.messages];
        const lastIdx = newMessages.length - 1;
        if (lastIdx >= 0 && newMessages[lastIdx].role === "assistant") {
          newMessages[lastIdx] = {
            ...newMessages[lastIdx],
            content: text,
            metadata: { ...metadata },
          };
        }
        return { ...prev, messages: newMessages };
      });
    }
  }, [searchMode, level]);

  const clearMessages = useCallback(() => {
    setState({
      messages: [],
      isLoading: false,
      workflow: initialWorkflowState,
    });
  }, []);

  return { ...state, sendMessage, clearMessages };
}

// 메시지 컴포넌트 (Phase 53: 마크다운 표 렌더링 지원)
function MessageContent({ content }: { content: string }) {
  return (
    <div className="prose prose-sm max-w-none prose-table:text-sm prose-th:bg-gray-100 prose-th:px-3 prose-th:py-2 prose-td:px-3 prose-td:py-2 prose-table:border-collapse">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // 표 스타일 커스터마이징
          table: ({ children }) => (
            <table className="min-w-full border border-gray-300 text-sm">
              {children}
            </table>
          ),
          thead: ({ children }) => (
            <thead className="bg-gray-100">{children}</thead>
          ),
          th: ({ children }) => (
            <th className="border border-gray-300 px-3 py-2 text-left font-semibold">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-gray-300 px-3 py-2">{children}</td>
          ),
          // 볼드 텍스트
          strong: ({ children }) => (
            <strong className="font-bold">{children}</strong>
          ),
          // 헤딩
          h3: ({ children }) => (
            <h3 className="text-base font-bold mt-4 mb-2">{children}</h3>
          ),
          h4: ({ children }) => (
            <h4 className="text-sm font-bold mt-3 mb-1">{children}</h4>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

// 사이드 패널 컴포넌트
function SidePanel({ workflow }: { workflow: WorkflowState }) {
  const hasContent =
    workflow.status !== "idle" ||
    workflow.analysis ||
    workflow.subqueries ||
    workflow.sql_result ||
    workflow.multi_sql_results ||
    workflow.rag_result;

  if (!hasContent) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400 text-sm">
        <div className="text-center">
          <p className="mb-2">📊</p>
          <p>질문을 입력하면</p>
          <p>워크플로우 상태가 표시됩니다</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      <WorkflowProgress status={workflow.status} timing={workflow.timing || undefined} />

      {workflow.analysis && (
        <QueryAnalysisCard
          analysis={workflow.analysis}
          expandedKeywords={workflow.expanded_keywords}
        />
      )}

      {workflow.subqueries && <SubQueryTree data={workflow.subqueries} />}

      {(workflow.sql_result || workflow.multi_sql_results) && (
        <SQLResultTable
          result={workflow.sql_result}
          multiResults={workflow.multi_sql_results}
        />
      )}

      {workflow.rag_result && <RAGResultCards result={workflow.rag_result} />}
    </div>
  );
}

// 메인 채팅 UI 컴포넌트
interface MyAssistantProps {
  searchMode: SearchMode;
  level: UserLevel;  // Phase 103: 수준 추가
}

export function MyAssistant({ searchMode, level }: MyAssistantProps) {
  const { messages, isLoading, workflow, sendMessage, clearMessages } =
    useStreamingChat(searchMode, level);
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [showSidePanel, setShowSidePanel] = useState(true);

  // 자동 스크롤
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() && !isLoading) {
      sendMessage(input.trim());
      setInput("");
    }
  };

  return (
    <div className="flex h-full">
      {/* 채팅 영역 */}
      <div className={`flex flex-col ${showSidePanel ? "flex-1" : "w-full"}`}>
        {/* 메시지 목록 */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="text-center text-gray-500 py-8">
              <p className="text-lg mb-2">안녕하세요! AX Agent입니다.</p>
              <p className="text-sm">
                {searchMode === "ax"
                  ? "특허 데이터에 대해 물어보세요."
                  : "연구 데이터(특허, 연구과제, 장비, 공고)에 대해 물어보세요."}
              </p>
              <div className="mt-4 flex flex-wrap gap-2 justify-center">
                {(searchMode === "ax"
                  ? [
                      "수소연료전지 특허 알려줘",
                      "배터리 기술 특허 동향",
                      "인공지능 특허 5개",
                    ]
                  : [
                      "특허 5개 알려줘",
                      "인공지능 연구 동향",
                      "AI 특허와 관련 연구과제",
                    ]
                ).map((suggestion) => (
                  <button
                    key={suggestion}
                    onClick={() => sendMessage(suggestion)}
                    className="px-3 py-1 text-sm bg-blue-50 text-blue-600 rounded-full hover:bg-blue-100 transition"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((message, index) => (
            <div
              key={index}
              className={`flex flex-col ${
                message.role === "user" ? "items-end" : "items-start"
              }`}
            >
              <div
                className={`max-w-[80%] rounded-lg p-3 ${
                  message.role === "user"
                    ? "bg-blue-600 text-white"
                    : "bg-gray-100 text-gray-800"
                }`}
              >
                {message.role === "assistant" ? (
                  <MessageContent content={message.content} />
                ) : (
                  <p>{message.content}</p>
                )}
              </div>
              {/* 시각화 패널 - assistant 메시지에만 표시 */}
              {message.role === "assistant" && (message.metadata?.sources?.length || message.metadata?.confidence_score !== undefined || message.metadata?.graph_data) && (
                <div className="max-w-[80%] mt-1">
                  <MessageVisualizationPanel
                    sources={message.metadata.sources || []}
                    timing={message.metadata.timing}
                    elapsedMs={message.metadata.elapsed_ms}
                    confidenceScore={message.metadata.confidence_score}
                    graphData={message.metadata.graph_data}
                  />
                </div>
              )}
            </div>
          ))}

          {isLoading && messages[messages.length - 1]?.content === "" && (
            <div className="flex justify-start">
              <div className="bg-gray-100 rounded-lg p-3">
                <div className="flex items-center space-x-2">
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-100"></div>
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-200"></div>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* 입력 폼 */}
        <div className="border-t p-4 bg-white">
          <form onSubmit={handleSubmit} className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="메시지를 입력하세요..."
              disabled={isLoading}
              className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
            />
            <button
              type="submit"
              disabled={isLoading || !input.trim()}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition"
            >
              {isLoading ? "전송 중..." : "전송"}
            </button>
            {messages.length > 0 && (
              <button
                type="button"
                onClick={clearMessages}
                className="px-4 py-2 text-gray-600 hover:text-gray-800 transition"
              >
                초기화
              </button>
            )}
          </form>
        </div>
      </div>

      {/* 사이드 패널 토글 */}
      <button
        onClick={() => setShowSidePanel(!showSidePanel)}
        className="absolute top-20 right-4 z-10 p-2 bg-white rounded-lg shadow border border-gray-200 hover:bg-gray-50 transition"
        title={showSidePanel ? "패널 숨기기" : "패널 보기"}
      >
        {showSidePanel ? "◀" : "▶"}
      </button>

      {/* 사이드 패널 */}
      {showSidePanel && (
        <div className="w-80 border-l border-gray-200 bg-gray-50">
          <SidePanel workflow={workflow} />
        </div>
      )}
    </div>
  );
}
