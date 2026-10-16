export interface ChatSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface Source {
  chunk_id: string
  file: string
  title: string
  score: number
  excerpt: string
}

export interface ToolCallEvent {
  name: string
  arguments: Record<string, unknown>
  is_error: boolean
  preview: string
}

export interface RepoTreeNode {
  name: string
  path: string
  type: 'dir' | 'file'
  children: RepoTreeNode[]
}

export interface RepoTree {
  tree: RepoTreeNode[]
  files_count: number
}

export interface BranchInfo {
  name: string
  label: string
  sha: string | null
  commits: number
  current: boolean
}

export interface BranchGraph {
  current_branch: string
  branches: BranchInfo[]
  mermaid: string
}

export interface MessageExtra {
  repo_tree: RepoTree | null
  branch_graph: BranchGraph | null
}

export interface RepoOverview {
  current_branch: string
  branches: BranchInfo[]
  mermaid: string
  tree: RepoTreeNode[]
  files_count: number
}

export interface RetrieveDebug {
  strategy: string
  original_query: string
  rewritten_query: string
  rewrite_fallback: boolean
  top_k: number
  retrieved: number
}

export interface Message {
  id: number
  chat_id: string
  role: 'user' | 'assistant'
  content: string
  elapsed_ms: number | null
  sources: Source[]
  debug: RetrieveDebug | null
  tools: ToolCallEvent[]
  extra: MessageExtra | null
  created_at: string
}

export interface ChatResponse {
  reply: string
  elapsed_ms: number
  sources: Source[]
  debug: RetrieveDebug | null
  tools: ToolCallEvent[]
  extra: MessageExtra | null
  message_id: number
}

export interface CommandInfo {
  name: string
  description: string
  usage: string
}

export interface RagStatus {
  strategy: string
  exists: boolean
  build_status: string
  error: string | null
  chunks: number
  files: number
  built_at: string | null
  embedding_model: string | null
  dim: number | null
}

export interface OllamaStatus {
  connected: boolean
  base_url: string
  model: string
  model_present: boolean
  models?: string[]
  error?: string
}

export interface McpStatus {
  name: string
  connected: boolean
  error: string | null
  tools_count: number
  tools: string[]
  command?: string
}

export interface Status {
  rag: RagStatus
  ollama: OllamaStatus
  deepseek: { configured: boolean; model: string }
  mcp: McpStatus
  top_k: number
  ui: { top_k_min: number; top_k_max: number }
  github: { owner: string; repo: string; branch: string }
}

export interface RagParams {
  strategy: string
  embedding_model: string
  min_tokens: number
  max_tokens: number
  overlap_tokens: number
  chars_per_token: number
  chat_top_k: number
}

export interface Settings {
  top_k: number
  model: string
  allowed_models: string[]
  ui: { top_k_min: number; top_k_max: number }
  rag_params: RagParams
}
