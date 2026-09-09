const BASE = 'http://127.0.0.1:8000/api';
let sessionToken = null;
export const setSessionToken = token => { sessionToken = token; };
async function request(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (sessionToken) headers.Authorization = `Bearer ${sessionToken}`;
  const res = await fetch(`${BASE}${path}`, { ...options, headers });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || 'The service could not complete this request.');
  return data;
}
export const api = {
  login: (citizenId, password) => request('/auth/login', { method: 'POST', body: JSON.stringify({ citizenId, password }) }),
  schemes: () => request('/citizen/schemes'),
  discover: (citizenId, timeout = false) => request(`/citizen/discover?citizen_id=${encodeURIComponent(citizenId)}&simulate_timeout=${timeout}`),
  consent: (citizenId, allow) => request('/citizen/consent', { method: 'POST', body: JSON.stringify({ citizenId, allow }) }),
  domicile: (citizenId, appId) => request('/citizen/orchestrate-dependency', { method: 'POST', body: JSON.stringify({ citizenId, appId }) }),
  submit: (citizenId, appId, timeout = false) => request('/citizen/submit', { method: 'POST', body: JSON.stringify({ citizenId, appId, simulateTimeout: timeout }) }),
  track: (appId) => request(`/citizen/track/${appId}`),
  queue: () => request('/officer/queue'),
  action: (appId, action, remarks, reviewId, selectedSource) => request('/officer/action', { method: 'POST', body: JSON.stringify({ appId, action, remarks, reviewId, selectedSource }) }),
  audit: () => request('/admin/audit-trail'),
  integrationHealth: () => request('/admin/integration-health'),
  dependencyRegistry: () => request('/admin/dependency-registry'),
};
