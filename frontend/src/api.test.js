import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, setAuthFailureHandler, setSessionToken } from './api';

function mockFetchOnce(status, body) {
  return vi.fn().mockResolvedValue({ status, ok: status >= 200 && status < 300, json: () => Promise.resolve(body) });
}

describe('api client auth behaviour (requirement 7 -- unaffected by Phase 6A, verified unchanged)', () => {
  beforeEach(() => { setSessionToken(null); setAuthFailureHandler(null); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('does not attach an Authorization header before login', async () => {
    const fetchMock = mockFetchOnce(200, { services: [] });
    vi.stubGlobal('fetch', fetchMock);
    await api.services();
    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers.Authorization).toBeUndefined();
  });

  it('attaches a bearer token once a session token is set', async () => {
    setSessionToken('test-token-123');
    const fetchMock = mockFetchOnce(200, { services: [] });
    vi.stubGlobal('fetch', fetchMock);
    await api.services();
    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers.Authorization).toBe('Bearer test-token-123');
  });

  it('clears the session and invokes the unauthorized handler on a 401 response, and rejects the call', async () => {
    setSessionToken('stale-token');
    const onUnauthorized = vi.fn();
    setAuthFailureHandler(onUnauthorized);
    vi.stubGlobal('fetch', mockFetchOnce(401, { detail: 'Not authenticated' }));

    await expect(api.services()).rejects.toThrow('Not authenticated');
    expect(onUnauthorized).toHaveBeenCalledTimes(1);

    // A subsequent call no longer carries the (now-cleared) stale token.
    const fetchMock = mockFetchOnce(200, { services: [] });
    vi.stubGlobal('fetch', fetchMock);
    await api.services();
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });
});
