// Explicit VITE_API_BASE_URL wins. Otherwise the dev server talks to the
// local backend, and a production build uses the same origin it is served
// from (the bundled nginx config proxies /api to the backend).
const BASE = import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? 'http://127.0.0.1:8001/api' : '/api');
const GENERIC_ERROR = 'The service could not complete this request.';
let sessionToken = null;
let onUnauthorized = () => {};
export const setSessionToken = token => { sessionToken = token; };
export const setAuthFailureHandler = handler => { onUnauthorized = handler || (() => {}); };

// FastAPI error bodies carry `detail` as a string, an object with a
// `message`, or a validation-error array; a proxy error may not be JSON at
// all. Always surface a readable message and keep the structured detail.
export function errorMessage(detail, fallback = GENERIC_ERROR) {
  if (typeof detail === 'string' && detail) return detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail) && typeof detail.message === 'string') return detail.message;
  if (detail && Array.isArray(detail.reasons) && detail.reasons.every(reason => typeof reason === 'string') && detail.reasons.length) return detail.reasons.join(' ');
  if (Array.isArray(detail) && detail.length) return 'Some of the information provided is not valid.';
  return fallback;
}

export const NETWORK_ERROR = 'We could not reach the service. Please check your connection and try again.';
export const TIMEOUT_ERROR = 'The service is taking too long to respond. Please try again.';
// A change (Auto-Fill, upload, submit...) that timed out may still complete
// on the server, so never tell the person it failed.
export const OUTCOME_UNKNOWN_ERROR = 'This is taking longer than expected. Your request may still be completing — please check again in a moment before trying again.';
export const SERVER_ERROR = 'Something went wrong on our side. Please try again later.';
export const REQUEST_TIMEOUT_MS = 30000;
// Auto-Fill can try several providers in turn, and an upload can be a few
// MB on a slow connection: these get a longer, explicit timeout.
export const LONG_REQUEST_TIMEOUT_MS = 120000;
const GATEWAY_TIMEOUT_STATUSES = new Set([502, 504]);

