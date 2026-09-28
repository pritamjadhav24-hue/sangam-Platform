import { useCallback, useEffect, useState } from 'react';
import {
  ArrowLeft, ArrowRight, BadgeCheck, Camera, CircleAlert, CloudOff, Download, Eye, FileText, IdCard, LoaderCircle, RefreshCw,
  Replace, Save, SearchX, ShieldAlert, ShieldCheck, Sparkles, Trash2, Upload, UserRound,
} from 'lucide-react';
import { api } from '../api';
import { NEEDS_ATTENTION_STATUSES, requirementStateClass, requirementStateLabel } from '../requirementState';
import { categoryLabel } from '../i18n';
import { useDismiss } from '../useDismiss';
import { schemeImage } from '../schemeImages';
import DocumentUploader from '../components/DocumentUploader';
import { useToast } from '../components/ui';
import EligibilityPanel from '../components/EligibilityPanel';

const SATISFIED = new Set(['VALIDATED', 'RETRIEVED']);

function isDocumentLike(requirement) {
  return requirement.dataType === 'DOCUMENT' || requirement.dataType === 'CERTIFICATE';
}

function verifiedWhen(iso, language) {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return language === 'mr' ? 'आज' : 'Today';
  return date.toLocaleDateString(language === 'mr' ? 'mr-IN' : 'en-IN', { dateStyle: 'medium' });
}

// What the card says for each verification state the backend reports. The
// backend decides the state; the card only words it and offers the actions
// that really exist for it (never "upload" where upload is not possible).
const STATE_COPY = {
  en: {
    NO_RECORD: ['No verified record was found in the connected departments.', 'You can provide the document yourself.'],
    TEMPORARILY_UNAVAILABLE: ['Government verification is temporarily unavailable.', 'Your application is kept. Retry in a little while, or provide the document yourself.'],
    TIMEOUT: ['The government department took too long to respond.', 'Retry in a little while, or provide the document yourself.'],
    LOW_CONFIDENCE: ["We couldn't verify this record with sufficient confidence.", 'To protect your information, it was not added. You can provide the document yourself.'],
    AMBIGUOUS_MATCH: ['More than one record matched your details.', 'To protect your information, none was added. You can provide the document yourself.'],
    UNAUTHORIZED: ['Automatic retrieval is not authorized for this record.', 'You can provide the document yourself.'],
    CONSENT_DENIED: ['You chose not to allow automatic retrieval.', 'You can allow Auto-Fill at any time, or provide the document yourself.'],
    VERIFICATION_FAILED: ['The retrieved information could not be verified.', 'You can provide the document yourself.'],
    MANUAL_UPLOAD_REQUIRED: ['Automatic verification could not be completed.', 'You can provide the document yourself.'],
  },
  mr: {
    NO_RECORD: ['जोडलेल्या विभागांमध्ये पडताळलेली नोंद आढळली नाही.', 'आपण दस्तऐवज स्वतः देऊ शकता.'],
    TEMPORARILY_UNAVAILABLE: ['शासकीय पडताळणी तात्पुरती उपलब्ध नाही.', 'आपला अर्ज जतन आहे. थोड्या वेळाने पुन्हा प्रयत्न करा किंवा दस्तऐवज स्वतः द्या.'],
    TIMEOUT: ['शासकीय विभागाने प्रतिसाद देण्यास खूप वेळ घेतला.', 'थोड्या वेळाने पुन्हा प्रयत्न करा किंवा दस्तऐवज स्वतः द्या.'],
    LOW_CONFIDENCE: ['ही नोंद पुरेशा खात्रीने पडताळता आली नाही.', 'आपल्या माहितीच्या सुरक्षिततेसाठी ती जोडली नाही. आपण दस्तऐवज स्वतः देऊ शकता.'],
    AMBIGUOUS_MATCH: ['आपल्या तपशिलांशी एकापेक्षा जास्त नोंदी जुळल्या.', 'आपल्या माहितीच्या सुरक्षिततेसाठी कोणतीही जोडली नाही. आपण दस्तऐवज स्वतः देऊ शकता.'],
    UNAUTHORIZED: ['या नोंदीसाठी स्वयंचलित पुनर्प्राप्ती अधिकृत नाही.', 'आपण दस्तऐवज स्वतः देऊ शकता.'],
    CONSENT_DENIED: ['आपण स्वयंचलित पुनर्प्राप्तीस अनुमती दिली नाही.', 'आपण कधीही ऑटो-फिलला अनुमती देऊ शकता किंवा दस्तऐवज स्वतः देऊ शकता.'],
    VERIFICATION_FAILED: ['मिळालेली माहिती पडताळता आली नाही.', 'आपण दस्तऐवज स्वतः देऊ शकता.'],
    MANUAL_UPLOAD_REQUIRED: ['स्वयंचलित पडताळणी पूर्ण होऊ शकली नाही.', 'आपण दस्तऐवज स्वतः देऊ शकता.'],
  },
};
const STATE_ICON = {
  NO_RECORD: SearchX, TEMPORARILY_UNAVAILABLE: CloudOff, TIMEOUT: CloudOff, LOW_CONFIDENCE: ShieldAlert, AMBIGUOUS_MATCH: ShieldAlert,
  UNAUTHORIZED: ShieldAlert, CONSENT_DENIED: CircleAlert, VERIFICATION_FAILED: CircleAlert, MANUAL_UPLOAD_REQUIRED: CircleAlert,
};
// States where asking the departments again is the natural next step.
const RETRY_FIRST = new Set(['TEMPORARILY_UNAVAILABLE', 'TIMEOUT']);

