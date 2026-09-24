import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminProvidersPage from './AdminProvidersPage';

const REGISTRY = [
  {
    providerId: 'REVENUE-DEPARTMENT', name: 'Revenue Department', department: 'Revenue Department',
    adapterType: 'REST API', environment: 'SANDBOX', authType: 'NONE', active: true,
    health: { status: 'AVAILABLE', lastSuccessAt: null, lastFailureAt: null, errorCategory: null },
    capabilities: [{ requirementCode: 'INCOME_PROOF', priority: 10, serviceId: 'SVC-1', serviceName: 'Income Certificate' }],
    supportedRequirements: ['INCOME_PROOF'], activeIncident: null, successCount: 3, failureCount: 0,
  },
  {
    providerId: 'EDUCATION-DEPARTMENT', name: 'Education Department', department: 'Education Department',
    adapterType: 'CSV/File Adapter', environment: 'SANDBOX', authType: 'NONE', active: true,
    health: { status: 'UNAVAILABLE', lastSuccessAt: null, lastFailureAt: null, errorCategory: 'UPSTREAM_UNAVAILABLE' },
    capabilities: [{ requirementCode: 'ACADEMIC_RECORD', priority: 10, serviceId: 'SVC-2', serviceName: 'Academic Verification' }],
    supportedRequirements: ['ACADEMIC_RECORD'],
    activeIncident: { incidentId: 'INC-1', detectedAt: '2026-09-24T00:00:00Z' },
    successCount: 0, failureCount: 2,
  },
];

function makeApi(overrides = {}) {
  return {
    adminProviderRegistry: vi.fn().mockResolvedValue({ providers: REGISTRY }),
    integrationHealth: vi.fn().mockResolvedValue({ integrations: [{ system: 'Revenue Department', status: 'AVAILABLE' }] }),
    adminSimulateHealth: vi.fn().mockResolvedValue({ status: 'AVAILABLE' }),
    ...overrides,
  };
}

describe('AdminProvidersPage (Provider / Integration Registry)', () => {
  it('renders every provider from the real registry response, not fabricated data', async () => {
    render(<AdminProvidersPage api={makeApi()} onOpenProvider={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('Revenue Department')).toBeInTheDocument());
    expect(screen.getByText('Education Department')).toBeInTheDocument();
    expect(screen.getAllByText('INCOME_PROOF').length).toBeGreaterThan(0);
    expect(screen.getAllByText('ACADEMIC_RECORD').length).toBeGreaterThan(0);
  });

  it('shows an active-incident indicator only for the provider that actually has one', async () => {
    render(<AdminProvidersPage api={makeApi()} onOpenProvider={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('Education Department')).toBeInTheDocument());
    const rows = screen.getAllByRole('row');
    const eduRow = rows.find(r => r.textContent.includes('Education Department'));
    const revRow = rows.find(r => r.textContent.includes('Revenue Department'));
    expect(eduRow.textContent).toContain('DOWN');
    expect(revRow.textContent).not.toContain('DOWN');
  });

  it('clicking "View Detail" calls onOpenProvider with the correct providerId', async () => {
    const onOpenProvider = vi.fn();
    render(<AdminProvidersPage api={makeApi()} onOpenProvider={onOpenProvider} />);
    await waitFor(() => expect(screen.getByText('Revenue Department')).toBeInTheDocument());
    const user = userEvent.setup();
    const buttons = screen.getAllByRole('button', { name: /View Detail/ });
    await user.click(buttons[0]);
    expect(onOpenProvider).toHaveBeenCalledWith('REVENUE-DEPARTMENT');
  });

  it('builds the capability matrix from the same registry data (no second selection source)', async () => {
    render(<AdminProvidersPage api={makeApi()} onOpenProvider={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('Provider ↔ Requirement Capability Matrix')).toBeInTheDocument());
    expect(screen.getAllByText(/Revenue Department \(P10\)/).length).toBeGreaterThan(0);
  });
});
