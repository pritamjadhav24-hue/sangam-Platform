const BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001/api';
let sessionToken = null;
let onUnauthorized = () => {};
export const setSessionToken = token => { sessionToken = token; };
export const setAuthFailureHandler = handler => { onUnauthorized = handler || (() => {}); };
async function request(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (sessionToken) headers.Authorization = `Bearer ${sessionToken}`;
  const res = await fetch(`${BASE}${path}`, { ...options, headers });
  const data = await res.json();
  if (res.status === 401) { sessionToken = null; onUnauthorized(); }
  if (!res.ok) throw new Error(data.detail || 'The service could not complete this request.');
  return data;
}
export const api = {
  login: (citizenId, password) => request('/auth/login', { method: 'POST', body: JSON.stringify({ citizenId, password }) }),
  // DEMO ONLY: lists/switches between seeded synthetic citizens. Backend
  // returns an empty list when demo switching isn't enabled server-side, so
  // the UI naturally hides the control rather than hardcoding a citizen list.
  demoCitizens: () => request('/auth/demo-citizens').catch(() => ({ citizens: [] })),
  demoLogin: citizenId => request('/auth/demo-login', { method: 'POST', body: JSON.stringify({ citizenId }) }),
  schemes: () => request('/citizen/schemes'),
  services: () => request('/citizen/services'),
  service: serviceId => request(`/citizen/services/${encodeURIComponent(serviceId)}`),
  applications: () => request('/citizen/applications'),
  application: applicationId => request(`/citizen/applications/${encodeURIComponent(applicationId)}`),
  createApplication: body => request('/citizen/applications', { method: 'POST', body: JSON.stringify(body) }),
  applyToScheme: schemeId => request('/citizen/apply', { method: 'POST', body: JSON.stringify({ schemeId }) }),
  autoFillRequirement: (applicationId, requirementCode, decision = 'ACCEPT') => request(`/citizen/applications/${encodeURIComponent(applicationId)}/requirements/${encodeURIComponent(requirementCode)}/auto-fill`, { method: 'POST', body: JSON.stringify({ decision }) }),
  uploadRequirement: (applicationId, requirementCode, body) => request(`/citizen/applications/${encodeURIComponent(applicationId)}/requirements/${encodeURIComponent(requirementCode)}/upload`, { method: 'POST', body: JSON.stringify(body) }),
  submitApplication: applicationId => request(`/citizen/applications/${encodeURIComponent(applicationId)}/submit`, { method: 'POST', body: JSON.stringify({}) }),
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
};
