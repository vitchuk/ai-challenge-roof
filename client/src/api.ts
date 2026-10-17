import type {
  ChatResponse,
  ChatSummary,
  CommandInfo,
  Message,
  PrDetail,
  PrList,
  RepoOverview,
  Settings,
  Status,
} from './types'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `HTTP ${response.status}`)
  }
  return (await response.json()) as T
}

export function getCommands(): Promise<{ commands: CommandInfo[] }> {
  return request('/api/commands')
}

export function getStatus(): Promise<Status> {
  return request('/api/status')
}

export function getSettings(): Promise<Settings> {
  return request('/api/settings')
}

export function patchSettings(payload: { top_k?: number; model?: string }): Promise<Settings> {
  return request('/api/settings', { method: 'PATCH', body: JSON.stringify(payload) })
}

export function rebuildIndex(): Promise<{ started: boolean; status: string }> {
  return request('/api/rag/rebuild', { method: 'POST' })
}

export function listChats(): Promise<{ chats: ChatSummary[] }> {
  return request('/api/chats')
}

export function createChat(): Promise<ChatSummary> {
  return request('/api/chats', { method: 'POST' })
}

export function deleteChat(chatId: string): Promise<{ ok: boolean }> {
  return request(`/api/chats/${chatId}`, { method: 'DELETE' })
}

export function getMessages(chatId: string): Promise<{ messages: Message[] }> {
  return request(`/api/chats/${chatId}/messages`)
}

export function sendMessage(chatId: string, message: string): Promise<ChatResponse> {
  return request('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ chat_id: chatId, message }),
  })
}

export function getRepo(refresh = false): Promise<RepoOverview> {
  const suffix = refresh ? '?refresh=1' : ''
  return request(`/api/repo${suffix}`)
}

export function getPrs(refresh = false): Promise<PrList> {
  const suffix = refresh ? '?refresh=1' : ''
  return request(`/api/prs${suffix}`)
}

export function getPr(number: number, refresh = false): Promise<PrDetail> {
  const suffix = refresh ? '?refresh=1' : ''
  return request(`/api/prs/${number}${suffix}`)
}

export function rerunPr(number: number): Promise<{ ok: boolean }> {
  return request(`/api/prs/${number}/rerun`, { method: 'POST' })
}
