/**
 * Thin fetch wrapper against the control-plane catalog read API
 * (architecture.md §8, FE2's `control-plane/api/catalog/`). No direct
 * storage access from this layer or anywhere in control-plane/web — every
 * read/write goes through this module.
 *
 * Base URL is configurable via VITE_API_BASE_URL (empty string = relative
 * paths, e.g. for a same-origin deployment or a dev-server proxy). Never
 * hardcode a host here.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    })
  } catch {
    throw new ApiError('Network request failed', 0)
  }

  if (!response.ok) {
    let detail = ''
    try {
      detail = await response.text()
    } catch {
      // ignore
    }
    throw new ApiError(detail || `Request failed with status ${response.status}`, response.status)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}
