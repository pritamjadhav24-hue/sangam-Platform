import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import CitizenDashboard from './CitizenDashboard';

const CITIZEN_A = { citizenId: 'SYN-CIT-00001', name: 'Amit Kale', dob: '1991-11-16', persona: 'JOBSEEKER' };
const CITIZEN_B = { citizenId: 'SYN-CIT-00002', name: 'Neha Kale', dob: '1965-03-12', persona: 'FARMER' };

const SCHEMES = [
  { serviceId: 'SCH-A', name: 'Post-Matric Scholarship', category: 'Education', description: 'Financial assistance for students.', department: 'Higher Education Department', enabled: true },
  { serviceId: 'SCH-B', name: 'Farmer Input Subsidy', category: 'Agriculture', description: 'Support for farmers.', department: 'Agriculture Department', enabled: true },
];

function application(overrides) {
  return {
    appId: 'APP-001', serviceId: 'SCH-A', schemeName: 'Post-Matric Scholarship', status: 'IN_PROGRESS',
    requirements: [
      { requirementCode: 'IDENTITY', displayLabel: 'Identity', status: 'VALIDATED' },
      { requirementCode: 'INCOME_PROOF', displayLabel: 'Income proof', status: 'NOT_PROVIDED' },
    ],
    ...overrides,
  };
}

describe('CitizenDashboard', () => {
  it('greets the real authenticated citizen by name -- not a hardcoded name', () => {
    render(<CitizenDashboard schemes={SCHEMES} applications={[]} citizen={CITIZEN_A} navigate={() => {}} onViewScheme={() => {}} />);
    expect(screen.getByText(/Amit/)).toBeInTheDocument();
    expect(screen.queryByText(/Rahul/)).not.toBeInTheDocument();
  });

  it('a different citizen produces a different greeting from the same component', () => {
    const { unmount } = render(<CitizenDashboard schemes={SCHEMES} applications={[]} citizen={CITIZEN_A} navigate={() => {}} onViewScheme={() => {}} />);
    expect(screen.getByText(/Amit/)).toBeInTheDocument();
    unmount();
    render(<CitizenDashboard schemes={SCHEMES} applications={[]} citizen={CITIZEN_B} navigate={() => {}} onViewScheme={() => {}} />);
    expect(screen.getByText(/Neha/)).toBeInTheDocument();
    expect(screen.queryByText(/Amit/)).not.toBeInTheDocument();
  });

  it('shows a polished empty state when the citizen has no applications, never a fabricated one', () => {
    render(<CitizenDashboard schemes={SCHEMES} applications={[]} citizen={CITIZEN_A} navigate={() => {}} onViewScheme={() => {}} />);
    expect(screen.getByText(/haven't applied/i)).toBeInTheDocument();
    expect(screen.queryByText('APP-001')).not.toBeInTheDocument();
  });

  it('renders real application data when present: scheme name, status, requirement progress', () => {
    render(<CitizenDashboard schemes={SCHEMES} applications={[application()]} citizen={CITIZEN_A} navigate={() => {}} onViewScheme={() => {}} />);
    const yourApplications = screen.getByText('Your Applications').closest('section');
    expect(within(yourApplications).getByText('Post-Matric Scholarship')).toBeInTheDocument();
    expect(within(yourApplications).getByText('In progress')).toBeInTheDocument();
    expect(within(yourApplications).getByText('1/2 requirements verified')).toBeInTheDocument();
  });

  it('the application overview counts are derived from the real applications array, never invented', () => {
    const apps = [application({ appId: 'A1', status: 'IN_PROGRESS' }), application({ appId: 'A2', status: 'SUBMITTED', submittedAt: '2026-01-01T00:00:00Z' })];
    render(<CitizenDashboard schemes={SCHEMES} applications={apps} citizen={CITIZEN_A} navigate={() => {}} onViewScheme={() => {}} />);
    const summarySection = screen.getByLabelText('Application overview');
    expect(summarySection.textContent).toContain('1'); // one active
  });

  it('shows an Action Required section only when a requirement actually needs attention', () => {
    const { rerender } = render(<CitizenDashboard schemes={SCHEMES} applications={[application()]} citizen={CITIZEN_A} navigate={() => {}} onViewScheme={() => {}} />);
    expect(screen.queryByText('Action Required')).not.toBeInTheDocument(); // NOT_PROVIDED alone doesn't count
    const withFailure = application({ requirements: [{ requirementCode: 'INCOME_PROOF', displayLabel: 'Income proof', status: 'FAILED' }] });
    rerender(<CitizenDashboard schemes={SCHEMES} applications={[withFailure]} citizen={CITIZEN_A} navigate={() => {}} onViewScheme={() => {}} />);
    expect(screen.getByText('Action Required')).toBeInTheDocument();
    expect(screen.getByText('Income proof')).toBeInTheDocument();
  });

  it('clicking a resolve/continue action calls onOpenApplication with the real application, not a hardcoded id', async () => {
    const onOpenApplication = vi.fn();
    render(<CitizenDashboard schemes={SCHEMES} applications={[application()]} citizen={CITIZEN_A} navigate={() => {}} onViewScheme={() => {}} onOpenApplication={onOpenApplication} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    expect(onOpenApplication).toHaveBeenCalledWith(expect.objectContaining({ appId: 'APP-001' }));
  });

  it('an already-applied scheme shows an applied badge in Explore Government Schemes, sourced from real applications', () => {
    render(<CitizenDashboard schemes={SCHEMES} applications={[application()]} citizen={CITIZEN_A} navigate={() => {}} onViewScheme={() => {}} />);
    const exploreSection = screen.getByText('Explore Government Schemes').closest('section');
    const schemeHeading = within(exploreSection).getByRole('heading', { name: 'Post-Matric Scholarship', level: 3 });
    const card = schemeHeading.closest('article');
    expect(card.textContent).toMatch(/already applied/i);
  });

  it('never leaks provider/department/source details', () => {
    render(<CitizenDashboard schemes={SCHEMES} applications={[application()]} citizen={CITIZEN_A} navigate={() => {}} onViewScheme={() => {}} />);
    const pageText = document.body.textContent;
    for (const forbidden of ['DigiLocker', 'API Setu', 'adapter', 'providerId']) {
      expect(pageText).not.toContain(forbidden);
    }
  });
});
