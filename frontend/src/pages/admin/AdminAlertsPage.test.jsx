import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminAlertsPage from './AdminAlertsPage';

const INCIDENT = {
  incidentId: 'INC-1', providerSystem: 'Revenue Department', department: 'Revenue Department', status: 'OPEN',
  detectedAt: '2026-09-25T10:00:00+00:00', resolvedAt: null, errorCategory: 'UPSTREAM_UNAVAILABLE',
  affectedCitizens: 2, affectedApplications: 3, affectedSchemes: ['Post-Matric Higher Education Scholarship'],
  blockedOperations: 2, pendingRetries: 1, successfulFallbacks: 1, recoveredApplications: 0,
};

const IMPACT = {
  incidentId: 'INC-1', applications: [
    { appId: 'APP-1', citizenId: 'CIT-A', schemeName: 'Post-Matric Higher Education Scholarship', applicationStatus: 'IN_PROGRESS', blocked: true, recovered: false,
      blockedStage: 'Requirement verification: Income proof (waiting for retry)', jobs: [],
      requirements: [{ requirementCode: 'INCOME_PROOF', label: 'Income proof', state: 'RETRY_PENDING', stateLabel: 'Waiting for retry', resolvedBy: null }] },
    { appId: 'APP-3', citizenId: 'CIT-B', schemeName: 'Post-Matric Higher Education Scholarship', applicationStatus: 'IN_PROGRESS', blocked: false, recovered: false,
      blockedStage: null, jobs: [],
      requirements: [{ requirementCode: 'INCOME_PROOF', label: 'Income proof', state: 'FALLBACK_SUCCEEDED', stateLabel: 'Served by a fallback provider', resolvedBy: 'Revenue Sandbox API' }] },
  ],
};

function makeApi() {
  return {
    adminIncidents: vi.fn().mockResolvedValue({ incidents: [INCIDENT] }),
    adminIncidentImpact: vi.fn().mockResolvedValue(IMPACT),
    adminDeadLetterJobs: vi.fn().mockResolvedValue({ jobs: [] }),
    adminSchemaMappingReviews: vi.fn().mockResolvedValue({ reviews: [] }),
    adminOverview: vi.fn().mockResolvedValue({ exceptions: {} }),
  };
}

describe('AdminAlertsPage incident impact', () => {
  it('shows every impact count for an incident', async () => {
    render(<AdminAlertsPage api={makeApi()} onNavigateToApplication={() => {}} />);
    const counts = await screen.findByLabelText('Incident impact');
    for (const text of ['affected citizens', 'affected applications', 'affected scheme', 'blocked operations', 'pending retry', 'successful fallback', 'recovered applications']) {
      expect(within(counts).getByText(new RegExp(text))).toBeInTheDocument();
    }
    expect(counts).toHaveTextContent('2 affected citizens');
    expect(counts).toHaveTextContent('3 affected applications');
    expect(counts).toHaveTextContent('1 successful fallback');
    expect(screen.getByText(/Schemes: Post-Matric Higher Education Scholarship/)).toBeInTheDocument();
  });

  it('lists affected applications with the blocked scheme stage and opens an application', async () => {
    const api = makeApi();
    const onNavigate = vi.fn();
    render(<AdminAlertsPage api={api} onNavigateToApplication={onNavigate} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'View affected applications' }));
    expect(api.adminIncidentImpact).toHaveBeenCalledWith('INC-1');
    expect(await screen.findByText('Requirement verification: Income proof (waiting for retry)')).toBeInTheDocument();
    expect(screen.getByText(/Served by a fallback provider — Revenue Sandbox API/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'APP-1' }));
    expect(onNavigate).toHaveBeenCalledWith('APP-1');
  });
});
