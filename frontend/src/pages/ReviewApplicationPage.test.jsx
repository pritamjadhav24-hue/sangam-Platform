import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ReviewApplicationPage from './ReviewApplicationPage';
import { api } from '../api';

vi.mock('../api', () => ({ api: { applyToScheme: vi.fn(), service: vi.fn(), submitApplication: vi.fn() } }));

const CITIZEN = { citizenId: 'CITIZEN_001', name: 'Test Citizen', dob: '2000-01-01', phone: '+91-9000000000' };

const READY_APPLICATION = {
  appId: 'APP-ZZZ-ALPHA-00001', serviceId: 'ZZZ-ALPHA-2099', status: 'IN_PROGRESS',
  readyForSubmission: true, blockingRequirements: [],
  requirements: [
    { requirementCode: 'IDENTITY', displayLabel: 'Identity', status: 'RETRIEVED', mandatory: true, dataType: 'ATTRIBUTE' },
    { requirementCode: 'DOMICILE_PROOF', displayLabel: 'Maharashtra domicile', status: 'VALIDATED', mandatory: true, dataType: 'CERTIFICATE' },
  ],
};

const INCOMPLETE_APPLICATION = {
  appId: 'APP-ZZZ-ALPHA-00001', serviceId: 'ZZZ-ALPHA-2099', status: 'IN_PROGRESS',
  readyForSubmission: false,
  blockingRequirements: [
    { requirementCode: 'INCOME_PROOF', displayLabel: 'Income proof', status: 'NOT_PROVIDED', userAction: 'Use Auto-Fill or Manual Upload to provide this.' },
  ],
  requirements: [
    { requirementCode: 'IDENTITY', displayLabel: 'Identity', status: 'RETRIEVED', mandatory: true, dataType: 'ATTRIBUTE' },
    { requirementCode: 'INCOME_PROOF', displayLabel: 'Income proof', status: 'NOT_PROVIDED', mandatory: true, dataType: 'CERTIFICATE' },
  ],
};

const SUBMITTED_APPLICATION = {
  ...READY_APPLICATION, status: 'SUBMITTED', submittedAt: '2026-09-22T10:00:00+00:00',
};

const SCHEME_A = { serviceId: 'ZZZ-ALPHA-2099', name: 'Zeta Test Assistance Scheme', category: 'Zeta Category', description: 'Alpha scheme description.' };

