// Shared citizen-facing requirement status labels/classes, used by both
// ApplicationFormPage and ReviewApplicationPage so the two pages never
// drift into showing different wording for the same backend status.
//
// RETRIEVED (non-document requirements) and VALIDATED (document/certificate
// requirements) are kept as distinct persisted statuses -- they still gate
// different behaviour (document lifecycle) -- but both represent the same
// citizen-facing outcome ("this was successfully verified, no action
// needed"), so they share one label rather than exposing an internal
// document-vs-record distinction the citizen has no reason to care about.
export const STATE_LABELS = {
  en: {
    NOT_PROVIDED: 'Not provided', PROCESSING: 'Processing', RETRIEVED: 'Verified', VALIDATED: 'Verified',
    WAITING: 'Waiting', ACTION_REQUIRED: 'Action required', REJECTED: 'Rejected', FAILED: 'Failed',
  },
  mr: {
    NOT_PROVIDED: 'दिलेले नाही', PROCESSING: 'प्रक्रिया सुरू', RETRIEVED: 'पडताळणी झाली', VALIDATED: 'पडताळणी झाली',
    WAITING: 'प्रतीक्षेत', ACTION_REQUIRED: 'कृती आवश्यक', REJECTED: 'नाकारले', FAILED: 'अयशस्वी',
  },
};

export const STATE_CLASS = {
  NOT_PROVIDED: 'missing', PROCESSING: 'pending', RETRIEVED: 'found', VALIDATED: 'found',
  WAITING: 'pending', ACTION_REQUIRED: 'exception', REJECTED: 'exception', FAILED: 'exception',
};

// Statuses that mean a prior Auto-Fill attempt did not (yet) succeed.
export const NEEDS_ATTENTION_STATUSES = new Set(['WAITING', 'ACTION_REQUIRED', 'REJECTED', 'FAILED']);

export function requirementStateLabel(status, language) {
  const labels = STATE_LABELS[language] || STATE_LABELS.en;
  return labels[status] || status;
}

export function requirementStateClass(status) {
  return STATE_CLASS[status] || 'missing';
}

// Purely decorative (aria-hidden) glyphs for the requirement card icon slot
// -- never the only way status is communicated, since requirementStateLabel
// already renders the real status as text.
const STATE_ICON = {
  NOT_PROVIDED: '○', PROCESSING: '⟳', RETRIEVED: '✓', VALIDATED: '✓',
  WAITING: '⟳', ACTION_REQUIRED: '!', REJECTED: '!', FAILED: '!',
};

export function requirementStateIcon(status) {
  return STATE_ICON[status] || '○';
}
