import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminSchemesPage from './AdminSchemesPage';
import AdminSchemeDetailPage from './AdminSchemeDetailPage';

const SCHEMES = [
  { schemeId: 'SCH-MH-2026', name: 'Post-Matric Scholarship', department: 'Higher Education Department', category: 'Education', active: true, synthetic: false, requirementCount: 3, mandatoryCount: 3, providerCoverage: 2, applicationCount: 4 },
];
const DETAIL = {
  schemeId: 'SCH-MH-2026', name: 'Post-Matric Scholarship', department: 'Higher Education Department', active: true, synthetic: false,
  category: 'Education', description: 'Scholarship for students', eligibility: 'Family income below limit', benefits: 'Fee reimbursement', applicationWindow: 'June–Sept', applicationCount: 4,
  requirements: [
    { requirementCode: 'INCOME_PROOF', label: 'Income proof', dataType: 'CERTIFICATE', category: 'REVENUE', description: null, mandatory: true, capability: 'INCOME_PROOF', manualUploadOnly: false,
      eligibleProviders: [{ providerId: 'REVENUE-DEPARTMENT', provider: 'Revenue Department', priority: 10, healthStatus: 'AVAILABLE', serviceName: 'Income Verification' }] },
    { requirementCode: 'HOUSING_ALLOTMENT', label: 'Housing allotment', dataType: null, category: null, description: null, mandatory: false, capability: 'HOUSING_ALLOTMENT', manualUploadOnly: true, eligibleProviders: [] },
  ],
};

describe('AdminSchemesPage (catalogue)', () => {
  it('lists schemes from the backend with coverage and opens detail', async () => {
    const onOpenScheme = vi.fn();
    render(<AdminSchemesPage api={{ adminSchemes: vi.fn().mockResolvedValue({ schemes: SCHEMES }) }} onOpenScheme={onOpenScheme} />);
    await waitFor(() => expect(screen.getByText('Post-Matric Scholarship')).toBeInTheDocument());
    expect(screen.getByText('1 manual-upload only')).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /View Detail/ }));
    expect(onOpenScheme).toHaveBeenCalledWith('SCH-MH-2026');
  });

  it('shows an honest empty state when no schemes exist', async () => {
    render(<AdminSchemesPage api={{ adminSchemes: vi.fn().mockResolvedValue({ schemes: [] }) }} onOpenScheme={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('No schemes configured')).toBeInTheDocument());
  });
});

describe('AdminSchemeDetailPage', () => {
  it('shows requirements with capability, eligible providers and manual-only state', async () => {
    const onOpenProvider = vi.fn();
    render(<AdminSchemeDetailPage api={{ adminSchemeDetail: vi.fn().mockResolvedValue(DETAIL) }} schemeId="SCH-MH-2026" onBack={vi.fn()} onOpenProvider={onOpenProvider} />);
    await waitFor(() => expect(screen.getByText('Income proof')).toBeInTheDocument());
    expect(screen.getByText('Family income below limit')).toBeInTheDocument();
    expect(screen.getByText('No eligible provider — manual upload only')).toBeInTheDocument();
    expect(screen.getByText('Not in requirement vocabulary')).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Revenue Department/ }));
    expect(onOpenProvider).toHaveBeenCalledWith('REVENUE-DEPARTMENT');
  });

  it('shows an error when the scheme does not exist', async () => {
    render(<AdminSchemeDetailPage api={{ adminSchemeDetail: vi.fn().mockRejectedValue(new Error('Scheme not found.')) }} schemeId="NOPE" onBack={vi.fn()} onOpenProvider={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Scheme not found.'));
  });
});