describe('ReviewApplicationPage', () => {
  beforeEach(() => {
    api.applyToScheme.mockReset();
    api.service.mockReset();
    api.submitApplication.mockReset();
    api.service.mockResolvedValue(SCHEME_A);
  });

  it('renders dynamic application data: scheme, personal details, requirements', async () => {
    api.applyToScheme.mockResolvedValue(READY_APPLICATION);
    render(<ReviewApplicationPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
    await screen.findByText('Zeta Test Assistance Scheme');
    expect(screen.getByText('Alpha scheme description.')).toBeInTheDocument();
    expect(screen.getByText('Test Citizen')).toBeInTheDocument();
    expect(screen.getByText('CITIZEN_001')).toBeInTheDocument();
    expect(screen.getByText('Identity')).toBeInTheDocument();
    expect(screen.getByText('Maharashtra domicile')).toBeInTheDocument();
  });

  it('requirement statuses render using the same citizen-facing labels as the form', async () => {
    api.applyToScheme.mockResolvedValue(READY_APPLICATION);
    render(<ReviewApplicationPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
    await screen.findByText('Zeta Test Assistance Scheme');
    const verifiedLabels = screen.getAllByText('Verified');
    expect(verifiedLabels.length).toBeGreaterThanOrEqual(2);
  });

  it('an incomplete application shows which requirements still need action and never pretends it can submit', async () => {
    api.applyToScheme.mockResolvedValue(INCOMPLETE_APPLICATION);
    render(<ReviewApplicationPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
    await screen.findByText('Zeta Test Assistance Scheme');
    expect(screen.getByText(/Action required/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Submit Application' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Back to form' })).toBeInTheDocument();
  });

  it('back/edit navigation returns to the application form', async () => {
    api.applyToScheme.mockResolvedValue(INCOMPLETE_APPLICATION);
    const navigate = vi.fn();
    render(<ReviewApplicationPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={navigate} />);
    await screen.findByText('Zeta Test Assistance Scheme');
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Back to form' }));
    expect(navigate).toHaveBeenCalledWith('applicationForm');
  });

  it('a ready application shows Submit Application, with a confirmation step before the real request fires', async () => {
    api.applyToScheme.mockResolvedValue(READY_APPLICATION);
    render(<ReviewApplicationPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
    await screen.findByText('Zeta Test Assistance Scheme');
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Submit Application' }));
    expect(api.submitApplication).not.toHaveBeenCalled();
    expect(screen.getByText(/Submit this application\?/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Confirm & Submit' })).toBeInTheDocument();
  });

  it('confirming submission calls the API exactly once and disables the button while in flight (double-click protection)', async () => {
    api.applyToScheme.mockResolvedValue(READY_APPLICATION);
    let resolveSubmit;
    api.submitApplication.mockReturnValue(new Promise(resolve => { resolveSubmit = resolve; }));
    render(<ReviewApplicationPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
    await screen.findByText('Zeta Test Assistance Scheme');
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Submit Application' }));
    const confirmButton = screen.getByRole('button', { name: 'Confirm & Submit' });
    await user.click(confirmButton);
    // Try clicking again while the request is in flight.
    await user.click(screen.getByRole('button', { name: /Submitting/ }));
    expect(api.submitApplication).toHaveBeenCalledTimes(1);
    resolveSubmit(SUBMITTED_APPLICATION);
    await waitFor(() => expect(screen.getByText('Application submitted')).toBeInTheDocument());
  });

  it('shows a citizen-friendly confirmation with application ID, scheme name, status and timestamp after successful submission', async () => {
    api.applyToScheme.mockResolvedValue(READY_APPLICATION);
    api.submitApplication.mockResolvedValue(SUBMITTED_APPLICATION);
    render(<ReviewApplicationPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
    await screen.findByText('Zeta Test Assistance Scheme');
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Submit Application' }));
    await user.click(screen.getByRole('button', { name: 'Confirm & Submit' }));
    await screen.findByText('Application submitted');
    expect(screen.getByText('APP-ZZZ-ALPHA-00001')).toBeInTheDocument();
    expect(screen.getByText('Zeta Test Assistance Scheme')).toBeInTheDocument();
    expect(screen.getByText('Submitted')).toBeInTheDocument();
  });

  it('a submitted application loaded fresh (e.g. after reload) shows the confirmation view directly, from backend state', async () => {
    api.applyToScheme.mockResolvedValue(SUBMITTED_APPLICATION);
    render(<ReviewApplicationPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
    await screen.findByText('Application submitted');
    expect(api.submitApplication).not.toHaveBeenCalled();
    expect(screen.getByText('APP-ZZZ-ALPHA-00001')).toBeInTheDocument();
  });

  it('a rejected submission attempt shows an error and does not pretend it succeeded', async () => {
    api.applyToScheme.mockResolvedValue(READY_APPLICATION);
    api.submitApplication.mockRejectedValue(new Error('This application is not ready to submit yet.'));
    render(<ReviewApplicationPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
    await screen.findByText('Zeta Test Assistance Scheme');
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Submit Application' }));
    await user.click(screen.getByRole('button', { name: 'Confirm & Submit' }));
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryByText('Application submitted')).not.toBeInTheDocument();
  });

  it('does not leak provider/department/source details anywhere on the page', async () => {
    api.applyToScheme.mockResolvedValue(READY_APPLICATION);
    render(<ReviewApplicationPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
    await screen.findByText('Zeta Test Assistance Scheme');
    const pageText = document.body.textContent;
    for (const forbidden of ['Department', 'DigiLocker', 'API Setu', 'provider', 'Provider', 'adapter']) {
      expect(pageText).not.toContain(forbidden);
    }
  });
});
