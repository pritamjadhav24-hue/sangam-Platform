import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import AdminApplicationDetailPage from './AdminApplicationDetailPage';

const DETAIL = {
  appId: 'APP-1', citizenId: 'CIT-A', status: 'IN_PROGRESS', schemeName: 'Post-Matric Higher Education Scholarship',
  createdAt: '2026-09-25T10:00:00+00:00', statusHistory: [], requirements: [], dependencies: [], jobs: [], entityReviews: [], conflictReviews: [], auditEntries: [],
  eligibility: {
    result: 'NOT_ELIGIBLE', failedCriteria: ['family_income_limit'], unknownCriteria: [], conflict: false,
    confidence: 'MEDIUM', confidenceReason: 'At least one criterion relies on a citizen-supplied document.',
    completeness: { total: 6, verifiedByProvider: 5, providedByCitizen: 1, pending: 0, notProvided: 0, failed: 0 },
    criteria: [
      { id: 'family_income_limit', type: 'maxValue', requirementCode: 'INCOME_PROOF', label: 'Annual family income up to ₹6,00,000', status: 'FAIL', source: 'VERIFIED', observed: 750000, reason: 'Verified value: 750000.' },
      { id: 'identity_verified', type: 'record', requirementCode: 'IDENTITY', label: 'Identity is verified', status: 'PASS', source: 'MANUAL', reason: 'Provided by you.' },
    ],
  },
};

describe('AdminApplicationDetailPage eligibility', () => {
  it('shows the rule outcome, failed rules, completeness and data-quality confidence', async () => {
    const api = { adminApplicationDetail: vi.fn().mockResolvedValue(DETAIL) };
    render(<AdminApplicationDetailPage applicationId="APP-1" onBack={() => {}} api={api} />);
    const section = (await screen.findByRole('heading', { name: 'Eligibility Assessment' })).closest('.card');
    expect(within(section).getByText('Not eligible')).toBeInTheDocument();
    expect(within(section).getByText('family_income_limit')).toBeInTheDocument();
    expect(within(section).getByText('MEDIUM')).toBeInTheDocument();
    expect(within(section).getByText('6/6')).toBeInTheDocument();
    const failedRow = within(section).getByText('Annual family income up to ₹6,00,000').closest('tr');
    expect(within(failedRow).getByText('FAIL')).toBeInTheDocument();
    expect(within(failedRow).getByText('750000')).toBeInTheDocument();
    expect(within(failedRow).getByText('Provider-verified')).toBeInTheDocument();
  });
});
