import { languageText } from '../i18n';

function initials(name) {
  const parts = (name || '').split(' ').filter(Boolean);
  return (parts[0]?.[0] || '') + (parts[1]?.[0] || '');
}

export default function ProfilePage({ citizen, applications, language = 'en' }) {
  const t = languageText(language);
  const apps = applications || [];
  const submitted = apps.filter(item => item.status === 'SUBMITTED').length;
  const active = apps.filter(item => item.status === 'IN_PROGRESS').length;

  return (
    <main className="container narrow">
      <div className="page-title">
        <div>
          <p className="eyebrow">{t.profileNav}</p>
          <h1>{language === 'en' ? 'Your profile' : 'आपली प्रोफाइल'}</h1>
        </div>
      </div>

      <section className="card form-section">
        <div className="profile-header">
          <div className="profile-avatar" aria-hidden="true">{initials(citizen?.name).toUpperCase()}</div>
          <div>
            <h2 style={{ margin: 0 }}>{citizen?.name}</h2>
            <p className="muted" style={{ margin: 0 }}>{citizen?.citizenId || citizen?.userId}</p>
          </div>
        </div>
        <ul className="compact">
          {citizen?.dob && <li><span>{language === 'en' ? 'Date of birth' : 'जन्मतारीख'}</span><span>{citizen.dob}</span></li>}
          {citizen?.phone && <li><span>{language === 'en' ? 'Phone' : 'फोन'}</span><span>{citizen.phone}</span></li>}
          {citizen?.district && <li><span>{language === 'en' ? 'District' : 'जिल्हा'}</span><span>{citizen.district}</span></li>}
          {citizen?.persona && <li><span>{language === 'en' ? 'Category' : 'श्रेणी'}</span><span className="persona-tag">{citizen.persona.replace(/_/g, ' ').toLowerCase()}</span></li>}
        </ul>
      </section>

      <section className="card form-section">
        <h2>{language === 'en' ? 'Application summary' : 'अर्ज सारांश'}</h2>
        <ul className="compact">
          <li><span>{t.activeApplications}</span><span>{active}</span></li>
          <li><span>{t.submittedApplications}</span><span>{submitted}</span></li>
          <li><span>{language === 'en' ? 'Total applications' : 'एकूण अर्ज'}</span><span>{apps.length}</span></li>
        </ul>
      </section>
    </main>
  );
}
