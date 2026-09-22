import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ApplicationFormPage from './ApplicationFormPage';
import { api } from '../api';

vi.mock('../api', () => ({ api: { applyToScheme: vi.fn(), service: vi.fn(), autoFillRequirement: vi.fn(), uploadRequirement: vi.fn() } }));

const CITIZEN = { citizenId: 'CITIZEN_001', name: 'Test Citizen', dob: '2000-01-01', phone: '+91-9000000000' };

const APPLICATION_A = {
  appId: 'APP-ZZZ-ALPHA-00001', serviceId: 'ZZZ-ALPHA-2099', status: 'IN_PROGRESS',
  requirements: [
    { requirementCode: 'IDENTITY', displayLabel: 'Identity', status: 'NOT_PROVIDED', mandatory: true, dataType: 'ATTRIBUTE' },
    { requirementCode: 'DOMICILE_PROOF', displayLabel: 'Maharashtra domicile', status: 'NOT_PROVIDED', mandatory: true, dataType: 'CERTIFICATE' },
    { requirementCode: 'INCOME_PROOF', displayLabel: 'Income proof', status: 'NOT_PROVIDED', mandatory: true, dataType: 'CERTIFICATE' },
  ],
};

const APPLICATION_B = {
  appId: 'APP-ZZZ-BETA-00002', serviceId: 'ZZZ-BETA-2099', status: 'IN_PROGRESS',
  requirements: [
    { requirementCode: 'BIRTH_CERTIFICATE', displayLabel: 'Birth certificate', status: 'NOT_PROVIDED', mandatory: true, dataType: 'CERTIFICATE' },
  ],
};

const SCHEME_A = { serviceId: 'ZZZ-ALPHA-2099', name: 'Zeta Test Assistance Scheme', category: 'Zeta Category', description: 'Alpha scheme description.' };
const SCHEME_B = { serviceId: 'ZZZ-BETA-2099', name: 'Omega Test Support Programme', category: 'Omega Category', description: 'Beta scheme description.' };

