import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminProviderDetailPage from './AdminProviderDetailPage';

const DETAIL = {
  providerId: 'REVENUE-DEPARTMENT', name: 'Revenue Department', department: 'Revenue Department',
  adapterType: 'REST API', contractVersion: 'v1', environment: 'SANDBOX', authType: 'NONE',
  endpointRef: null, active: true, timeoutSeconds: 5, maxAttempts: 3,
  health: { status: 'AVAILABLE', lastCheckedAt: '2026-09-24T00:00:00Z', lastSuccessAt: '2026-09-24T00:00:00Z', lastFailureAt: null, errorCategory: null },
  capabilities: [{ requirementCode: 'INCOME_PROOF', priority: 10, serviceId: 'SVC-1', serviceName: 'Income Certificate', healthStatus: 'AVAILABLE' }],
  schemaMappings: [{ departmentField: 'annual_income', canonicalField: 'incomeAmount', dataType: 'number', serviceId: 'SVC-1' }],
  reliability: { successCount: 5, failureCount: 1, recentJobs: [{ jobId: 'JOB-abcdef1234567890', type: 'retrieve', applicationId: 'APP-1', status: 'COMPLETED', createdAt: '2026-09-24T00:00:00Z' }] },
  incidents: [{ incidentId: 'INC-1', status: 'RESOLVED', detectedAt: '2026-09-24T00:00:00Z', resolvedAt: '2026-09-24T00:05:00Z' }],
  auditEvents: [{ sequence: 1, who: 'SYSTEM', action: 'SELECT', why: 'Primary provider selected for requirement', when: '2026-09-24T00:00:00Z' }],
};

function makeApi(overrides = {}) {
  return { adminProviderDetail: vi.fn().mockResolvedValue(DETAIL), ...overrides };
}

describe('AdminProviderDetailPage', () => {
  it('renders overview, capabilities, schema mappings, reliability, incidents and audit events from real data', async () => {
    render(<AdminProviderDetailPage providerId="REVENUE-DEPARTMENT" api={makeApi()} onBack={vi.fn()} onNavigateToApplication={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('Revenue Department')).toBeInTheDocument());
    expect(screen.getByText('INCOME_PROOF')).toBeInTheDocument();
    expect(screen.getByText('annual_income')).toBeInTheDocument();
    expect(screen.getByText('incomeAmount')).toBeInTheDocument();
    expect(screen.getByText('RESOLVED')).toBeInTheDocument();
    expect(screen.getByText('Primary provider selected for requirement')).toBeInTheDocument();
  });

  it('shows an error state when the provider is not found, never a blank crash', async () => {
    const api = { adminProviderDetail: vi.fn().mockRejectedValue(new Error('Provider not found.')) };
    render(<AdminProviderDetailPage providerId="NONEXISTENT" api={api} onBack={vi.fn()} onNavigateToApplication={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Provider not found.'));
  });

  it('clicking a recent job\'s application id navigates to the application detail', async () => {
    const onNavigateToApplication = vi.fn();
    render(<AdminProviderDetailPage providerId="REVENUE-DEPARTMENT" api={makeApi()} onBack={vi.fn()} onNavigateToApplication={onNavigateToApplication} />);
    await waitFor(() => expect(screen.getByText('APP-1')).toBeInTheDocument());
    const user = userEvent.setup();
    await user.click(screen.getByText('APP-1'));
    expect(onNavigateToApplication).toHaveBeenCalledWith('APP-1');
  });

  it('the back button returns to the provider registry', async () => {
    const onBack = vi.fn();
    render(<AdminProviderDetailPage providerId="REVENUE-DEPARTMENT" api={makeApi()} onBack={onBack} onNavigateToApplication={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('Revenue Department')).toBeInTheDocument());
    const user = userEvent.setup();
    await user.click(screen.getByText('← Back to Providers'));
    expect(onBack).toHaveBeenCalled();
  });
});