// Older payloads (and officer views) may not carry verificationState yet.
function stateOf(requirement) {
  if (requirement.verificationState) return requirement.verificationState;
  if (SATISFIED.has(requirement.status)) return requirement.documentId ? 'UPLOADED' : 'VERIFIED';
  if (requirement.status === 'WAITING') return 'TEMPORARILY_UNAVAILABLE';
  if (NEEDS_ATTENTION_STATUSES.has(requirement.status)) return 'MANUAL_UPLOAD_REQUIRED';
  return 'NOT_STARTED';
}

function StatusBadge({ status, language }) {
  const statusClass = requirementStateClass(status);
  const Icon = SATISFIED.has(status) ? BadgeCheck : NEEDS_ATTENTION_STATUSES.has(status) ? CircleAlert : null;
  return (
    <span className={`status ${statusClass}`}>
      {Icon && <Icon size={14} aria-hidden="true" />}{requirementStateLabel(status, language)}
    </span>
  );
}

function RequirementCard({ requirement, applicationId, language, onChange, locked }) {
  const [uploadSource, setUploadSource] = useState(null); // null | 'choose' | 'device' | 'camera'
  const uploadOpen = uploadSource !== null;
  const [consentOpen, setConsentOpen] = useState(false);
  const [busy, setBusy] = useState(null); // 'auto-fill' | 'view' | 'download' | 'remove' | null
  const [error, setError] = useState(null);
  const [viewedDocument, setViewedDocument] = useState(null);
  const isMr = language === 'mr';
  const toast = useToast();

  const closeConsent = useCallback(() => setConsentOpen(false), []);
  const closeUpload = useCallback(() => setUploadSource(null), []);
  const closeViewedDocument = useCallback(() => {
    setViewedDocument(current => {
      if (current?.url) URL.revokeObjectURL(current.url);
      return null;
    });
  }, []);
  const consentRef = useDismiss(consentOpen, closeConsent);
  const viewedDocumentRef = useDismiss(Boolean(viewedDocument), closeViewedDocument);

  const documentLike = isDocumentLike(requirement);
  const satisfied = SATISFIED.has(requirement.status);
  const state = stateOf(requirement);
  // Upload is offered only where the backend accepts it (documents,
  // certificates and department records -- never an identity attribute).
  const canUpload = requirement.canUpload ?? documentLike;
  const hasViewableDocument = (documentLike && requirement.status === 'VALIDATED') || Boolean(requirement.documentId);
  // Only the citizen's own upload carries a documentId on the requirement --
  // a provider-verified document can be replaced by an upload, never removed.
  const hasCitizenUpload = hasViewableDocument && Boolean(requirement.documentId);
  const needsAttention = NEEDS_ATTENTION_STATUSES.has(requirement.status);
  const isRetry = needsAttention; // same action, different button copy
  const problem = STATE_COPY.en[state] ? state : null;
  const retryFirst = RETRY_FIRST.has(state) || (problem && !canUpload);
  const label = isMr ? (requirement.displayLabelMr || requirement.displayLabel) : requirement.displayLabel;
  const when = verifiedWhen(requirement.verifiedAt, language);

  async function handleViewDocument() {
    setBusy('view');
    setError(null);
    try {
      const doc = await api.viewDocument(applicationId, requirement.requirementCode);
      if (doc.isFile) {
        // An uploaded image/PDF: preview the original file itself.
        const { blob } = await api.downloadDocument(applicationId, requirement.requirementCode);
        setViewedDocument({ ...doc, url: URL.createObjectURL(blob) });
      } else {
        setViewedDocument(doc);
      }
    } catch (err) {
      setError(err.message || (isMr ? 'दस्तऐवज उघडता आले नाही.' : 'The document could not be opened.'));
    } finally {
      setBusy(null);
    }
  }

  async function handleDownloadDocument() {
    setBusy('download');
    setError(null);
    try {
      const { blob, filename } = await api.downloadDocument(applicationId, requirement.requirementCode);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message || (isMr ? 'दस्तऐवज डाउनलोड करता आले नाही.' : 'The document could not be downloaded.'));
    } finally {
      setBusy(null);
    }
  }

  // Auto-Fill never retrieves anything until the citizen explicitly accepts
  // this per-requirement consent prompt -- wording is deliberately generic
  // and never names a department, provider, API or document source. A
  // retry goes through this exact same consent-gated call -- consent is
  // never skipped just because a prior attempt already happened.
  async function handleAutoFillDecision(decision) {
    setConsentOpen(false);
    setBusy('auto-fill');
    setError(null);
    try {
      const updated = await api.autoFillRequirement(applicationId, requirement.requirementCode, decision);
      onChange(updated);
      const latest = (updated?.requirements || []).find(item => item.requirementCode === requirement.requirementCode);
      if (decision === 'ACCEPT' && latest && SATISFIED.has(latest.status) && latest.source) {
        toast({ tone: 'success', title: isMr ? 'पडताळणी झाली' : 'Verified',
          message: latest.verificationState === 'VERIFIED_VIA_FALLBACK'
            ? (isMr ? 'पर्यायी शासकीय स्रोताद्वारे' : `${label} — through an alternate government source`)
            : (isMr ? `${label} — ${latest.sourceMr || latest.source}` : `${label} — from ${latest.source}`) });
      }
    } catch (err) {
      setError(err.message || (isMr ? 'ऑटो-फिल सुरू करता आले नाही.' : 'Auto-Fill could not be started.'));
      // A timed-out Auto-Fill may still have completed: show the real state,
      // and drop the message if it turns out it did.
      if (err.outcomeUnknown) {
        api.application(applicationId).then(current => {
          onChange(current);
          const latest = (current?.requirements || []).find(item => item.requirementCode === requirement.requirementCode);
          if (latest && SATISFIED.has(latest.status)) setError(null);
        }).catch(() => {});
      }
    } finally {
      setBusy(null);
    }
  }

  async function handleRemoveUpload() {
    setBusy('remove');
    setError(null);
    try {
      closeViewedDocument();
      onChange(await api.removeUpload(applicationId, requirement.requirementCode));
    } catch (err) {
      setError(err.message || (isMr ? 'अपलोड काढता आले नाही.' : 'The upload could not be removed.'));
    } finally {
      setBusy(null);
    }
  }

  const Icon = documentLike ? FileText : IdCard;
  return (
    <article className={`card requirement-card${satisfied ? ' is-verified' : ''}${needsAttention ? ' needs-attention' : ''}`}>
      <div className="requirement-card-heading">
        <span className="requirement-type-icon" aria-hidden="true"><Icon size={20} /></span>
        <div className="requirement-card-title">
          <h3>{label}</h3>
          <span className={`requirement-flag ${requirement.mandatory === false ? 'optional' : 'required'}`}>
            {requirement.mandatory === false ? (isMr ? 'ऐच्छिक' : 'Optional') : (isMr ? 'आवश्यक' : 'Required')}
          </span>
        </div>
        <StatusBadge status={requirement.status} language={language} />
      </div>

      {satisfied && (
        <div className="verified-line">
          <ShieldCheck size={16} aria-hidden="true" />
          <span className="verified-kind">{state === 'UPLOADED'
            ? (isMr ? 'आपण अपलोड केले' : 'Uploaded by you')
            : (isMr ? 'विभागाच्या नोंदीतून ऑटो-फिल' : 'Auto-filled from department record')}</span>
          {state === 'VERIFIED' && requirement.source && (
            <span>· {isMr ? `${requirement.sourceMr || requirement.source} कडून पडताळले` : `Verified from ${requirement.source}`}</span>
          )}
          {state === 'VERIFIED_VIA_FALLBACK' && (
            <span>· {isMr ? 'पर्यायी शासकीय स्रोताद्वारे पडताळले' : 'Verified through an alternate government source'}
              {requirement.source && <> · {isMr ? 'स्रोत' : 'Source'}: {isMr ? (requirement.sourceMr || requirement.source) : requirement.source}</>}</span>
          )}
          {when && <span>· {isMr ? 'पडताळले' : 'Verified'}: {when}</span>}
        </div>
      )}

      {(busy === 'auto-fill' || state === 'CHECKING') && (
        <p className="progress-line" role="status"><LoaderCircle className="spin" size={16} aria-hidden="true" />
          {isMr ? 'जोडलेल्या शासकीय विभागांमध्ये तपासणी करत आहे…' : 'Checking connected government departments…'}</p>
      )}
      {error && <div className="alert danger" role="alert">{error}</div>}
      {/* Backend-persisted state, not local-only: it survives a refresh
          because it comes from requirement.verificationState. */}
      {problem && busy !== 'auto-fill' && (() => {
        const [headline, guidance] = (STATE_COPY[language] || STATE_COPY.en)[problem];
        const Icon = STATE_ICON[problem] || CircleAlert;
        return (
          <div className={`state-notice state-${problem.toLowerCase().replace(/_/g, '-')}`} role="note">
            <Icon size={18} aria-hidden="true" />
            <div><b>{headline}</b>
              <span>{canUpload ? guidance : (isMr ? 'कृपया थोड्या वेळाने पुन्हा प्रयत्न करा.' : 'Please try again in a little while.')}</span></div>
          </div>
        );
      })()}

      {consentOpen && !locked && (
        <div className="consent-prompt" ref={consentRef} role="group" aria-label={isMr ? 'संमती' : 'Consent'}>
          <p><ShieldCheck size={18} aria-hidden="true" />{isMr
            ? 'आपल्या अर्जासाठी ही माहिती पुनर्प्राप्त व पडताळण्याची SANGAM ला परवानगी द्यायची का?'
            : 'Allow SANGAM to retrieve and verify this information for your application?'}</p>
          <div className="actions">
            <button className="outline" onClick={() => handleAutoFillDecision('REJECT')}>{isMr ? 'नकार द्या' : 'Reject'}</button>
            <button className="primary" onClick={() => handleAutoFillDecision('ACCEPT')}>{isMr ? 'स्वीकारा' : 'Accept'}</button>
          </div>
        </div>
      )}

      {locked ? (
        <p className="muted">{isMr ? 'हा अर्ज सादर करण्यात आला आहे आणि तो आता बदलता येणार नाही.' : 'This application has been submitted and can no longer be changed.'}</p>
      ) : (
        <div className="requirement-actions">
          {!satisfied && (!problem || retryFirst || state === 'CONSENT_DENIED') && (
            <button className="autofill-button button-with-icon" disabled={busy !== null} onClick={() => setConsentOpen(true)}>
              {busy === 'auto-fill' ? <LoaderCircle className="spin" size={18} aria-hidden="true" />
                : isRetry ? <RefreshCw size={18} aria-hidden="true" /> : <Sparkles size={18} aria-hidden="true" />}
              {busy === 'auto-fill'
                ? (isMr ? 'तपासत आहे…' : 'Checking…')
                : isRetry ? (isMr ? 'पुन्हा प्रयत्न करा' : 'Retry') : (isMr ? 'पडताळलेली माहिती ऑटो-फिल करा' : 'Auto-Fill verified information')}
            </button>
          )}
          {canUpload && !satisfied && (
            <>
              <button className={`${problem && !retryFirst ? 'primary' : 'outline'} button-with-icon`} disabled={busy !== null}
                onClick={() => setUploadSource(current => current ? null : 'device')}>
                <Upload size={18} aria-hidden="true" />{isMr ? 'दस्तऐवज अपलोड करा' : 'Upload document'}
              </button>
              {problem && (
                <button className="outline button-with-icon" disabled={busy !== null} onClick={() => setUploadSource('camera')}>
                  <Camera size={18} aria-hidden="true" />{isMr ? 'फोटो काढा' : 'Take photo'}
                </button>
              )}
            </>
          )}
          {hasCitizenUpload && (
            <button className="outline button-with-icon" disabled={busy !== null} onClick={() => setUploadSource(current => current ? null : 'choose')}>
              <Replace size={18} aria-hidden="true" />{isMr ? 'बदला' : 'Replace'}
            </button>
          )}
          {hasViewableDocument && (
            <>
              <button className="outline button-with-icon" disabled={busy !== null} onClick={handleViewDocument}>
                {busy === 'view' ? <LoaderCircle className="spin" size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
                {busy === 'view' ? (isMr ? 'उघडत आहे…' : 'Opening…') : (isMr ? 'पहा' : 'View')}
              </button>
              <button className="outline button-with-icon" disabled={busy !== null} onClick={handleDownloadDocument}>
                {busy === 'download' ? <LoaderCircle className="spin" size={18} aria-hidden="true" /> : <Download size={18} aria-hidden="true" />}
                {busy === 'download' ? (isMr ? 'डाउनलोड होत आहे…' : 'Downloading…') : (isMr ? 'डाउनलोड करा' : 'Download')}
              </button>
            </>
          )}
          {hasCitizenUpload && (
            <button className="outline danger-text button-with-icon" disabled={busy !== null} onClick={handleRemoveUpload}>
              {busy === 'remove' ? <LoaderCircle className="spin" size={18} aria-hidden="true" /> : <Trash2 size={18} aria-hidden="true" />}
              {busy === 'remove' ? (isMr ? 'काढत आहे…' : 'Removing…') : (isMr ? 'काढून टाका' : 'Remove')}
            </button>
          )}
          {problem && !retryFirst && state !== 'CONSENT_DENIED' && (
            <button className="link" disabled={busy !== null} onClick={() => setConsentOpen(true)}>
              {isMr ? 'ऑटो-फिल पुन्हा करून पहा' : 'Try Auto-Fill again'}
            </button>
          )}
        </div>
      )}

      {locked && hasViewableDocument && (
        <div className="requirement-actions">
          <button className="outline button-with-icon" disabled={busy !== null} onClick={handleViewDocument}><Eye size={18} aria-hidden="true" />{isMr ? 'पहा' : 'View'}</button>
          <button className="outline button-with-icon" disabled={busy !== null} onClick={handleDownloadDocument}><Download size={18} aria-hidden="true" />{isMr ? 'डाउनलोड करा' : 'Download'}</button>
        </div>
      )}

      {viewedDocument && (
        <div className="document-preview" ref={viewedDocumentRef}>
          <div className="document-preview-heading">
            <b>{viewedDocument.title}</b>
            <button className="link" onClick={closeViewedDocument}>{isMr ? 'बंद करा' : 'Close'}</button>
          </div>
          {viewedDocument.isFile
            ? (viewedDocument.contentType === 'application/pdf'
              ? <iframe className="document-preview-frame" src={viewedDocument.url} title={viewedDocument.title} />
              : <img className="upload-preview-image" src={viewedDocument.url} alt={viewedDocument.title} />)
            : <pre>{viewedDocument.content}</pre>}
        </div>
      )}

      {canUpload && uploadOpen && !locked && (
        <DocumentUploader
          initialSource={uploadSource === 'device' || uploadSource === 'camera' ? uploadSource : null}
          applicationId={applicationId}
          requirementCode={requirement.requirementCode}
          title={label}
          language={language}
          replacing={hasCitizenUpload}
          onCancel={closeUpload}
          onUploaded={updated => { setUploadSource(null); closeViewedDocument(); onChange(updated); toast({ tone: 'success', title: isMr ? 'दस्तऐवज अपलोड झाला' : 'Document uploaded', message: label }); }}
        />
      )}
    </article>
  );
}

