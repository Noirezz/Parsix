/**
 * Centralized API HTTP client with timeout, error normalization, and query serialization.
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public message: string,
    public details?: unknown
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export interface RequestOptions extends RequestInit {
  timeoutMs?: number;
  params?: Record<string, string | number | boolean | null | undefined>;
}

const DEFAULT_BASE_URL = 'http://localhost:8000';

export function getBaseUrl(): string {
  if (typeof window !== 'undefined' && (window as unknown as { __MADE_API_URL__?: string }).__MADE_API_URL__) {
    return (window as unknown as { __MADE_API_URL__: string }).__MADE_API_URL__;
  }
  return import.meta.env.VITE_API_BASE_URL || DEFAULT_BASE_URL;
}

export function buildQueryString(params?: Record<string, string | number | boolean | null | undefined>): string {
  if (!params) return '';
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      searchParams.append(key, String(value));
    }
  }
  const str = searchParams.toString();
  return str ? `?${str}` : '';
}

export async function apiClient<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { timeoutMs = 8000, params, ...fetchOptions } = options;
  const baseUrl = getBaseUrl();
  const url = `${baseUrl}${path}${buildQueryString(params)}`;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        ...fetchOptions.headers,
      },
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      let errorDetail = `HTTP Error ${response.status}: ${response.statusText}`;
      try {
        const errorJson = await response.json();
        if (errorJson && typeof errorJson.detail === 'string') {
          errorDetail = errorJson.detail;
        }
      } catch {
        // use default statusText
      }
      throw new ApiError(response.status, errorDetail);
    }

    return (await response.json()) as T;
  } catch (err: unknown) {
    clearTimeout(timeoutId);
    if (err instanceof ApiError) {
      throw err;
    }
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(408, `Request timeout after ${timeoutMs}ms`);
    }
    const message = err instanceof Error ? err.message : 'Network error or backend unreachable';
    throw new ApiError(0, message);
  }
}
