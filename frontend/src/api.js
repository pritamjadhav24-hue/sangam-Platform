const BASE = 'http://127.0.0.1:8000/api';
async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || 'The service could not complete this request.');
  return data;
}
export const api = {
  login: (citizenId, password) => request('/auth/login', { method: 'POST', body: JSON.stringify({ citizenId, password }) }),
  schemes: () => request('/citizen/schemes'),
  discover: (timeout = false) => request(`/citizen/discover?citizen_id=CITIZEN_001&simulate_timeout=${timeout}`),
  consent: (allow) => request('/citizen/consent', { method: 'POST', body: JSON.stringify({ citizenId: 'CITIZEN_001', allow }) }),
  domicile: (appId) => request('/citizen/orchestrate-dependency', { method: 'POST', body: JSON.stringify({ citizenId: 'CITIZEN_001', appId }) }),
  submit: (appId, timeout = false) => request('/citizen/submit', { method: 'POST', body: JSON.stringify({ citizenId: 'CITIZEN_001', appId, simulateTimeout: timeout }) }),
  track: (appId) => request(`/citizen/track/${appId}`),
  queue: () => request('/officer/queue'),
  action: (appId, action, remarks, reviewId) => request('/officer/action', { method: 'POST', body: JSON.stringify({ appId, action, remarks, reviewId }) }),
  audit: () => request('/admin/audit-trail'),
  integrationHealth: () => request('/admin/integration-health'),
};