describe('ApplicationFormPage', () => {
  beforeEach(() => {
    api.applyToScheme.mockReset();
    api.service.mockReset();
    api.autoFillRequirement.mockReset();
    api.uploadRequirement.mockReset();
  });

  it('shows a loading state before the backend responds', async () => {
    let resolveApply;
    api.applyToScheme.mockReturnValue(new Promise(resolve => { resolveApply = resolve; }));
    api.service.mockResolvedValue(SCHEME_A);
    render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
    expect(screen.getByRole('status')).toBeInTheDocument();
    resolveApply(APPLICATION_A);
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  });

  it('shows an error state when the backend call fails', async () => {
    api.applyToScheme.mockRejectedValue(new Error('Configured scheme not found or disabled'));
    api.service.mockResolvedValue(SCHEME_A);
    render(<ApplicationFormPage schemeId="DOES-NOT-EXIST" citizen={CITIZEN} navigate={() => {}} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Configured scheme not found or disabled');
  });

  describe('with a loaded application', () => {
    beforeEach(() => {
      api.applyToScheme.mockResolvedValue(APPLICATION_A);
      api.service.mockResolvedValue(SCHEME_A);
    });

    it('requirement 1+2: Apply creates/loads the real application, whose id comes from the backend', async () => {
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      expect(await screen.findByText('APP-ZZZ-ALPHA-00001')).toBeInTheDocument();
      expect(api.applyToScheme).toHaveBeenCalledWith('ZZZ-ALPHA-2099');
    });

    it('requirement 3: personal fields are backend-driven (from the authenticated citizen, not invented)', async () => {
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');
      expect(screen.getByText('Test Citizen')).toBeInTheDocument();
      expect(screen.getByText('CITIZEN_001')).toBeInTheDocument();
    });

    it('requirement 4: requirements are backend-driven, one card per requirement', async () => {
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');
      expect(screen.getByRole('heading', { name: 'Identity' })).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Maharashtra domicile' })).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Income proof' })).toBeInTheDocument();
    });

    it('requirement 5+6: every requirement has its own Auto-Fill action; only document-like requirements also get Manual Upload', async () => {
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');
      const autoFillButtons = screen.getAllByRole('button', { name: 'Auto-Fill' });
      expect(autoFillButtons).toHaveLength(3); // one per requirement
      const uploadButtons = screen.getAllByRole('button', { name: 'Upload Manually' });
      expect(uploadButtons).toHaveLength(2); // only the two CERTIFICATE requirements, not IDENTITY (ATTRIBUTE)
    });

    it('requirement 7: there is no global Auto-Fill All button anywhere on the page', async () => {
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');
      expect(screen.queryByText(/auto-?fill all/i)).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /auto-?fill all/i })).not.toBeInTheDocument();
    });

    it('requirement 8: Auto-Fill receives the correct application + requirement, not a different one', async () => {
      api.autoFillRequirement.mockResolvedValue({ ...APPLICATION_A, requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'INCOME_PROOF' ? { ...r, status: 'RETRIEVED' } : r) });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');

      const incomeCard = screen.getByRole('heading', { name: 'Income proof' }).closest('article');
      const user = userEvent.setup();
      // Auto-Fill first shows a consent prompt; only Accept triggers the call.
      await user.click(within(incomeCard).getByRole('button', { name: 'Auto-Fill' }));
      await user.click(within(incomeCard).getByRole('button', { name: 'Accept' }));

      expect(api.autoFillRequirement).toHaveBeenCalledWith('APP-ZZZ-ALPHA-00001', 'INCOME_PROOF', 'ACCEPT');
      expect(api.autoFillRequirement).not.toHaveBeenCalledWith(expect.anything(), 'DOMICILE_PROOF', expect.anything());
    });

    it('requirement: the consent prompt never names a department, provider or data source', async () => {
      api.autoFillRequirement.mockResolvedValue(APPLICATION_A);
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');

      const incomeCard = screen.getByRole('heading', { name: 'Income proof' }).closest('article');
      const user = userEvent.setup();
      await user.click(within(incomeCard).getByRole('button', { name: 'Auto-Fill' }));

      expect(within(incomeCard).getByRole('button', { name: 'Accept' })).toBeInTheDocument();
      expect(within(incomeCard).getByRole('button', { name: 'Reject' })).toBeInTheDocument();
      const cardText = incomeCard.textContent;
      for (const forbidden of ['Department', 'DigiLocker', 'API Setu', 'provider', 'Provider']) {
        expect(cardText).not.toContain(forbidden);
      }
    });

    it('requirement: Reject sends the REJECT decision, never calls Accept behaviour, and shows the generic decline message', async () => {
      api.autoFillRequirement.mockResolvedValue({ ...APPLICATION_A, requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'INCOME_PROOF' ? { ...r, status: 'ACTION_REQUIRED', userAction: 'Automatic retrieval was not allowed. You can provide this manually.' } : r) });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');

      const incomeCard = screen.getByRole('heading', { name: 'Income proof' }).closest('article');
      const user = userEvent.setup();
      await user.click(within(incomeCard).getByRole('button', { name: 'Auto-Fill' }));
      await user.click(within(incomeCard).getByRole('button', { name: 'Reject' }));

      expect(api.autoFillRequirement).toHaveBeenCalledWith('APP-ZZZ-ALPHA-00001', 'INCOME_PROOF', 'REJECT');
      expect(await within(incomeCard).findByText('Automatic retrieval was not allowed. You can provide this manually.')).toBeInTheDocument();
    });

    it('requirement: Manual Upload on one card stays available while another card is mid Auto-Fill', async () => {
      let resolveAutoFill;
      api.autoFillRequirement.mockReturnValue(new Promise(resolve => { resolveAutoFill = resolve; }));
      api.uploadRequirement.mockResolvedValue({ ...APPLICATION_A, requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'DOMICILE_PROOF' ? { ...r, status: 'VALIDATED', documentId: 'DOC-1' } : r) });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');

      const incomeCard = screen.getByRole('heading', { name: 'Income proof' }).closest('article');
      const domicileCard = screen.getByRole('heading', { name: 'Maharashtra domicile' }).closest('article');
      const user = userEvent.setup();
      await user.click(within(incomeCard).getByRole('button', { name: 'Auto-Fill' }));
      await user.click(within(incomeCard).getByRole('button', { name: 'Accept' }));
      // Income's Auto-Fill is now in flight (unresolved); Domicile's Manual
      // Upload must still work, independently.
      await user.click(within(domicileCard).getByRole('button', { name: 'Upload Manually' }));
      await user.type(within(domicileCard).getByLabelText('Document title'), 'My domicile copy');
      await user.type(within(domicileCard).getByLabelText('Document details (demo upload)'), 'Synthetic demo content');
      await user.click(within(domicileCard).getByRole('button', { name: 'Submit' }));
      expect(api.uploadRequirement).toHaveBeenCalled();
      resolveAutoFill({ ...APPLICATION_A, requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'INCOME_PROOF' ? { ...r, status: 'RETRIEVED' } : r) });
    });

    it('requirement 9: manual upload receives the correct application + requirement', async () => {
      api.uploadRequirement.mockResolvedValue({ ...APPLICATION_A, requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'DOMICILE_PROOF' ? { ...r, status: 'VALIDATED', documentId: 'DOC-1' } : r) });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');

      const domicileCard = screen.getByRole('heading', { name: 'Maharashtra domicile' }).closest('article');
      const user = userEvent.setup();
      await user.click(within(domicileCard).getByRole('button', { name: 'Upload Manually' }));
      await user.type(within(domicileCard).getByLabelText('Document title'), 'My domicile copy');
      await user.type(within(domicileCard).getByLabelText('Document details (demo upload)'), 'Synthetic demo content');
      await user.click(within(domicileCard).getByRole('button', { name: 'Submit' }));

      expect(api.uploadRequirement).toHaveBeenCalledWith(
        'APP-ZZZ-ALPHA-00001', 'DOMICILE_PROOF',
        expect.objectContaining({ title: 'My domicile copy', content: 'Synthetic demo content' }),
      );
    });

    it('requirement 10: requirement states render dynamically after an action', async () => {
      api.autoFillRequirement.mockResolvedValue({ ...APPLICATION_A, requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'IDENTITY' ? { ...r, status: 'RETRIEVED' } : r) });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');

      const identityCard = screen.getByRole('heading', { name: 'Identity' }).closest('article');
      expect(within(identityCard).getByText('Not provided')).toBeInTheDocument();

      const user = userEvent.setup();
      await user.click(within(identityCard).getByRole('button', { name: 'Auto-Fill' }));
      await user.click(within(identityCard).getByRole('button', { name: 'Accept' }));

      await waitFor(() => expect(within(screen.getByRole('heading', { name: 'Identity' }).closest('article')).getByText('Verified')).toBeInTheDocument());
    });

    // Phase 6E: Continue to Review must navigate to the review step using
    // the same already-open application, never creating a second one.
    it('Phase 6E: Continue to Review navigates to the review page without creating a second application', async () => {
      const navigate = vi.fn();
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={navigate} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');
      const user = userEvent.setup();
      await user.click(screen.getByRole('button', { name: 'Continue to Review' }));
      expect(navigate).toHaveBeenCalledWith('reviewApplication');
      expect(api.applyToScheme).toHaveBeenCalledTimes(1);
    });

    it('Phase 6E: a submitted application disables all requirement actions and shows a submitted notice', async () => {
      api.applyToScheme.mockResolvedValue({ ...APPLICATION_A, status: 'SUBMITTED' });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');
      expect(screen.getByText('This application has already been submitted.')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Auto-Fill' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Upload Manually' })).not.toBeInTheDocument();
    });

    // Phase 6D: requirement state must be rendered from persisted backend
    // state, not local-only React state, so it survives a fresh page load.
    it('Phase 6D: an Action Required requirement loaded fresh (e.g. after a page refresh) shows its backend-persisted guidance without any prior click in this render', async () => {
      api.applyToScheme.mockResolvedValue({
        ...APPLICATION_A,
        requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'INCOME_PROOF'
          ? { ...r, status: 'ACTION_REQUIRED', userAction: 'Automatic retrieval was not allowed. You can provide this manually.' }
          : r),
      });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');

      const incomeCard = screen.getByRole('heading', { name: 'Income proof' }).closest('article');
      expect(within(incomeCard).getByText('Action required')).toBeInTheDocument();
      expect(within(incomeCard).getByText('Automatic retrieval was not allowed. You can provide this manually.')).toBeInTheDocument();
      // No Auto-Fill click happened in this render at all -- this message
      // came entirely from the initial API response.
      expect(api.autoFillRequirement).not.toHaveBeenCalled();
    });

    it('Phase 6D: a Verified (VALIDATED) requirement loaded fresh shows the Verified label and no action guidance', async () => {
      api.applyToScheme.mockResolvedValue({
        ...APPLICATION_A,
        requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'DOMICILE_PROOF' ? { ...r, status: 'VALIDATED', userAction: 'No action required' } : r),
      });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');
      const domicileCard = screen.getByRole('heading', { name: 'Maharashtra domicile' }).closest('article');
      expect(within(domicileCard).getByText('Verified')).toBeInTheDocument();
      expect(within(domicileCard).queryByText(/action required/i)).not.toBeInTheDocument();
    });

    it('Phase 6D: a requirement with a prior failed/action-required attempt offers Retry instead of Auto-Fill, and Retry re-runs the same consent-gated flow', async () => {
      api.applyToScheme.mockResolvedValue({
        ...APPLICATION_A,
        requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'INCOME_PROOF'
          ? { ...r, status: 'WAITING', userAction: 'Retrieval is in progress. You can try again shortly.' }
          : r),
      });
      api.autoFillRequirement.mockResolvedValue({ ...APPLICATION_A, requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'INCOME_PROOF' ? { ...r, status: 'VALIDATED', userAction: 'No action required' } : r) });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');

      const incomeCard = screen.getByRole('heading', { name: 'Income proof' }).closest('article');
      expect(within(incomeCard).queryByRole('button', { name: 'Auto-Fill' })).not.toBeInTheDocument();
      expect(within(incomeCard).getByRole('button', { name: 'Retry' })).toBeInTheDocument();

      const user = userEvent.setup();
      await user.click(within(incomeCard).getByRole('button', { name: 'Retry' }));
      // Retry goes through the exact same consent prompt -- never bypassed.
      expect(within(incomeCard).getByText(/Allow SANGAM to retrieve and verify/)).toBeInTheDocument();
      await user.click(within(incomeCard).getByRole('button', { name: 'Accept' }));

      expect(api.autoFillRequirement).toHaveBeenCalledWith('APP-ZZZ-ALPHA-00001', 'INCOME_PROOF', 'ACCEPT');
      await waitFor(() => expect(within(screen.getByRole('heading', { name: 'Income proof' }).closest('article')).getByText('Verified')).toBeInTheDocument());
    });

    it('Phase 6D: independent per-requirement loading states -- one card retrying does not disable or block an unrelated card', async () => {
      let resolveRetry;
      api.applyToScheme.mockResolvedValue({
        ...APPLICATION_A,
        requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'INCOME_PROOF' ? { ...r, status: 'FAILED', userAction: 'Automatic retrieval could not complete. You can provide this manually.' } : r),
      });
      api.autoFillRequirement.mockReturnValue(new Promise(resolve => { resolveRetry = resolve; }));
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');

      const incomeCard = screen.getByRole('heading', { name: 'Income proof' }).closest('article');
      const identityCard = screen.getByRole('heading', { name: 'Identity' }).closest('article');
      const user = userEvent.setup();
      await user.click(within(incomeCard).getByRole('button', { name: 'Retry' }));
      await user.click(within(incomeCard).getByRole('button', { name: 'Accept' }));

      // Income's retry is now in flight (unresolved promise); Identity's own
      // Auto-Fill button must remain fully enabled and independent.
      expect(within(identityCard).getByRole('button', { name: 'Auto-Fill' })).not.toBeDisabled();
      resolveRetry({ ...APPLICATION_A, requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'INCOME_PROOF' ? { ...r, status: 'VALIDATED', userAction: 'No action required' } : r) });
    });
  });

  it('requirement 11: a different application/scheme renders a different form using the same component', async () => {
    api.applyToScheme.mockResolvedValue(APPLICATION_B);
    api.service.mockResolvedValue(SCHEME_B);
    render(<ApplicationFormPage schemeId="ZZZ-BETA-2099" citizen={CITIZEN} navigate={() => {}} />);

    expect(await screen.findByText('Omega Test Support Programme')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Birth certificate' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Income proof' })).not.toBeInTheDocument();
    // Only one requirement on this scheme -> only one Auto-Fill button.
    expect(screen.getAllByRole('button', { name: 'Auto-Fill' })).toHaveLength(1);
  });
});
