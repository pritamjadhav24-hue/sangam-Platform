import { useEffect, useState } from 'react';
import { Building2, KeyRound, ShieldCheck } from 'lucide-react';
import { ErrorState, Skeleton, StatusPill } from '../../components/ui';

const AREA_LABELS = {
  '/api/admin': 'Admin operations console',
  '/api/officer': 'Officer review desk',
  '/api/citizen': 'Citizen portal',
  '/api/catalog': 'Service catalogue',
  '/api/notifications': 'Notifications',
  '/api/auth': 'Sign-in',
};

function when(iso) {
  if (!iso) return 'Not recorded';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? 'Not recorded' : date.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
}

function initials(name) {
  return (name || '').split(' ').filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase();
}

function Detail({ label, children }) {
  return <div><dt>{label}</dt><dd>{children || 'Not recorded'}</dd></div>;
}

export default function AdminProfilePage({ api, language = 'en' }) {
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState('');

  const load = () => {
    setError('');
    api.adminProfile().then(setProfile).catch(err => setError(err.message || 'Failed to load profile.'));
  };
  useEffect(load, []);

  const user = profile?.user || {};
  const security = profile?.security || {};

  return (
    <main className="container">
      <div className="page-title">
        <div>
          <p className="eyebrow">Account</p>
          <h1>Profile</h1>
        </div>
      </div>

      {error && <ErrorState title="Profile could not be loaded" message={error} onRetry={load} />}
      {!profile && !error && <Skeleton lines={5} label="Loading profile" />}

      {profile && (
        <>
          <section className="card profile-summary">
            <div className="profile-avatar" aria-hidden="true">{initials(user.name)}</div>
            <div className="profile-identity">
              <h2>{user.name}</h2>
              <p className="muted">{[user.designation, user.organisation].filter(Boolean).join(' · ')}</p>
            </div>
            <StatusPill status="AVAILABLE" label={user.accountStatus || 'Active'} />
          </section>

          <div className="profile-grid">
            <section className="card">
              <h2 className="section-title"><Building2 size={18} aria-hidden="true" />Account details</h2>
              <dl className="detail-list">
                <Detail label="Admin ID"><code>{user.userId}</code></Detail>
                <Detail label="Role">{user.role === 'ADMIN' ? 'Administrator' : user.role}</Detail>
                <Detail label="Access level">{user.accessLevel}</Detail>
                <Detail label="Organisation">{user.organisation}</Detail>
                <Detail label="Unit">{user.unit}</Detail>
                <Detail label="Official email">{user.officialEmail}</Detail>
                <Detail label="Contact number">{user.phone}</Detail>
                <Detail label="Account created">{user.accountCreated ? new Date(user.accountCreated).toLocaleDateString('en-IN', { dateStyle: 'medium' }) : null}</Detail>
                <Detail label="Preferred language">{language === 'mr' ? 'मराठी' : 'English'}</Detail>
              </dl>
            </section>

            <section className="card">
              <h2 className="section-title"><KeyRound size={18} aria-hidden="true" />Security</h2>
              <dl className="detail-list">
                <Detail label="Authentication">{security.authentication}</Detail>
                <Detail label="Password">{security.passwordStored}</Detail>
                <Detail label="Last password change">{when(security.lastPasswordChange)}</Detail>
                <Detail label="Signed in">{when(security.signedInAt || profile.session.issuedAt)}</Detail>
                <Detail label="Session expires">{when(profile.session.expiresAt)}</Detail>
                <Detail label="Session reference"><code>{profile.session.sessionRef}</code></Detail>
              </dl>
            </section>
          </div>

          <section className="card">
            <h2 className="section-title"><ShieldCheck size={18} aria-hidden="true" />Access by area</h2>
            <p className="muted small-text">Roles: {profile.access.roles.join(', ')}. Read-only.</p>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Area</th>
                    <th>Endpoints</th>
                    {profile.access.roles.map(role => <th key={role}>{role}</th>)}
                    <th>Public</th>
                  </tr>
                </thead>
                <tbody>
                  {profile.access.areas.map(area => (
                    <tr key={area.area}>
                      <td><b>{AREA_LABELS[area.area] || area.area}</b></td>
                      <td>{area.endpoints}</td>
                      {profile.access.roles.map(role => {
                        const count = area.byRole[role] || 0;
                        return (
                          <td key={role}>
                            {count > 0
                              ? <StatusPill status={role === user.role ? 'AVAILABLE' : 'INFO'} label={count === area.endpoints ? 'All' : `${count} of ${area.endpoints}`} />
                              : <span className="muted">—</span>}
                          </td>
                        );
                      })}
                      <td>{area.public > 0 ? area.public : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
