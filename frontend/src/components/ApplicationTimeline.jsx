import { applicationTimelineSteps } from '../applicationState';

export default function ApplicationTimeline({ application, language = 'en' }) {
  const steps = applicationTimelineSteps(application, language);
  return (
    <div className="app-timeline" role="list" aria-label={language === 'en' ? 'Application progress' : 'अर्जाची प्रगती'}>
      {steps.map((step, index) => (
        <div className={`app-timeline-step${step.done ? ' done' : ''}${step.current ? ' current' : ''}`} role="listitem" key={step.label}>
          <span className="app-timeline-dot" aria-hidden="true">{step.done ? '✓' : index + 1}</span>
          <span>{step.label}</span>
        </div>
      ))}
    </div>
  );
}
