import { useEffect, useState } from 'react';
import { FileText, IdCard, UserRound } from 'lucide-react';
import { languageText } from '../i18n';
import { StatusPill } from '../components/ui';

function initials(name) {
  return (name || '').split(' ').filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase();
}

function when(iso, language) {
  if (!iso) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString(language === 'mr' ? 'mr-IN' : 'en-IN', { dateStyle: 'medium', timeStyle: 'short' });
}

// A row only when the value exists -- nothing is invented for a citizen.
function Detail({ label, value }) {
  if (value === undefined || value === null || value === '') return null;
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

export default function ProfilePage({ citizen, applications, language = 'en', loadProfile }) {
  const t = languageText(language);
  const isMr = language === 'mr';
  const [record, setRecord] = useState(null);
  const apps = applications || [];
  const submitted = apps.filter(item => item.status === 'SUBMITTED').length;
  const active = apps.filter(item => item.status === 'IN_PROGRESS').length;

  useEffect(() => {
    if (!loadProfile) return undefined;
    let current = true;
    loadProfile().then(result => { if (current) setRecord(result); }).catch(() => {});
    return () => { current = false; };
  }, [loadProfile]);

  const person = { ...citizen, ...(record || {}) };
  const citizenId = person.citizenId || person.userId;
  const gender = person.gender ? person.gender.charAt(0) + person.gender.slice(1).toLowerCase() : null;

  return (
    <main className="container narrow">
      <div className="page-title">
        <div>
          <p className="eyebrow">{t.profileNav}</p>
          <h1>{isMr ? 'आपली प्रोफाइल' : 'Your profile'}</h1>
        </div>
      </div>

      <section className="card profile-summary">
        <div className="profile-avatar" aria-hidden="true">{initials(person.name)}</div>
        <div className="profile-identity">
          <h2>{person.name}</h2>
          <p className="muted">{citizenId}</p>
        </div>
        <StatusPill status="AVAILABLE" label={record?.verifiedIdentity ? (isMr ? 'ओळख पडताळली' : 'Identity verified') : (isMr ? 'सक्रिय खाते' : 'Active account')} />
      </section>

      <section className="card">
        <h2 className="section-title"><UserRound size={18} aria-hidden="true" />{isMr ? 'वैयक्तिक माहिती' : 'Personal details'}</h2>
        <dl className="detail-list">
          <Detail label={isMr ? 'जन्मतारीख' : 'Date of birth'} value={person.dob} />
          <Detail label={isMr ? 'लिंग' : 'Gender'} value={gender} />
          <Detail label={isMr ? 'फोन' : 'Phone'} value={person.phone} />
          <Detail label={isMr ? 'जिल्हा' : 'District'} value={person.district} />
          <Detail label={isMr ? 'पत्ता' : 'Address'} value={person.address} />
          {person.persona && <Detail label={isMr ? 'श्रेणी' : 'Category'} value={<span className="persona-tag">{person.persona.replace(/_/g, ' ').toLowerCase()}</span>} />}
        </dl>
      </section>

      <section className="card">
        <h2 className="section-title"><IdCard size={18} aria-hidden="true" />{isMr ? 'खाते' : 'Account'}</h2>
        <dl className="detail-list">
          <Detail label={isMr ? 'नागरिक क्रमांक' : 'Citizen ID'} value={citizenId} />
          <Detail label={isMr ? 'खात्याची स्थिती' : 'Account status'} value={record?.accountStatus || (isMr ? 'सक्रिय' : 'Active')} />
          <Detail label={isMr ? 'पसंतीची भाषा' : 'Preferred language'} value={isMr ? 'मराठी' : 'English'} />
          <Detail label={isMr ? 'साइन इन' : 'Signed in'} value={when(record?.session?.signedInAt, language)} />
          <Detail label={isMr ? 'सत्र समाप्ती' : 'Session expires'} value={when(record?.session?.expiresAt, language)} />
        </dl>
      </section>

      <section className="card">
        <h2 className="section-title"><FileText size={18} aria-hidden="true" />{isMr ? 'अर्ज सारांश' : 'Application summary'}</h2>
        <dl className="detail-list">
          <Detail label={t.activeApplications} value={String(active)} />
          <Detail label={t.submittedApplications} value={String(submitted)} />
          <Detail label={isMr ? 'एकूण अर्ज' : 'Total applications'} value={String(apps.length)} />
        </dl>
      </section>
    </main>
  );
}
