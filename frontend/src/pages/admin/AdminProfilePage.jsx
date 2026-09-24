import { useEffect, useState } from 'react';

const AREA_LABELS = {
  '/api/admin': 'Admin operations console',
  '/api/officer': 'Officer review desk',
  '/api/citizen': 'Citizen portal',
  '/api/catalog': 'Service catalogue',
  '/api/notifications': 'Notifications',
  '/api/auth': 'Sign-in',
};

export default function AdminProfilePage({ api }) {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    api.adminProfile()
      .then(setProfile)
      .catch(err => setError(err.message || 'Failed to load profile.'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="container">
      <div className="page-title">
        <div>
          <p className="eyebrow">Profile / Access · Admin</p>
          <h1>Profile &amp; Access</h1>
          <p>Your identity, current session and the access model SANGAM actually enforces.</p>
        </div>
      </div>

      {error && <div className="alert danger" role="alert">{error}</div>}
      {loading && <p className="loading-state">Loading profile…</p>}

      {profile && (
        <>
          <div className="summary-grid" style={{ marginBottom: '20px' }}>
            <div className="summary-card">
              <span className="eyebrow">Signed in as</span>
              <b style={{ fontSize: '20px' }}>{profile.user.name}</b>
              <small><code>{profile.user.userId}</code></small>
            </div>
            <div className="summary-card blue">
              <span className="eyebrow">Role</span>
              <b style={{ fontSize: '20px' }}>{profile.user.role}</b>
              <small>Platform-wide operational visibility</small>
            </div>
            <div className="summary-card">
              <span className="eyebrow">Session issued</span>
              <b style={{ fontSize: '16px' }}>{new Date(profile.session.issuedAt).toLocaleString()}</b>
              <small>Reference {profile.session.sessionRef}</small>
            </div>
            <div className="summary-card amber">
              <span className="eyebrow">Session expires</span>
              <b style={{ fontSize: '16px' }}>{new Date(profile.session.expiresAt).toLocaleString()}</b>
              <small>Signed token, {Math.round(profile.session.lifetimeSeconds / 60)}-minute lifetime</small>
            </div>
          </div>

          <div className="card">
            <div className="section-heading">
              <div>
                <h2>Effective access model</h2>
                <p>
                  Derived from the role guard on every live API endpoint. SANGAM uses three fixed roles
                  ({profile.access.roles.join(', ')}); permissions are not editable at runtime, so this view is read-only.
                </p>
              </div>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>Area</th>
                    <th>Endpoints</th>
                    {profile.access.roles.map(role => <th key={role}>{role}</th>)}
                    <th>Unauthenticated</th>
                  </tr>
                </thead>
                <tbody>
                  {profile.access.areas.map(area => (
                    <tr key={area.area}>
                      <td><b>{AREA_LABELS[area.area] || area.area}</b><small><code>{area.area}</code></small></td>
                      <td>{area.endpoints}</td>
                      {profile.access.roles.map(role => {
                        const count = area.byRole[role] || 0;
                        return (
                          <td key={role}>
                            {count > 0
                              ? <span className={`status ${role === profile.user.role ? 'found' : 'pending'}`}>{count === area.endpoints ? 'All' : `${count} of ${area.endpoints}`}</span>
                              : <span className="muted">—</span>}
                          </td>
                        );
                      })}
                      <td>{area.public > 0 ? `${area.public} (sign-in)` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted" style={{ marginTop: '12px', fontSize: '13px' }}>
              Admin access is exception-oriented: operational oversight, investigation and replay. Normal citizen document retrieval remains fully automated and never requires Admin approval.
            </p>
          </div>
        </>
      )}
    </main>
  );
}
