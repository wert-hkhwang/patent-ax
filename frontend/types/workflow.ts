/**
 * 워크플로우 시각화 타입 정의
 */

// 쿼리 타입
export type QueryType = "sql" | "rag" | "hybrid" | "simple";

// 워크플로우 상태
export type WorkflowStatus =
  | "idle"
  | "analyzing"
  | "analyzed"
  | "vector_enhanced"
  | "executing_sql"
  | "searching"
  | "merging"
  | "generating"
  | "done"
  | "error";

// 분석 결과
export interface AnalysisResult {
  query_type: QueryType;
  query_intent: string;
  entity_types: string[];
  keywords: string[];              // LLM 추출 키워드
  expanded_keywords?: string[];    // 벡터 확장 키워드 (Phase 43)
  related_tables: string[];
  is_compound: boolean;
}

// 하위 질의 정보
export interface SubQueryInfo {
  index: number;
  query: string;
  type: QueryType;
  entity_types: string[];
  status: "pending" | "executing" | "completed" | "error";
}

// 복합 질의 정보
export interface SubQueryData {
  sub_queries: SubQueryInfo[];
  merge_strategy: "parallel" | "sequential";
  complexity_reason: string;
}

// SQL 실행 결과
export interface SQLResult {
  generated_sql: string;
  columns: string[];
  row_count: number;
  rows: any[][];
  execution_time_ms: number;
  entity_type?: string;  // Phase 19: 엔티티 타입 (다중 결과용)
}

// Phase 19: 다중 엔티티 SQL 결과
export interface MultiSQLResults {
  [entity_type: string]: SQLResult;
}

// RAG 검색 결과 항목 메타데이터
export interface RAGResultMetadata {
  community?: number;
  pagerank?: number;
  connections?: {
    ipc?: number;
    applicant?: number;
    org?: number;
    related?: number;
  };
  content?: string;
}

// RAG 검색 결과 항목
export interface RAGResultItem {
  node_id: string;
  name: string;
  entity_type: string;
  score: number;
  metadata?: RAGResultMetadata;  // Phase 99.3: 메타데이터 추가
}

// RAG 검색 결과
export interface RAGResult {
  search_strategy: string;
  result_count: number;
  top_results: RAGResultItem[];
}

// 단계별 타이밍
export interface StageTiming {
  analyzer_ms?: number;
  sql_node_ms?: number;
  rag_node_ms?: number;
  merger_ms?: number;
  generator_ms?: number;
  [key: string]: number | undefined;
}

// 소스 정보
export interface Source {
  type: "sql" | "rag" | "graph" | string;  // Phase 99.3: graph 및 동적 타입 지원
  sql?: string;
  tables?: string[];
  row_count?: number;
  count?: number;  // Phase 99.3: 검색 결과 수
  node_id?: string;
  name?: string;
  entity_type?: string;
  score?: number;
  strategy?: string;  // Phase 99.3: RAG 전략
}

// Phase 102: 그래프 노드
export interface GraphNodeData {
  id: string;
  name: string;
  type: string;
  score: number;
  color?: string;
}

// Phase 102: 그래프 엣지
export interface GraphEdgeData {
  from_id: string;
  to_id: string;
  relation: string;
}

// Phase 102: 그래프 데이터
export interface GraphData {
  nodes: GraphNodeData[];
  edges: GraphEdgeData[];
}

// 메시지 메타데이터
export interface MessageMetadata {
  // 분석 결과
  analysis?: AnalysisResult;

  // 복합 질의
  subqueries?: SubQueryData;

  // 실행 결과
  sql_result?: SQLResult;
  multi_sql_results?: MultiSQLResults;  // Phase 19: 다중 엔티티 SQL 결과
  rag_result?: RAGResult;

  // 완료 정보
  sources?: Source[];
  timing?: StageTiming;
  elapsed_ms?: number;

  // Phase 102: 신뢰도 + 그래프 데이터
  confidence_score?: number;
  graph_data?: GraphData;

  // 상태
  status?: WorkflowStatus;
}

// 확장된 메시지
export interface ExtendedMessage {
  role: "user" | "assistant";
  content: string;
  metadata?: MessageMetadata;
}

// 워크플로우 컨텍스트 상태
export interface WorkflowContextState {
  status: WorkflowStatus;
  analysis?: AnalysisResult;
  subqueries?: SubQueryData;
  sql_result?: SQLResult;
  multi_sql_results?: MultiSQLResults;  // Phase 19: 다중 엔티티 SQL 결과
  rag_result?: RAGResult;
  timing?: StageTiming;
  elapsed_ms?: number;
}
