// Shared citizen-facing APPLICATION status labels (distinct from
// requirementState.js, which covers per-requirement status). Maps every
// backend CANONICAL_STATUSES value (workflow_engine.py) to simple citizen
// language -- never invents a status the backend doesn't have. Today only
// IN_PROGRESS and SUBMITTED are actually reachable for a citizen-created
// application (officer actions on these applications are a future phase),
// but every backend status is covered so this never silently falls back to
// a raw backend code if that changes.
export const APPLICATION_STATE_LABELS = {
  en: {
    DRAFT: 'Application started', IN_PROGRESS: 'Information being collected',
    WAITING_FOR_DEPENDENCY: 'Information being collected', WAITING_FOR_USER: 'Information being collected',
    SUBMITTED: 'Submitted', WAITING_FOR_OFFICER: 'Application is being processed',
    VERIFICATION_FAILED: 'Application is being reviewed', CONFLICT_DETECTED: 'Application is being reviewed',
    APPROVED: 'Approved', REJECTED: 'Not approved', COMPLETED: 'Completed', CANCELLED: 'Cancelled',
  },
  mr: {
    DRAFT: 'अर्ज सुरू केला', IN_PROGRESS: 'माहिती गोळा करत आहे',
    WAITING_FOR_DEPENDENCY: 'माहिती गोळा करत आहे', WAITING_FOR_USER: 'माहिती गोळा करत आहे',
    SUBMITTED: 'सादर केले', WAITING_FOR_OFFICER: 'अर्जावर प्रक्रिया सुरू आहे',
    VERIFICATION_FAILED: 'अर्जाचे पुनरावलोकन सुरू आहे', CONFLICT_DETECTED: 'अर्जाचे पुनरावलोकन सुरू आहे',
    APPROVED: 'मंजूर', REJECTED: 'नामंजूर', COMPLETED: 'पूर्ण झाले', CANCELLED: 'रद्द केले',
  },
};

export const APPLICATION_STATE_CLASS = {
  DRAFT: 'pending', IN_PROGRESS: 'pending', WAITING_FOR_DEPENDENCY: 'pending', WAITING_FOR_USER: 'pending',
  SUBMITTED: 'found', WAITING_FOR_OFFICER: 'pending', VERIFICATION_FAILED: 'exception', CONFLICT_DETECTED: 'exception',
  APPROVED: 'found', REJECTED: 'exception', COMPLETED: 'found', CANCELLED: 'exception',
};

export function applicationStateLabel(status, language) {
  const labels = APPLICATION_STATE_LABELS[language] || APPLICATION_STATE_LABELS.en;
  return labels[status] || status;
}

export function applicationStateClass(status) {
  return APPLICATION_STATE_CLASS[status] || 'pending';
}

// The simple citizen-facing progress timeline (Task F). Each application's
// actual position on it is derived from real, already-persisted fields --
// never fabricated -- via applicationTimelineSteps() below.
export const TIMELINE_STEPS = {
  en: ['Application started', 'Information collected', 'Submitted', 'Under processing', 'Completed'],
  mr: ['अर्ज सुरू केला', 'माहिती गोळा केली', 'सादर केले', 'प्रक्रिया सुरू', 'पूर्ण झाले'],
};

const TERMINAL_PROCESSED_STATUSES = new Set(['APPROVED', 'REJECTED', 'COMPLETED']);

// Returns { steps: [{ label, done, current }], } -- a straight line, no
// invented branching -- reflecting only what the backend has actually
// recorded: whether requirements are satisfied (informationCollected) and
// whether/when the application was submitted (application.submittedAt),
// plus whether it has reached a real backend terminal status.
export function applicationTimelineSteps(application, language) {
  const labels = TIMELINE_STEPS[language] || TIMELINE_STEPS.en;
  const requirements = application?.requirements || [];
  const total = requirements.length;
  const satisfied = requirements.filter(item => item.status === 'VALIDATED' || item.status === 'RETRIEVED').length;
  const informationCollected = total > 0 && satisfied === total;
  const submitted = Boolean(application?.submittedAt) || application?.status === 'SUBMITTED';
  const processed = submitted && (TERMINAL_PROCESSED_STATUSES.has(application?.status) || application?.status === 'WAITING_FOR_OFFICER');
  const completed = application?.status === 'COMPLETED' || application?.status === 'APPROVED';

  const reached = [true, informationCollected || submitted, submitted, processed, completed];
  return labels.map((label, index) => ({
    label,
    done: reached[index],
    current: reached[index] && !reached[index + 1],
  }));
}
