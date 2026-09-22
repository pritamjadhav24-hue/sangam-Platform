import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { languageText, categoryLabel } from '../i18n';
import { applicationStateLabel } from '../applicationState';

export default function SchemesPage({ applications, onViewScheme, language = 'en' }) {
  const t = languageText(language);
  const [schemes, setSchemes] = useState(null); // null while loading
  const [error, setError] = useState(null);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('ALL');
  const appliedByScheme = useMemo(() => {
    const map = new Map();
    for (const application of applications || []) map.set(application.serviceId, application);
    return map;
  }, [applications]);

  useEffect(() => {
    let active = true;
    setSchemes(null);
    setError(null);
    api.services()
      .then(result => { if (active) setSchemes(result.services || []); })
      .catch(err => { if (active) setError(err.message || (language === 'en' ? 'Unable to load schemes right now.' : 'सध्या योजना लोड करता आल्या नाहीत.')); });
    return () => { active = false; };
  }, [language]);

  const categories = useMemo(() => {
    const found = new Set((schemes || []).map(scheme => scheme.category).filter(Boolean));
    return ['ALL', ...Array.from(found).sort()];
  }, [schemes]);

  const filtered = useMemo(() => {
    if (!schemes) return [];
    const needle = query.trim().toLowerCase();
    return schemes.filter(scheme => {
      const matchesCategory = category === 'ALL' || scheme.category === category;
      if (!matchesCategory) return false;
      if (!needle) return true;
      const haystack = `${scheme.name || ''} ${scheme.nameMr || ''} ${scheme.description || ''} ${scheme.department || ''}`.toLowerCase();
      return haystack.includes(needle);
    });
  }, [schemes, query, category]);

  return (
    <main className="container scheme-catalogue">
      <div className="page-title">
        <div>
          <p className="eyebrow">{language === 'en' ? 'Scheme catalogue' : 'योजना सूची'}</p>
          <h1>{language === 'en' ? 'Government schemes & services' : 'शासकीय योजना व सेवा'}</h1>
          <p className="muted">{language === 'en' ? 'Discover schemes across Maharashtra government departments, verified automatically through SANGAM.' : 'महाराष्ट्र शासनाच्या विविध विभागांमधील योजना शोधा, SANGAM द्वारे आपोआप पडताळलेल्या.'}</p>
        </div>
      </div>

      <div className="card scheme-catalogue-controls">
        <div className="search-service">
          <label htmlFor="scheme-search">{language === 'en' ? 'Search schemes' : 'योजना शोधा'}</label>
          <input id="scheme-search" value={query} onChange={event => setQuery(event.target.value)} placeholder={t.search} />
        </div>
        {schemes && schemes.length > 0 && (
          <div className="category-filters" role="group" aria-label={language === 'en' ? 'Filter by category' : 'श्रेणीनुसार गाळा'}>
            {categories.map(cat => (
              <button key={cat} type="button" className={cat === category ? 'chip selected' : 'chip'} onClick={() => setCategory(cat)}>
                {cat === 'ALL' ? (language === 'en' ? 'All categories' : 'सर्व श्रेणी') : categoryLabel(cat, language)}
              </button>
            ))}
          </div>
        )}
      </div>

      {schemes === null && !error && <p className="loading-state" role="status">{language === 'en' ? 'Loading schemes…' : 'योजना लोड होत आहेत…'}</p>}
      {error && <div className="alert danger" role="alert">{error}</div>}

      {schemes !== null && !error && (
        filtered.length ? (
          <div className="scheme-grid">
            {filtered.map(scheme => {
              const id = scheme.serviceId || scheme.schemeId;
              const application = appliedByScheme.get(id);
              return (
                <article className="scheme-card card" key={id}>
                  <div className="scheme-card-heading">
                    {scheme.category && <span className="tag">{categoryLabel(scheme.category, language)}</span>}
                    {scheme.synthetic && <span className="tag demo-tag">{language === 'en' ? 'Demo' : 'नमुना'}</span>}
                    {application && <span className="tag applied-tag">{application.status === 'SUBMITTED' ? applicationStateLabel('SUBMITTED', language) : t.alreadyApplied}</span>}
                  </div>
                  <h3>{language === 'en' ? scheme.name : (scheme.nameMr || scheme.name)}</h3>
                  <p>{language === 'en' ? scheme.description : (scheme.descriptionMr || scheme.description)}</p>
                  <div className="scheme-card-footer">
                    <small>{language === 'en' ? scheme.department : (scheme.departmentMr || scheme.department)}</small>
                    <button className="outline" onClick={() => onViewScheme(id)}>{language === 'en' ? 'View details' : 'तपशील पहा'}</button>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <p className="empty-state">{t.noResults}</p>
        )
      )}
    </main>
  );
}
