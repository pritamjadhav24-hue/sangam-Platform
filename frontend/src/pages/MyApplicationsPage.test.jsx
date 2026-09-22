import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import MyApplicationsPage from './MyApplicationsPage';

const APPLICATION_A = {
  appId: 'APP-AAA', serviceId: 'SCH-A', schemeName: 'Post-Matric Scholarship', status: 'IN_PROGRESS',
  requirements: [{ requirementCode: 'IDENTITY', status: 'VALIDATED' }, { requirementCode: 'INCOME_PROOF', status: 'NOT_PROVIDED' }],
};
const APPLICATION_B = {
  appId: 'APP-BBB', serviceId: 'SCH-B', schemeName: 'Farmer Input Subsidy', status: 'SUBMITTED', submittedAt: '2026-01-05T00:00:00Z',
  requirements: [{ requirementCode: 'IDENTITY', status: 'VALIDATED' }],
};

describe('MyApplicationsPage', () => {
  it('shows a polished empty state with no fabricated applications when the citizen has none', () => {
    render(<MyApplicationsPage applications={[]} onOpenApplication={() => {}} navigate={() => {}} />);
    expect(screen.getByText(/haven't applied/i)).toBeInTheDocument();
  });

  it('lists every real persisted application with its own status', () => {
    render(<MyApplicationsPage applications={[APPLICATION_A, APPLICATION_B]} onOpenApplication={() => {}} navigate={() => {}} />);
    expect(screen.getByText('Post-Matric Scholarship')).toBeInTheDocument();
    expect(screen.getByText('Farmer Input Subsidy')).toBeInTheDocument();
    expect(screen.getByText('In progress')).toBeInTheDocument();
    expect(screen.getByText('Submitted')).toBeInTheDocument();
  });

  it('opening an application passes the exact real application object', async () => {
    const onOpenApplication = vi.fn();
    render(<MyApplicationsPage applications={[APPLICATION_A, APPLICATION_B]} onOpenApplication={onOpenApplication} navigate={() => {}} />);
    const user = userEvent.setup();
    const buttons = screen.getAllByRole('button', { name: 'Continue' });
    await user.click(buttons[0]);
    expect(onOpenApplication).toHaveBeenCalledWith(expect.objectContaining({ appId: 'APP-AAA' }));
  });

  it('never leaks provider/department/source details', () => {
    render(<MyApplicationsPage applications={[APPLICATION_A]} onOpenApplication={() => {}} navigate={() => {}} />);
    const pageText = document.body.textContent;
    for (const forbidden of ['DigiLocker', 'API Setu', 'adapter', 'providerId']) {
      expect(pageText).not.toContain(forbidden);
    }
  });
});
