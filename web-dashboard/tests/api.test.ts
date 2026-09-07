import { describe, it, expect, vi, beforeEach } from 'vitest';
import { buildQueryString, ApiError } from '../src/api/client';
import { api } from '../src/api/endpoints';

describe('API Client', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('builds query string correctly', () => {
    expect(buildQueryString()).toBe('');
    expect(buildQueryString({ limit: 50, offset: 0, status: 'ANOMALY' })).toBe('?limit=50&offset=0&status=ANOMALY');
    expect(buildQueryString({ limit: 50, empty: '', nil: null, undef: undefined })).toBe('?limit=50');
  });

  it('handles successful API responses', async () => {
    const mockData = { status: 'ok', service: 'made-api' };
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockData,
    });

    const res = await api.getHealth();
    expect(res).toEqual(mockData);
  });

  it('handles HTTP error responses and normalizes ApiError', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: async () => ({ detail: "Event with ID '123' not found" }),
    });

    await expect(api.getEvent('123')).rejects.toThrow(ApiError);
    await expect(api.getEvent('123')).rejects.toMatchObject({
      status: 404,
      message: "Event with ID '123' not found",
    });
  });
});
