export type AuthUser = {
  id: string
  username: string
  displayName: string
  isOwner: boolean
}

export type AuthSession = {
  user: AuthUser
  expiresAt: string
}

export class AuthApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number,
  ) {
    super(message)
  }
}

function cookieValue(name: string): string | null {
  const prefix = `${encodeURIComponent(name)}=`
  const item = document.cookie.split('; ').find((value) => value.startsWith(prefix))
  return item ? decodeURIComponent(item.slice(prefix.length)) : null
}

async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body) headers.set('Content-Type', 'application/json')
  if (init.method && !['GET', 'HEAD'].includes(init.method.toUpperCase())) {
    const csrf = cookieValue('trainlab_csrf')
    if (csrf) headers.set('X-CSRF-Token', csrf)
  }
  const response = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  const payload = (await response.json().catch(() => null)) as
    { code?: string; message?: string } | T | null
  if (!response.ok) {
    const error = payload as { code?: string; message?: string } | null
    throw new AuthApiError(
      error?.message ?? '服务暂时不可用',
      error?.code ?? 'request_failed',
      response.status,
    )
  }
  return payload as T
}

export function restoreSession(): Promise<AuthSession> {
  return apiRequest<AuthSession>('/api/v1/auth/session')
}

export function login(username: string, password: string): Promise<AuthSession> {
  return apiRequest<AuthSession>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export function logout(): Promise<{ status: string }> {
  return apiRequest<{ status: string }>('/api/v1/auth/logout', { method: 'POST' })
}
