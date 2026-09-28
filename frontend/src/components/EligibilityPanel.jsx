// Citizen-facing view of the deterministic eligibility assessment returned
// on every application (eligibilityAssessment). Shows the outcome and each
// criterion with the reason -- never a score, and never where the data came from.
const HEADINGS = {
  ELIGIBLE: { en: 'Eligible', mr: 'पात्र', className: 'success' },
  NOT_ELIGIBLE: { en: 'Not eligible', mr: 'अपात्र', className: 'danger' },
  CANNOT_CONFIRM: { en: 'Eligibility cannot be confirmed yet', mr: 'पात्रता अद्याप निश्चित करता येत नाही', className: 'notice' },
};
const SUMMARY = {
  ELIGIBLE: { en: 'You meet every criterion for this scheme.', mr: 'आपण या योजनेचे सर्व निकष पूर्ण करता.' },
  NOT_ELIGIBLE: { en: 'Based on your verified information, you do not meet the criteria marked below.', mr: 'आपल्या पडताळलेल्या माहितीनुसार, आपण खाली दर्शवलेले निकष पूर्ण करत नाही.' },
  CANNOT_CONFIRM: { en: 'Some information is missing or still being verified. This is not a rejection. Complete the items marked “Not yet known” in the documents section.', mr: 'काही माहिती अपूर्ण आहे किंवा अद्याप पडताळली जात आहे. हा नकार नाही. तपासणी पूर्ण करण्यासाठी, “अद्याप माहित नाही” असे दर्शवलेल्या बाबी ऑटो-फिल करा किंवा दस्तऐवज विभागात अपलोड करा.' },
};
const STATUS = {
  PASS: { icon: '✓', en: 'Met', mr: 'पूर्ण', className: 'found' },
  FAIL: { icon: '✕', en: 'Not met', mr: 'पूर्ण नाही', className: 'exception' },
  UNKNOWN: { icon: '?', en: 'Not yet known', mr: 'अद्याप माहित नाही', className: 'pending' },
};

export default function EligibilityPanel({ assessment, language = 'en' }) {
  if (!assessment || !HEADINGS[assessment.result]) return null;
  const isMr = language === 'mr';
  const heading = HEADINGS[assessment.result];
  return (
    <section className="card form-section eligibility-panel" aria-label={isMr ? 'पात्रता' : 'Eligibility'}>
      <h2>{isMr ? 'पात्रता' : 'Eligibility'}</h2>
      <div className={`alert ${heading.className}`} role="status">
        <b>{isMr ? heading.mr : heading.en}</b>
        <div>{isMr ? SUMMARY[assessment.result].mr : SUMMARY[assessment.result].en}</div>
        {assessment.conflict && <div>{isMr ? 'काही माहिती परस्परविरोधी आहे व तिचे पुनरावलोकन सुरू आहे.' : 'Some information conflicts and is being reviewed.'}</div>}
      </div>
      <ul className="eligibility-criteria">
        {assessment.criteria.map(item => {
          const status = STATUS[item.status] || STATUS.UNKNOWN;
          return (
            <li key={item.id} className={`eligibility-criterion criterion-${item.status.toLowerCase()}`}>
              <span className={`status ${status.className}`}>{status.icon} {isMr ? status.mr : status.en}</span>
              <span>
                <b>{isMr ? item.labelMr : item.label}</b>
                <small className="muted">{isMr ? (item.reasonMr || item.reason) : item.reason}</small>
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
