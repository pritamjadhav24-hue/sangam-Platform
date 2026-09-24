import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminAnalyticsPage from './AdminAnalyticsPage';

const trend = (series, limited) => ({ series, limited });
const REPORT = {
  applications: { total: 3, submitted: 1, automaticallyVerified: 1, manuallyFulfilled: 1, citizenActionRequired: 1, officerReviewRequired: 0, retryInProgress: 0, processing: 0, appIds: ['APP-1', 'APP-2', 'APP-3'] },
  requirements: { total: 6, fulfilledAutomatically: 3, fulfilledManually: 1, pending: 1, actionRequired: 1, retrying: 0, failed: 0, fallbackUsed: 1,
    byRequirement: [{ requirementCode: 'INCOME_PROOF', total: 2, fulfilledAutomatically: 2, fallbackUsed: 1 }] },
  providers: { registered: 5, healthy: 4, down: 1, degraded: 0,
    jobs: { total: 4, byStatus: {}, retries: 2, deadLetter: 1, failed: 0 },
    incidents: { total: 1, open: 1, resolved: 0, byProvider: { 'Revenue Department': 1 } },
    replays: { total: 1, automaticRecovery: 1, manual: 0 }, fallbackUsed: 1 },
  trends: {
    applications: trend([{ date: '2026-09-22', count: 1 }, { date: '2026-09-23', count: 2 }], false),
    fulfillment: trend([{ date: '2026-09-23', count: 4 }], true),
    providerFailures: trend([], true),
    incidents: trend([], true),
    recovery: trend([], true),
  },
  providerNames: { 'REVENUE-DEPARTMENT': 'Revenue Department' },
};

function makeApi() {
  return {
    adminAnalytics: vi.fn().mockResolvedValue(REPORT),
    adminProviderRegistry: vi.fn().mockResolvedValue({ providers: [{ providerId: 'REVENUE-DEPARTMENT', name: 'Revenue Department' }] }),
  };
}

function renderPage(overrides = {}) {
  const props = { api: makeApi(), onNavigate: vi.fn(), onOpenProvider: vi.fn(), onOpenApplication: vi.fn(), ...overrides };
  render(<AdminAnalyticsPage {...props} />);
  return props;
}

describe('AdminAnalyticsPage', () => {
  it('renders application, requirement and provider figures from the backend report', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Application overview')).toBeInTheDocument());
    expect(screen.getByText('Requirement fulfillment')).toBeInTheDocument();
    expect(screen.getByText('Fulfilled via fallback provider')).toBeInTheDocument();
    expect(screen.getByText('Automatic recovery replays')).toBeInTheDocument();
    expect(screen.getByText('INCOME_PROOF')).toBeInTheDocument();
  });

  it('labels sparse trends as limited instead of drawing fabricated history', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Trends')).toBeInTheDocument());
    expect(screen.getAllByText(/Limited demo data available for this trend/).length).toBe(4);
    expect(screen.getByText('2026-09-22')).toBeInTheDocument();
  });

  it('sends filters to the backend API rather than filtering client-side', async () => {
    const props = renderPage();
    await waitFor(() => expect(props.api.adminAnalytics).toHaveBeenCalledTimes(1));
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText('Outcome'), 'automaticallyVerified');
    await user.selectOptions(screen.getByLabelText('Provider'), 'REVENUE-DEPARTMENT');
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(props.api.adminAnalytics).toHaveBeenCalledTimes(2));
    expect(props.api.adminAnalytics.mock.calls[1][0]).toMatchObject({ outcome: 'automaticallyVerified', provider: 'REVENUE-DEPARTMENT' });
  });

  it('drills down into applications, providers and alerts', async () => {
    const props = renderPage();
    await waitFor(() => expect(screen.getByText('APP-2')).toBeInTheDocument());
    const user = userEvent.setup();
    await user.click(screen.getByText('APP-2'));
    expect(props.onOpenApplication).toHaveBeenCalledWith('APP-2');
    await user.click(screen.getByText('Revenue Department: 1'));
    expect(props.onOpenProvider).toHaveBeenCalledWith('REVENUE-DEPARTMENT');
    await user.click(screen.getByText('Dead-letter jobs').closest('button'));
    expect(props.onNavigate).toHaveBeenCalledWith('adminAlerts');
  });

  it('shows an understandable error when the report fails', async () => {
    const api = { ...makeApi(), adminAnalytics: vi.fn().mockRejectedValue(new Error('Invalid date')) };
    renderPage({ api });
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Invalid date'));
  });
});
