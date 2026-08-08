// Repository types
export interface Repo {
  id: string;
  name: string;
  path: string;
  gitUrl?: string;
  status: 'indexing' | 'indexed' | 'completed' | 'error';
  errorMessage?: string;
  totalFiles: number;
  indexedFiles: number;
  fileCount?: number;
  symbolCount?: number;
  createdAt: string;
  lastIndexedAt: string;
}

// Search types
export interface ScoreBreakdown {
  vector?: number;
  symbol?: number;
  bm25?: number;
  graph?: number;
  final?: number;
  [key: string]: number | undefined;
}

export interface SearchResult {
  repoId: string;
  repoName: string;
  filePath: string;
  lineNumber: number;
  code: string;
  language: string;
  score: number;
  scoreBreakdown: ScoreBreakdown;
}

// Settings types
export interface Settings {
  embeddingProvider: 'openai' | 'local';
  theme: 'light' | 'dark';
}

// Stats types
export interface Stats {
  totalRepos: number;
  totalFiles: number;
  recentSearches: string[];
}

// API response types
export interface ApiResponse<T> {
  data: T;
  error?: string;
}

// Benchmark types
export interface BenchmarkRun {
  id: string;
  query: string;
  repoId?: string;
  mode: 'with_codepop' | 'without_codepop';
  latencyMs: number;
  resultsCount: number;
  relevantResultsCount: number;
  tokenConsumed: number;
  accuracyScore: number;
  createdAt: string;
}

export interface BenchmarkSummary {
  totalRuns: number;
  avgLatencyMs: number;
  avgTokenConsumed: number;
  avgAccuracyScore: number;
  latencyTrend: { timestamp: string; latencyMs: number }[];
  savingsVsBaseline: Record<string, number>;
}

export interface SearchHistoryStats {
  totalQueries: number;
  avgLatencyMs: number;
  totalInputTokens: number;
  totalOutputTokens: number;
  estimatedTokensSaved: number;
}

export interface SearchHistoryDailyStats {
  date: string;
  totalQueries: number;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalResultsCount: number;
}

export interface SearchHistoryRecentItem {
  id: string;
  query: string;
  repoId?: string;
  repoName?: string;
  mode: string;
  resultsCount: number;
  latencyMs: number;
  inputTokens: number;
  outputTokens: number;
  createdAt: string;
}

export interface LLMCostBreakdown {
  input_tokens: number;
  output_tokens: number;
  call_count: number;
  cost: number;
}

export interface LLMCostEstimate {
  period_minutes?: number;
  period_days?: number;
  repo_id: string | null;
  total_cost: number;
  total_input_tokens: number;
  total_output_tokens: number;
  provider_breakdown: Record<string, LLMCostBreakdown>;
  operation_breakdown: Record<string, LLMCostBreakdown>;
}

export interface LLMUsageSummary {
  period_minutes?: number;
  period_days?: number;
  total_calls: number;
  success_calls: number;
  error_calls: number;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
}

export interface LLMDailyUsage {
  date: string;
  call_count: number;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  cost: number;
}

// Form types
export interface AddRepoForm {
  name?: string;
  path?: string;
  gitUrl?: string;
}

// CodeContext types
export interface SymbolEntry {
  id: string;
  name: string;
  type: string;
  file_path: string;
  line: number;
  relevance_score: number;
}

export interface CallChain {
  root: SymbolEntry;
  upstream: SymbolEntry[];
  downstream: SymbolEntry[];
  depth: number;
}

export interface FileSummary {
  path: string;
  role: string;
  relevance_score: number;
  key_symbols: string[];
}

export interface CodeContext {
  query: string;
  query_intent: string;
  matched_concepts: string[];
  entry_points: SymbolEntry[];
  call_chain: CallChain | null;
  flow_summary: string | null;
  related_files: FileSummary[];
  code_snippets: SearchResult[];
  total_files: number;
  total_symbols: number;
  search_latency_ms: number;
  degraded: boolean;
  degradation_reason?: string;
  unavailable_sources: string[];
}

export interface CodeContextResponse {
  context: CodeContext;
  success: boolean;
  error?: string;
}

// Debug search (retrieval testing center) types
export interface DebugPathOverrides {
  enabled?: string[];
  top_k?: Record<string, number>;
}

export interface DebugSearchHit {
  id: string;
  file_path: string;
  line: number;
  language: string;
  content: string;
  score: number;
  symbol_name?: string | null;
  sources: string[];
}

export interface DebugPathSnapshot {
  name: string;
  enabled: boolean;
  top_k: number;
  latency_ms: number;
  hit_count: number;
  hits: DebugSearchHit[];
}

export interface DebugFusionHit extends DebugSearchHit {
  rrf_score: number;
  vector_score: number;
  symbol_score: number;
  bm25_score: number;
  sparse_score: number;
  graph_score: number;
}

export interface DebugFusionSnapshot {
  rrf_k: number;
  hit_count: number;
  hits: DebugFusionHit[];
}

export interface DebugRerankStage {
  input_count: number;
  output_count: number;
  output: SearchResult[];
}

export interface DebugRerankSnapshot {
  code_reranker: DebugRerankStage;
  m3_reranker: DebugRerankStage;
}

export interface DebugSearchResponse {
  query_analysis: {
    intent_type: string;
    is_chinese: boolean;
    concepts: string[];
    expanded_terms: string[];
  };
  paths: DebugPathSnapshot[];
  fusion: DebugFusionSnapshot;
  rerank: DebugRerankSnapshot;
  final_context: CodeContext;
  total_latency_ms: number;
}