// Admin/officer APIs intentionally return short operational messages on some
// 5xx responses (e.g. "Provider job replay is unavailable."). Staff see those;
// anything that looks like an internal error, query or secret is still hidden.
const UNSAFE_DETAIL = /traceback|exception|stack|sql|psycopg|postgres|select\s|insert\s|update\s|delete\s|password|secret|token|credential|api[_-]?key|file "|line \d+|0x[0-9a-f]{6,}/i;
export function staffOperationalMessage(path, detail) {
  if (!/^\/(admin|officer)\//.test(path)) return null;
  if (typeof detail !== 'string' || !detail.trim() || detail.length > 200 || /[\r\n]/.test(detail) || UNSAFE_DETAIL.test(detail)) return null;
  return detail;
}

async function request(path, options = {}) {
  const { timeoutMs = REQUEST_TIMEOUT_MS, ...fetchOptions } = options;
  const method = (fetchOptions.method || 'GET').toUpperCase();
  const isChange = method !== 'GET';
  const headers = { 'Content-Type': 'application/json', ...(fetchOptions.headers || {}) };
  if (sessionToken) headers.Authorization = `Bearer ${sessionToken}`;
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  let res;
  try {
    res = await fetch(`${BASE}${path}`, { ...fetchOptions, headers, ...(controller ? { signal: controller.signal } : {}) });
  } catch (cause) {
    // Never surface the browser's raw network error ("Failed to fetch" etc.).
    const timedOut = cause?.name === 'AbortError';
    const error = new Error(timedOut ? (isChange ? OUTCOME_UNKNOWN_ERROR : TIMEOUT_ERROR) : NETWORK_ERROR);
    error.status = 0;
    error.timedOut = timedOut;
    error.outcomeUnknown = timedOut && isChange;
    throw error;
  } finally {
    if (timer) clearTimeout(timer);
  }
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) { sessionToken = null; onUnauthorized(); }
  if (!res.ok) {
    // A proxy gateway timeout on a change means the server may still finish it.
    const outcomeUnknown = isChange && GATEWAY_TIMEOUT_STATUSES.has(res.status);
    // Citizens get one generic message for server-side failures; the
    // backend's own 4xx messages are written for the person using the service.
    const message = outcomeUnknown ? OUTCOME_UNKNOWN_ERROR
      : res.status >= 500 ? (staffOperationalMessage(path, data.detail) || SERVER_ERROR)
      : errorMessage(data.detail);
    const error = new Error(message);
    error.status = res.status;
    error.detail = data.detail;
    error.outcomeUnknown = outcomeUnknown;
    throw error;
  }
  return data;
}
export const api = {
  login: (citizenId, password) => request('/auth/login', { method: 'POST', body: JSON.stringify({ citizenId, password }) }),
  // Public demonstration accounts (only when the server runs in explicit
  // public-demo mode; 404 otherwise). The server never sends a password.
  publicDemoAccounts: () => request('/auth/public-demo/accounts'),
  publicDemoSignIn: citizenId => request('/auth/public-demo/sign-in', { method: 'POST', body: JSON.stringify({ citizenId }) }),
  schemes: () => request('/citizen/schemes'),
  services: () => request('/citizen/services'),
  service: serviceId => request(`/citizen/services/${encodeURIComponent(serviceId)}`),
  applications: () => request('/citizen/applications'),
  application: applicationId => request(`/citizen/applications/${encodeURIComponent(applicationId)}`),
  createApplication: body => request('/citizen/applications', { method: 'POST', body: JSON.stringify(body) }),
  applyToScheme: schemeId => request('/citizen/apply', { method: 'POST', body: JSON.stringify({ schemeId }) }),
  autoFillRequirement: (applicationId, requirementCode, decision = 'ACCEPT') => request(`/citizen/applications/${encodeURIComponent(applicationId)}/requirements/${encodeURIComponent(requirementCode)}/auto-fill`, { method: 'POST', body: JSON.stringify({ decision }), timeoutMs: LONG_REQUEST_TIMEOUT_MS }),
  uploadRequirement: (applicationId, requirementCode, body) => request(`/citizen/applications/${encodeURIComponent(applicationId)}/requirements/${encodeURIComponent(requirementCode)}/upload`, { method: 'POST', body: JSON.stringify(body), timeoutMs: LONG_REQUEST_TIMEOUT_MS }),
  removeUpload: (applicationId, requirementCode) => request(`/citizen/applications/${encodeURIComponent(applicationId)}/requirements/${encodeURIComponent(requirementCode)}/upload`, { method: 'DELETE' }),
  submitApplication: applicationId => request(`/citizen/applications/${encodeURIComponent(applicationId)}/submit`, { method: 'POST', body: JSON.stringify({}) }),
  viewDocument: (applicationId, requirementCode) => request(`/citizen/applications/${encodeURIComponent(applicationId)}/requirements/${encodeURIComponent(requirementCode)}/document`),
  downloadDocument: async (applicationId, requirementCode) => {
    const headers = {};
    if (sessionToken) headers.Authorization = `Bearer ${sessionToken}`;
    let res;
    try {
      res = await fetch(`${BASE}/citizen/applications/${encodeURIComponent(applicationId)}/requirements/${encodeURIComponent(requirementCode)}/document/download`, { headers });
    } catch {
      throw new Error(NETWORK_ERROR);
    }
    if (res.status === 401) { sessionToken = null; onUnauthorized(); }
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(res.status >= 500 ? SERVER_ERROR : errorMessage(data.detail, 'The document could not be downloaded.'));
    }
    const blob = await res.blob();
    const match = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') || '');
    return { blob, filename: match ? match[1] : 'document.txt' };
  },
  catalog: () => request('/catalog'),
  discover: (citizenId, timeout = false, schemeId = '') => request(`/citizen/discover?citizen_id=${encodeURIComponent(citizenId)}&simulate_timeout=${timeout}${schemeId ? `&scheme_id=${encodeURIComponent(schemeId)}` : ''}`),
  consent: (citizenId, allow, schemeId = null) => request('/citizen/consent', { method: 'POST', body: JSON.stringify({ citizenId, allow, schemeId }) }),
  domicile: (citizenId, appId) => request('/citizen/orchestrate-dependency', { method: 'POST', body: JSON.stringify({ citizenId, appId }) }),
  submit: (citizenId, appId, timeout = false) => request('/citizen/submit', { method: 'POST', body: JSON.stringify({ citizenId, appId, simulateTimeout: timeout }) }),
  track: (appId) => request(`/citizen/track/${appId}`),
  queue: () => request('/officer/queue'),
  action: (appId, action, remarks, reviewId, selectedSource) => request('/officer/action', { method: 'POST', body: JSON.stringify({ appId, action, remarks, reviewId, selectedSource }) }),
  audit: () => request('/admin/audit-trail'),
  integrationHealth: () => request('/admin/integration-health'),
  dependencyRegistry: () => request('/admin/dependency-registry'),
  resetDemo: () => request('/admin/demo/reset', { method: 'POST' }),
  notifications: (role) => request(`/${role.toLowerCase()}/notifications`),
  markNotificationRead: (notificationId) => request(`/notifications/${notificationId}/read`, { method: 'POST' }),
  markAllNotificationsRead: () => request('/notifications/read-all', { method: 'POST' }),
  adminOverview: () => request('/admin/operations/overview'),
  adminIncidents: () => request('/admin/operations/incidents'),
  adminDepartments: () => request('/admin/operations/departments'),
  adminActivity: ({ limit = 30, applicationId } = {}) => request(`/admin/operations/activity?limit=${limit}${applicationId ? `&applicationId=${encodeURIComponent(applicationId)}` : ''}`),
  adminSetDepartmentAvailability: (departmentKey, available) => request(`/admin/operations/departments/${encodeURIComponent(departmentKey)}/availability`, { method: 'POST', body: JSON.stringify({ available }) }),
  adminIncidentImpact: incidentId => request(`/admin/operations/incidents/${encodeURIComponent(incidentId)}/impact`),
  adminApplications: (params = {}) => {
    const q = new URLSearchParams();
    if (params.status) q.set('status', params.status);
    if (params.search) q.set('search', params.search);
    if (params.limit) q.set('limit', params.limit);
    const qs = q.toString();
    return request('/admin/applications' + (qs ? `?${qs}` : ''));
  },
  adminApplicationDetail: (appId) => request(`/admin/applications/${encodeURIComponent(appId)}`),
  adminProviders: () => request('/admin/operations/providers'),
  adminProviderRegistry: () => request('/admin/operations/providers/registry'),
  adminAnalytics: (filters = {}) => {
    const q = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => { if (value) q.set(key, value); });
    const qs = q.toString();
    return request('/admin/analytics' + (qs ? `?${qs}` : ''));
  },
  adminSchemes: () => request('/admin/schemes'),
  adminSchemeDetail: (schemeId) => request(`/admin/schemes/${encodeURIComponent(schemeId)}`),
  adminProfile: () => request('/admin/profile'),
  citizenProfile: () => request('/citizen/profile'),
  adminProviderDetail: (providerId) => request(`/admin/operations/providers/registry/${encodeURIComponent(providerId)}`),
  adminDeadLetterJobs: (limit = 50) => request(`/admin/operations/jobs/dead-letter?limit=${limit}`),
  adminRecentJobs: (limit = 50) => request(`/admin/operations/jobs/recent?limit=${limit}`),
  adminReplayJob: (jobId) => request(`/admin/operations/jobs/${encodeURIComponent(jobId)}/replay`, { method: 'POST' }),
  adminSimulateHealth: (system, available, error) => request('/admin/integration-health/simulate', { method: 'POST', body: JSON.stringify({ system, available, error }) }),
  adminWorkerStatus: () => request('/admin/operations/worker'),
  adminSchemaMappingReviews: () => request('/officer/schema-mapping-reviews'),
  adminSchemaMappingAction: (reviewId, decision, remarks) => request('/officer/schema-mapping-action', { method: 'POST', body: JSON.stringify({ reviewId, decision, remarks }) }),
};
