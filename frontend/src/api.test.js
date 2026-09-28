import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, errorMessage, LONG_REQUEST_TIMEOUT_MS, OUTCOME_UNKNOWN_ERROR, REQUEST_TIMEOUT_MS, setAuthFailureHandler, setSessionToken, TIMEOUT_ERROR } from './api';

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

describe('api client error contract', () => {
  beforeEach(() => { setSessionToken(null); setAuthFailureHandler(null); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('surfaces the message of an object-shaped detail and keeps the structured detail', async () => {
    const detail = { message: 'This application is not ready to submit yet.', blockingRequirements: [{ requirementCode: 'IDENTITY' }] };
    vi.stubGlobal('fetch', mockFetchOnce(422, { detail }));
    const error = await api.submitApplication('APP-1').catch(e => e);
    expect(error.message).toBe('This application is not ready to submit yet.');
    expect(error.status).toBe(422);
    expect(error.detail).toEqual(detail);
  });

  it('never shows a raw validation array or "[object Object]"', () => {
    expect(errorMessage([{ loc: ['body', 'schemeId'], msg: 'Field required' }])).toBe('Some of the information provided is not valid.');
    expect(errorMessage({ reasons: ['Unsupported file type.'] })).toBe('Unsupported file type.');
    expect(errorMessage({ unexpected: true })).toBe('The service could not complete this request.');
  });

  it('falls back to a generic message when the response body is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 502, ok: false, json: () => Promise.reject(new SyntaxError('Unexpected token <')) }));
    await expect(api.services()).rejects.toThrow('Something went wrong on our side. Please try again later.');
  });

  it('never shows server-side error details for a 5xx response', async () => {
    vi.stubGlobal('fetch', mockFetchOnce(500, { detail: 'psycopg.OperationalError: connection refused' }));
    const error = await api.services().catch(e => e);
    expect(error.message).toBe('Something went wrong on our side. Please try again later.');
    expect(error.message).not.toMatch(/psycopg|refused/);
  });

  it('shows an Admin API\'s intentional operational 5xx message to staff, but still hides unsafe or citizen 5xx details', async () => {
    vi.stubGlobal('fetch', mockFetchOnce(503, { detail: 'Provider job replay is unavailable.' }));
    expect((await api.adminReplayJob('JOB-1').catch(e => e)).message).toBe('Provider job replay is unavailable.');

    vi.stubGlobal('fetch', mockFetchOnce(500, { detail: 'psycopg.OperationalError: password authentication failed' }));
    expect((await api.adminOverview().catch(e => e)).message).toBe('Something went wrong on our side. Please try again later.');

    vi.stubGlobal('fetch', mockFetchOnce(503, { detail: 'Provider job replay is unavailable.' }));
    expect((await api.services().catch(e => e)).message).toBe('Something went wrong on our side. Please try again later.');
  });

  it('turns a network failure into a friendly message instead of the raw browser error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const error = await api.services().catch(e => e);
    expect(error.message).toBe('We could not reach the service. Please check your connection and try again.');
    expect(error.status).toBe(0);
  });
});

describe('api client timeouts', () => {
  beforeEach(() => { setSessionToken(null); setAuthFailureHandler(null); vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  // A fetch that never answers; it rejects only when its signal is aborted.
  function hangingFetch() {
    return vi.fn((url, options) => new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
    }));
  }

  it('gives an ordinary read the normal 30 s timeout', async () => {
    vi.stubGlobal('fetch', hangingFetch());
    const pending = api.services().catch(e => e);
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);
    const error = await pending;
    expect(error.message).toBe(TIMEOUT_ERROR);
    expect(error.timedOut).toBe(true);
    expect(error.outcomeUnknown).toBe(false);
  });

  it('lets Auto-Fill and uploads run past 30 s, up to the long timeout', async () => {
    for (const call of [() => api.autoFillRequirement('APP-1', 'INCOME_PROOF'), () => api.uploadRequirement('APP-1', 'INCOME_PROOF', { title: 't', contentType: 'image/png', content: 'x' })]) {
      vi.stubGlobal('fetch', hangingFetch());
      let settled = false;
      const pending = call().catch(e => e).finally(() => { settled = true; });
      await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 1000);
      expect(settled).toBe(false);
      await vi.advanceTimersByTimeAsync(LONG_REQUEST_TIMEOUT_MS - REQUEST_TIMEOUT_MS);
      const error = await pending;
      // A timed-out change is never reported as a definite failure.
      expect(error.message).toBe(OUTCOME_UNKNOWN_ERROR);
      expect(error.outcomeUnknown).toBe(true);
    }
  });

  it('treats a proxy gateway timeout on a change as "may still be completing"', async () => {
    vi.useRealTimers();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 504, ok: false, json: () => Promise.reject(new SyntaxError('html')) }));
    const error = await api.autoFillRequirement('APP-1', 'INCOME_PROOF').catch(e => e);
    expect(error.message).toBe(OUTCOME_UNKNOWN_ERROR);
    expect(error.outcomeUnknown).toBe(true);
  });
});