const STEPS = [
  { id: 'overview', en: 'Application overview', mr: 'अर्जाचा आढावा' },
  { id: 'personal', en: 'Personal information', mr: 'वैयक्तिक माहिती' },
  { id: 'verified', en: 'Eligibility & verified information', mr: 'पात्रता व पडताळलेली माहिती' },
  { id: 'documents', en: 'Required documents', mr: 'आवश्यक दस्तऐवज' },
  { id: 'additional', en: 'Additional information', mr: 'अतिरिक्त माहिती' },
  { id: 'review', en: 'Review', mr: 'पुनरावलोकन' },
  { id: 'submit', en: 'Submit', mr: 'सादर करा' },
];

export default function ApplicationFormPage({ schemeId, citizen, navigate, language = 'en' }) {
  const [application, setApplication] = useState(null);
  const [scheme, setScheme] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const isMr = language === 'mr';

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setApplication(null);
    if (!schemeId) {
      setLoading(false);
      setError(isMr ? 'कोणतीही योजना निवडलेली नाही.' : 'No scheme was selected.');
      return undefined;
    }
    Promise.all([api.applyToScheme(schemeId), api.service(schemeId)])
      .then(([applicationResult, schemeResult]) => {
        if (!active) return;
        setApplication(applicationResult);
        setScheme(schemeResult);
        setLoading(false);
      })
      .catch(err => {
        if (!active) return;
        setError(err.message || (isMr ? 'हा अर्ज सध्या उघडता आला नाही.' : 'Unable to open this application right now.'));
        setLoading(false);
      });
    return () => { active = false; };
  }, [schemeId, isMr]);

  function updateRequirement(updatedApplication) {
    setApplication(updatedApplication);
  }

  if (loading) {
    return <main className="container narrow"><p className="loading-state" role="status"><LoaderCircle className="spin" size={18} aria-hidden="true" /> {isMr ? 'अर्ज उघडत आहे…' : 'Opening application…'}</p></main>;
  }
  if (error || !application) {
    return (
      <main className="container narrow">
        <div className="alert danger" role="alert">{error || (isMr ? 'अर्ज लोड करता आला नाही.' : 'Application could not be loaded.')}</div>
        <button className="outline" onClick={() => navigate('schemes')}>{isMr ? 'योजनांकडे परत जा' : 'Back to schemes'}</button>
      </main>
    );
  }

  const schemeName = scheme ? (isMr ? (scheme.nameMr || scheme.name) : scheme.name) : application.schemeName;
  const requirements = application.requirements || [];
  const mandatory = requirements.filter(item => item.mandatory !== false);
  const information = mandatory.filter(item => !isDocumentLike(item));
  const documents = mandatory.filter(isDocumentLike);
  const optional = requirements.filter(item => item.mandatory === false);
  const done = requirements.filter(item => SATISFIED.has(item.status)).length;
  const percent = requirements.length ? Math.round((done / requirements.length) * 100) : 0;
  const locked = application.status === 'SUBMITTED';
  const image = schemeImage(scheme || { serviceId: application.serviceId }, language);
  const stepDone = {
    overview: true, personal: true,
    verified: information.every(item => SATISFIED.has(item.status)),
    documents: documents.every(item => SATISFIED.has(item.status)),
    additional: true, review: locked, submit: locked,
  };
  const cards = items => items.map(requirement => (
    <RequirementCard key={requirement.requirementCode} requirement={requirement} applicationId={application.appId}
      language={language} onChange={updateRequirement} locked={locked} />
  ));

  return (
    <main className="container application-form">
      <button className="link back-link button-with-icon" onClick={() => navigate('myApplications')}><ArrowLeft size={16} aria-hidden="true" />{isMr ? 'माझे अर्ज' : 'My applications'}</button>

      <nav className="stepper" aria-label={isMr ? 'अर्जाचे टप्पे' : 'Application steps'}>
        <ol>
          {STEPS.map((step, index) => (
            <li key={step.id} className={stepDone[step.id] ? 'done' : ''}>
              {index < 5
                ? <a href={`#step-${step.id}`}><span className="step-number">{index + 1}</span>{isMr ? step.mr : step.en}</a>
                : <span className="step-later"><span className="step-number">{index + 1}</span>{isMr ? step.mr : step.en}</span>}
            </li>
          ))}
        </ol>
      </nav>

      <section id="step-overview" className="card application-overview" aria-labelledby="application-title">
        <img className="overview-image" src={image.src} alt="" width="720" height="405" />
        <div className="overview-body">
          <p className="eyebrow">{isMr ? 'अर्ज' : 'Application'} · <code>{application.appId}</code></p>
          <h1 id="application-title">{schemeName}</h1>
          {scheme && <p className="muted">{isMr ? (scheme.departmentMr || scheme.department) : scheme.department} · {categoryLabel(scheme.category, language)}</p>}
          <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}
            aria-label={isMr ? 'पूर्ण झालेल्या बाबी' : 'Items completed'}>
            <span style={{ width: `${percent}%` }} />
          </div>
          <p className="progress-caption">{isMr ? `${requirements.length} पैकी ${done} बाबी पूर्ण` : `${done} of ${requirements.length} items complete`}</p>
        </div>
      </section>

      {application.verificationDelayed && !locked && (
        <div className="alert notice" role="status">
          {isMr
            ? 'आवश्यक पडताळण्यांपैकी एक सध्या उपलब्ध नसल्यामुळे आपल्या अर्जाला तात्पुरता विलंब होत आहे. आपला अर्ज जतन केला आहे; कृपया नंतर पुन्हा प्रयत्न करा.'
            : 'Some verifications are temporarily unavailable. Your application is saved — please try again later.'}
        </div>
      )}
      {locked && (
        <div className="alert success" role="status">{isMr ? 'हा अर्ज आधीच सादर करण्यात आला आहे.' : 'This application has already been submitted.'}</div>
      )}

      <section id="step-personal" className="card form-section">
        <h2><UserRound size={20} aria-hidden="true" />{isMr ? 'वैयक्तिक माहिती' : 'Personal information'}</h2>
        <dl className="field-grid">
          <div><dt>{isMr ? 'नाव' : 'Name'}</dt><dd>{citizen?.name}</dd></div>
          <div><dt>{isMr ? 'नागरिक क्रमांक' : 'Citizen ID'}</dt><dd>{citizen?.citizenId}</dd></div>
          {citizen?.dob && <div><dt>{isMr ? 'जन्मतारीख' : 'Date of birth'}</dt><dd>{citizen.dob}</dd></div>}
          {citizen?.phone && <div><dt>{isMr ? 'फोन' : 'Phone'}</dt><dd>{citizen.phone}</dd></div>}
          {citizen?.district && <div><dt>{isMr ? 'जिल्हा' : 'District'}</dt><dd>{citizen.district}</dd></div>}
          {citizen?.address && <div className="wide"><dt>{isMr ? 'पत्ता' : 'Address'}</dt><dd>{citizen.address}</dd></div>}
        </dl>
        <p className="muted small-text"><ShieldCheck size={14} aria-hidden="true" /> {isMr ? 'आपल्या SANGAM ओळख नोंदीवरून.' : 'From your SANGAM identity record.'}</p>
      </section>

      <section id="step-verified" className="form-section">
        <div className="section-intro">
          <h2><Sparkles size={20} aria-hidden="true" />{isMr ? 'पात्रता व पडताळलेली माहिती' : 'Eligibility & verified information'}</h2>
          <p className="muted">{isMr ? 'ही माहिती संबंधित विभागांकडून आपल्या संमतीनेच मिळवली जाते.' : 'Verified information from connected departments, used only with your consent.'}</p>
        </div>
        <div className="requirement-list">{cards(information)}</div>
        <EligibilityPanel assessment={application.eligibilityAssessment} language={language} />
      </section>

      <section id="step-documents" className="form-section">
        <div className="section-intro">
          <h2><FileText size={20} aria-hidden="true" />{isMr ? 'आवश्यक दस्तऐवज' : 'Required documents'}</h2>
          <p className="muted">{isMr ? 'विभागाकडून आपोआप मिळवा किंवा आपल्या डिव्हाइस/कॅमेऱ्याने अपलोड करा.' : 'Auto-Fill from the issuing department, or upload from your device or camera.'}</p>
        </div>
        <div className="requirement-list">{documents.length ? cards(documents) : <p className="muted">{isMr ? 'या योजनेसाठी दस्तऐवज आवश्यक नाहीत.' : 'No documents are required for this scheme.'}</p>}</div>
      </section>

      <section id="step-additional" className="form-section">
        <div className="section-intro">
          <h2>{isMr ? 'अतिरिक्त माहिती' : 'Additional information'}</h2>
        </div>
        {optional.length
          ? <div className="requirement-list">{cards(optional)}</div>
          : <p className="card muted plain-note">{isMr ? 'या योजनेसाठी इतर कोणतीही माहिती आवश्यक नाही.' : 'Nothing else is needed for this scheme.'}</p>}
      </section>

      <section className="card form-section continue-bar">
        <div>
          <h2>{isMr ? 'पुनरावलोकन व सादरीकरण' : 'Review & submit'}</h2>
          <p className="muted">{isMr ? 'सादर करण्यापूर्वी आपल्या अर्जाचे पुनरावलोकन करा.' : 'Review your application before submitting it.'}</p>
        </div>
        <div className="requirement-actions">
          <button className="outline button-with-icon" onClick={() => navigate('dashboard')}><Save size={18} aria-hidden="true" />{isMr ? 'जतन करा व नंतर सुरू ठेवा' : 'Save & continue later'}</button>
          <button className="primary button-with-icon" onClick={() => navigate('reviewApplication')}>{isMr ? 'पुनरावलोकनाकडे जा' : 'Continue to review'}<ArrowRight size={18} aria-hidden="true" /></button>
        </div>
      </section>
    </main>
  );
}
