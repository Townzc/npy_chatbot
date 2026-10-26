import type { components } from './generated-api';

// Domain contracts come from FastAPI's OpenAPI document. Dictionary metadata is
// narrowed for display only; no chat content is interpreted as HTML or commands.
export interface Persona { id: string; name: string }
export interface Relationship { id: string; persona_id: string; name: string }
export type Binding = Required<components['schemas']['Binding']>;
export type ModeStatus = components['schemas']['ModeStatus'];
export type ModeCommand = components['schemas']['ModeCommand'];
export type SandboxInput = components['schemas']['SandboxInput'];
export type MemoryInput = components['schemas']['MemoryInput'];
export type NamedInput = components['schemas']['NamedInput'];
export type RelationshipInput = components['schemas']['RelationshipInput'];
export type ScopeInput = components['schemas']['Scope'];
export type WorkspaceState = Omit<components['schemas']['AppState'], 'personas' | 'relationships' | 'bindings' | 'provider' | 'training'> & {
  personas: Persona[];
  relationships: Relationship[];
  bindings: Binding[];
  provider: { name: string; remote: boolean };
  training: { available: boolean; detail: string };
};
export interface Memory {
  id: string;
  text?: string;
  confirmed?: boolean;
  source_message_ids?: string[];
  payload?: { text?: string; confirmed?: boolean; source_message_ids?: string[] };
}
export interface SandboxReply {
  text: string; synthetic: boolean; model: string;
  memories: Memory[]; status: ModeStatus;
}

export class APIError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function errorMessage(data: unknown, fallback: string): string {
  if (!data || typeof data !== 'object') return fallback;
  const obj = data as Record<string, unknown>;
  if (typeof obj.detail === 'string') return obj.detail;
  if (typeof obj.message === 'string') return obj.message;
  if (Array.isArray(obj.detail)) return obj.detail.map((d: { msg?: string }) => d.msg ?? '输入无效').join('；');
  return fallback;
}

export async function request<T>(token: string, path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set('Authorization', `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(`/api/v1${path}`, { ...options, headers, credentials: 'same-origin' });
  const data: unknown = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw new APIError(response.status, errorMessage(data, `请求未完成（${response.status}）`));
  return data as T;
}

export function post<T>(token: string, path: string, data: unknown): Promise<T> {
  return request<T>(token, path, { method: 'POST', body: JSON.stringify(data) });
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : '操作未完成，请稍后重试。';
}
