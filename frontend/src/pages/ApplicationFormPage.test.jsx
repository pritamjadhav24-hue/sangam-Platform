import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ApplicationFormPage from './ApplicationFormPage';
import { api } from '../api';

vi.mock('../api', () => ({ api: { applyToScheme: vi.fn(), service: vi.fn(), autoFillRequirement: vi.fn(), uploadRequirement: vi.fn(), removeUpload: vi.fn(), viewDocument: vi.fn(), downloadDocument: vi.fn() } }));

const PNG_FILE = () => new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])], 'scan.png', { type: 'image/png' });

// Choose "Upload from device" and pick a file through the (hidden) file input.
async function chooseDeviceFile(user, card, file = PNG_FILE()) {
  await user.click(within(card).getByRole('button', { name: 'Upload document' }));
  await user.click(within(card).getByRole('button', { name: 'Upload from device' }));
  fireEvent.change(within(card).getByTestId('device-input'), { target: { files: [file] } });
}

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
    api.viewDocument.mockReset();
    api.downloadDocument.mockReset();
    api.removeUpload.mockReset();
    URL.createObjectURL = vi.fn(() => 'blob:preview');
    URL.revokeObjectURL = vi.fn();
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
      const autoFillButtons = screen.getAllByRole('button', { name: 'Auto-Fill verified information' });
      expect(autoFillButtons).toHaveLength(3); // one per requirement
      const uploadButtons = screen.getAllByRole('button', { name: 'Upload document' });
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
      await user.click(within(incomeCard).getByRole('button', { name: 'Auto-Fill verified information' }));
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
      await user.click(within(incomeCard).getByRole('button', { name: 'Auto-Fill verified information' }));

      expect(within(incomeCard).getByRole('button', { name: 'Accept' })).toBeInTheDocument();
      expect(within(incomeCard).getByRole('button', { name: 'Reject' })).toBeInTheDocument();
      const cardText = incomeCard.textContent;
      for (const forbidden of ['Department', 'DigiLocker', 'API Setu', 'provider', 'Provider']) {
        expect(cardText).not.toContain(forbidden);
      }
    });

    it('requirement: Reject sends the REJECT decision, never calls Accept behaviour, and shows the generic decline message', async () => {
      api.autoFillRequirement.mockResolvedValue({ ...APPLICATION_A, requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'INCOME_PROOF' ? { ...r, status: 'ACTION_REQUIRED', verificationState: 'CONSENT_DENIED', canUpload: true, userAction: 'You chose not to allow automatic retrieval. You can upload the document yourself.' } : r) });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');

      const incomeCard = screen.getByRole('heading', { name: 'Income proof' }).closest('article');
      const user = userEvent.setup();
      await user.click(within(incomeCard).getByRole('button', { name: 'Auto-Fill verified information' }));
      await user.click(within(incomeCard).getByRole('button', { name: 'Reject' }));

      expect(api.autoFillRequirement).toHaveBeenCalledWith('APP-ZZZ-ALPHA-00001', 'INCOME_PROOF', 'REJECT');
      expect(await within(incomeCard).findByText('You chose not to allow automatic retrieval.')).toBeInTheDocument();
      // Declining never removes the manual route.
      expect(within(incomeCard).getByRole('button', { name: 'Upload document' })).toBeInTheDocument();
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
      await user.click(within(incomeCard).getByRole('button', { name: 'Auto-Fill verified information' }));
      await user.click(within(incomeCard).getByRole('button', { name: 'Accept' }));
      // Income's Auto-Fill is now in flight (unresolved); Domicile's Manual
      // Upload must still work, independently.
      await chooseDeviceFile(user, domicileCard);
      await user.click(within(domicileCard).getByRole('button', { name: 'Confirm & upload' }));
      await waitFor(() => expect(api.uploadRequirement).toHaveBeenCalled());
      resolveAutoFill({ ...APPLICATION_A, requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'INCOME_PROOF' ? { ...r, status: 'RETRIEVED' } : r) });
    });

    it('requirement 9: manual upload receives the correct application + requirement', async () => {
      api.uploadRequirement.mockResolvedValue({ ...APPLICATION_A, requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'DOMICILE_PROOF' ? { ...r, status: 'VALIDATED', documentId: 'DOC-1' } : r) });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');

      const domicileCard = screen.getByRole('heading', { name: 'Maharashtra domicile' }).closest('article');
      const user = userEvent.setup();
      await chooseDeviceFile(user, domicileCard);
      await user.click(within(domicileCard).getByRole('button', { name: 'Confirm & upload' }));

      await waitFor(() => expect(api.uploadRequirement).toHaveBeenCalledWith(
        'APP-ZZZ-ALPHA-00001', 'DOMICILE_PROOF',
        expect.objectContaining({ title: 'Maharashtra domicile', contentType: 'image/png', fileName: 'scan.png', content: 'iVBORw0KGgo=' }),
      ));
    });

    it('device upload: previews the file before anything is sent, and Remove discards it', async () => {
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');
      const domicileCard = screen.getByRole('heading', { name: 'Maharashtra domicile' }).closest('article');
      const user = userEvent.setup();
      await chooseDeviceFile(user, domicileCard);
      expect(within(domicileCard).getByRole('img', { name: 'Preview: scan.png' })).toHaveAttribute('src', 'blob:preview');
      expect(within(domicileCard).getByRole('button', { name: 'View' })).toBeInTheDocument();
      expect(api.uploadRequirement).not.toHaveBeenCalled();
      await user.click(within(domicileCard).getByRole('button', { name: 'Remove' }));
      expect(within(domicileCard).getByText('Choose document source')).toBeInTheDocument();
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview');
    });

    it('device upload: Replace picks a new file and only the confirmed one is uploaded', async () => {
      api.uploadRequirement.mockResolvedValue(APPLICATION_A);
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');
      const domicileCard = screen.getByRole('heading', { name: 'Maharashtra domicile' }).closest('article');
      const user = userEvent.setup();
      await chooseDeviceFile(user, domicileCard);
      await user.click(within(domicileCard).getByRole('button', { name: 'Replace' }));
      fireEvent.change(within(domicileCard).getByTestId('device-input'), { target: { files: [new File(['%PDF-1.4'], 'domicile.pdf', { type: 'application/pdf' })] } });
      expect(within(domicileCard).getByText('PDF · domicile.pdf')).toBeInTheDocument();
      await user.click(within(domicileCard).getByRole('button', { name: 'Confirm & upload' }));
      await waitFor(() => expect(api.uploadRequirement).toHaveBeenCalledTimes(1));
      expect(api.uploadRequirement.mock.calls[0][2]).toMatchObject({ contentType: 'application/pdf', fileName: 'domicile.pdf' });
    });

    it('device upload: rejects unsupported types and files over 5 MB without uploading', async () => {
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');
      const domicileCard = screen.getByRole('heading', { name: 'Maharashtra domicile' }).closest('article');
      const user = userEvent.setup();
      await chooseDeviceFile(user, domicileCard, new File(['MZ'], 'setup.exe', { type: 'application/x-msdownload' }));
      expect(within(domicileCard).getByRole('alert')).toHaveTextContent('not supported');
      const huge = new File(['x'], 'big.png', { type: 'image/png' });
      Object.defineProperty(huge, 'size', { value: 6 * 1024 * 1024 });
      fireEvent.change(within(domicileCard).getByTestId('device-input'), { target: { files: [huge] } });
      expect(within(domicileCard).getByRole('alert')).toHaveTextContent('larger than 5 MB');
      expect(api.uploadRequirement).not.toHaveBeenCalled();
    });

    it('camera: without live camera support, falls back to the device camera input', async () => {
      const original = navigator.mediaDevices;
      Object.defineProperty(navigator, 'mediaDevices', { value: undefined, configurable: true });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');
      const domicileCard = screen.getByRole('heading', { name: 'Maharashtra domicile' }).closest('article');
      const user = userEvent.setup();
      await user.click(within(domicileCard).getByRole('button', { name: 'Upload document' }));
      const cameraInput = within(domicileCard).getByTestId('camera-input');
      expect(cameraInput).toHaveAttribute('capture', 'environment');
      expect(cameraInput).toHaveAttribute('accept', 'image/*');
      fireEvent.change(cameraInput, { target: { files: [new File([new Uint8Array([0xff, 0xd8, 0xff])], 'photo.jpg', { type: 'image/jpeg' })] } });
      expect(within(domicileCard).getByRole('button', { name: 'Retake' })).toBeInTheDocument();
      Object.defineProperty(navigator, 'mediaDevices', { value: original, configurable: true });
    });

    it('camera: captures a still from the live camera, previews it and stops the camera', async () => {
      const stop = vi.fn();
      const original = navigator.mediaDevices;
      Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] }) }, configurable: true });
      const getContext = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: vi.fn() });
      const toBlob = vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(callback => callback(new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: 'image/jpeg' })));
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');
      const domicileCard = screen.getByRole('heading', { name: 'Maharashtra domicile' }).closest('article');
      const user = userEvent.setup();
      await user.click(within(domicileCard).getByRole('button', { name: 'Upload document' }));
      await user.click(within(domicileCard).getByRole('button', { name: 'Take a picture' }));
      await user.click(await within(domicileCard).findByRole('button', { name: 'Capture' }));
      expect(within(domicileCard).getByRole('img', { name: 'Preview: camera-capture.jpg' })).toBeInTheDocument();
      expect(stop).toHaveBeenCalled();
      getContext.mockRestore();
      toBlob.mockRestore();
      Object.defineProperty(navigator, 'mediaDevices', { value: original, configurable: true });
    });

    it('a confirmed citizen upload can be previewed as an image and removed before submission', async () => {
      const uploaded = { ...APPLICATION_A, requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'DOMICILE_PROOF' ? { ...r, status: 'VALIDATED', documentId: 'DOC-1' } : r) };
      api.applyToScheme.mockResolvedValue(uploaded);
      api.viewDocument.mockResolvedValue({ documentId: 'DOC-1', title: 'Maharashtra Domicile Certificate', isFile: true, contentType: 'image/png', fileName: 'scan.png' });
      api.downloadDocument.mockResolvedValue({ blob: new Blob(['x'], { type: 'image/png' }), filename: 'scan.png' });
      api.removeUpload.mockResolvedValue(APPLICATION_A);
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');
      const domicileCard = screen.getByRole('heading', { name: 'Maharashtra domicile' }).closest('article');
      const user = userEvent.setup();
      expect(within(domicileCard).getByRole('button', { name: 'Replace' })).toBeInTheDocument();
      await user.click(within(domicileCard).getByRole('button', { name: 'View' }));
      expect(await within(domicileCard).findByRole('img', { name: 'Maharashtra Domicile Certificate' })).toHaveAttribute('src', 'blob:preview');
      await user.click(within(domicileCard).getByRole('button', { name: 'Remove' }));
      await waitFor(() => expect(api.removeUpload).toHaveBeenCalledWith('APP-ZZZ-ALPHA-00001', 'DOMICILE_PROOF'));
      expect(await within(domicileCard).findByText('Not provided')).toBeInTheDocument();
    });

    it('a provider-verified document offers no Remove action', async () => {
      api.applyToScheme.mockResolvedValue({ ...APPLICATION_A, requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'INCOME_PROOF' ? { ...r, status: 'VALIDATED' } : r) });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');
      const incomeCard = screen.getByRole('heading', { name: 'Income proof' }).closest('article');
      expect(within(incomeCard).queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument();
    });

    it('eligibility: shows the outcome with passed and failed criteria', async () => {
      api.applyToScheme.mockResolvedValue({ ...APPLICATION_A, eligibilityAssessment: { result: 'NOT_ELIGIBLE', conflict: false, criteria: [
        { id: 'domicile', label: 'Domicile of Maharashtra', status: 'PASS', reason: 'Verified value: Maharashtra.' },
        { id: 'income', label: 'Annual family income up to ₹6,00,000', status: 'FAIL', reason: 'Verified value: 750000.' },
      ] } });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      const panel = await screen.findByRole('region', { name: 'Eligibility' });
      expect(within(panel).getByText('Not eligible')).toBeInTheDocument();
      const income = within(panel).getByText('Annual family income up to ₹6,00,000').closest('li');
      expect(within(income).getByText(/Not met/)).toBeInTheDocument();
      expect(within(income).getByText('Verified value: 750000.')).toBeInTheDocument();
      expect(within(within(panel).getByText('Domicile of Maharashtra').closest('li')).getByText(/Met/)).toBeInTheDocument();
    });

    it('eligibility: insufficient data is shown as not yet confirmable, never as ineligible', async () => {
      api.applyToScheme.mockResolvedValue({ ...APPLICATION_A, eligibilityAssessment: { result: 'CANNOT_CONFIRM', conflict: false, criteria: [
        { id: 'income', label: 'Annual family income up to ₹6,00,000', status: 'UNKNOWN', reason: 'This information has not been provided yet.' },
      ] } });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      const panel = await screen.findByRole('region', { name: 'Eligibility' });
      expect(within(panel).getByText('Eligibility cannot be confirmed yet')).toBeInTheDocument();
      expect(within(panel).queryByText('Not eligible')).not.toBeInTheDocument();
      expect(within(panel).getByText('This information has not been provided yet.')).toBeInTheDocument();
    });

    it('an outage-delayed verification shows only a generic, provider-free notice', async () => {
      api.applyToScheme.mockResolvedValue({ ...APPLICATION_A, verificationDelayed: true });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      const notice = await screen.findByText(/Some verifications are temporarily unavailable/);
      // The notice never says which system is unavailable ...
      expect(notice.textContent).not.toMatch(/provider|department|sandbox|revenue|api/i);
      // ... and the page never exposes integration internals. (Departments may
      // be named as the source of verified information -- that is intended.)
      expect(document.body.textContent).not.toMatch(/provider|sandbox|api/i);
    });

    it('requirement 10: requirement states render dynamically after an action', async () => {
      api.autoFillRequirement.mockResolvedValue({ ...APPLICATION_A, requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'IDENTITY' ? { ...r, status: 'RETRIEVED' } : r) });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');

      const identityCard = screen.getByRole('heading', { name: 'Identity' }).closest('article');
      expect(within(identityCard).getByText('Not provided')).toBeInTheDocument();

      const user = userEvent.setup();
      await user.click(within(identityCard).getByRole('button', { name: 'Auto-Fill verified information' }));
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
      await user.click(screen.getByRole('button', { name: 'Continue to review' }));
      expect(navigate).toHaveBeenCalledWith('reviewApplication');
      expect(api.applyToScheme).toHaveBeenCalledTimes(1);
    });

    it('Phase 6E: a submitted application disables all requirement actions and shows a submitted notice', async () => {
      api.applyToScheme.mockResolvedValue({ ...APPLICATION_A, status: 'SUBMITTED' });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');
      expect(screen.getByText('This application has already been submitted.')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Auto-Fill verified information' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Upload document' })).not.toBeInTheDocument();
    });

    // Phase 6D: requirement state must be rendered from persisted backend
    // state, not local-only React state, so it survives a fresh page load.
    it('Phase 6D: an Action Required requirement loaded fresh (e.g. after a page refresh) shows its backend-persisted guidance without any prior click in this render', async () => {
      api.applyToScheme.mockResolvedValue({
        ...APPLICATION_A,
        requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'INCOME_PROOF'
          ? { ...r, status: 'ACTION_REQUIRED', verificationState: 'CONSENT_DENIED', canUpload: true, userAction: 'You chose not to allow automatic retrieval. You can upload the document yourself.' }
          : r),
      });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('APP-ZZZ-ALPHA-00001');

      const incomeCard = screen.getByRole('heading', { name: 'Income proof' }).closest('article');
      expect(within(incomeCard).getByText('Action required')).toBeInTheDocument();
      expect(within(incomeCard).getByText('You chose not to allow automatic retrieval.')).toBeInTheDocument();
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
      expect(within(incomeCard).queryByRole('button', { name: 'Auto-Fill verified information' })).not.toBeInTheDocument();
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
        requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'INCOME_PROOF' ? { ...r, status: 'WAITING', errorCategory: undefined, verificationState: 'TEMPORARILY_UNAVAILABLE', canUpload: true, userAction: 'Government verification is temporarily unavailable. You can upload the document yourself.' } : r),
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
      expect(within(identityCard).getByRole('button', { name: 'Auto-Fill verified information' })).not.toBeDisabled();
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
    expect(screen.getAllByRole('button', { name: 'Auto-Fill verified information' })).toHaveLength(1);
  });

  describe('verified document view/download (Phase 6F2 Task C)', () => {
    const VALIDATED_APPLICATION = {
      ...APPLICATION_A,
      requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'DOMICILE_PROOF' ? { ...r, status: 'VALIDATED' } : r),
    };

    it('shows View Document and Download only for a VALIDATED document-type requirement, never for a merely-verified attribute', async () => {
      api.applyToScheme.mockResolvedValue(VALIDATED_APPLICATION);
      api.service.mockResolvedValue(SCHEME_A);
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('Zeta Test Assistance Scheme');

      const domicileCard = screen.getByRole('heading', { name: 'Maharashtra domicile' }).closest('article');
      expect(within(domicileCard).getByRole('button', { name: 'View' })).toBeInTheDocument();
      expect(within(domicileCard).getByRole('button', { name: 'Download' })).toBeInTheDocument();

      const identityCard = screen.getByRole('heading', { name: 'Identity' }).closest('article');
      expect(within(identityCard).queryByRole('button', { name: 'View' })).not.toBeInTheDocument();

      const incomeCard = screen.getByRole('heading', { name: 'Income proof' }).closest('article');
      expect(within(incomeCard).queryByRole('button', { name: 'View' })).not.toBeInTheDocument();
    });

    it('clicking View Document renders the citizen-safe content returned by the backend', async () => {
      api.applyToScheme.mockResolvedValue(VALIDATED_APPLICATION);
      api.service.mockResolvedValue(SCHEME_A);
      api.viewDocument.mockResolvedValue({ documentId: 'DOC-1', title: 'Maharashtra Domicile Certificate', requirementCode: 'DOMICILE_PROOF', status: 'VALIDATED', content: 'MAHARASHTRA DOMICILE CERTIFICATE\n\nState: Maharashtra' });
      render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
      await screen.findByText('Zeta Test Assistance Scheme');

      const user = userEvent.setup();
      await user.click(screen.getByRole('button', { name: 'View' }));
      expect(await screen.findByText('Maharashtra Domicile Certificate')).toBeInTheDocument();
      expect(screen.getByText(/State: Maharashtra/)).toBeInTheDocument();
      expect(api.viewDocument).toHaveBeenCalledWith('APP-ZZZ-ALPHA-00001', 'DOMICILE_PROOF');
    });
  });
});

describe('ApplicationFormPage -- where verified information came from', () => {
  const withIncome = patch => ({ ...APPLICATION_A, requirements: APPLICATION_A.requirements.map(r => r.requirementCode === 'INCOME_PROOF' ? { ...r, ...patch } : r) });
  const incomeCard = () => screen.getByRole('heading', { name: 'Income proof' }).closest('article');

  beforeEach(() => {
    api.applyToScheme.mockReset();
    api.service.mockReset();
    api.autoFillRequirement.mockReset();
    api.service.mockResolvedValue(SCHEME_A);
  });

  it('names the department that verified an auto-filled record', async () => {
    api.applyToScheme.mockResolvedValue(withIncome({ status: 'VALIDATED', source: 'Education Department', verifiedAt: new Date().toISOString() }));
    render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
    await screen.findByText('APP-ZZZ-ALPHA-00001');
    expect(within(incomeCard()).getByText(/Auto-filled from department record/)).toBeInTheDocument();
    expect(within(incomeCard()).getByText(/Verified from Education Department/)).toBeInTheDocument();
  });

  it('says an alternate government source verified it when a fallback answered', async () => {
    api.applyToScheme.mockResolvedValue(withIncome({ status: 'VALIDATED', verificationState: 'VERIFIED_VIA_FALLBACK', source: 'Social Welfare Department', alternateSource: true }));
    render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
    await screen.findByText('APP-ZZZ-ALPHA-00001');
    expect(within(incomeCard()).getByText(/Verified through an alternate government source/)).toBeInTheDocument();
    expect(within(incomeCard()).getByText(/Source: Social Welfare Department/)).toBeInTheDocument();
    expect(within(incomeCard()).queryByText(/Verified from Social Welfare Department/)).not.toBeInTheDocument();
  });

  it('labels a citizen upload as uploaded by the citizen, not as department-verified', async () => {
    api.applyToScheme.mockResolvedValue(withIncome({ status: 'VALIDATED', documentId: 'DOC-1', source: 'Revenue Department' }));
    render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
    await screen.findByText('APP-ZZZ-ALPHA-00001');
    expect(within(incomeCard()).getByText(/Uploaded by you/)).toBeInTheDocument();
    expect(within(incomeCard()).queryByText(/Auto-filled from department record/)).not.toBeInTheDocument();
  });

  it('shows "Checking connected government departments" while Auto-Fill runs', async () => {
    api.applyToScheme.mockResolvedValue(APPLICATION_A);
    let finish;
    api.autoFillRequirement.mockReturnValue(new Promise(resolve => { finish = resolve; }));
    render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
    await screen.findByText('APP-ZZZ-ALPHA-00001');
    const user = userEvent.setup();
    await user.click(within(incomeCard()).getByRole('button', { name: 'Auto-Fill verified information' }));
    await user.click(within(incomeCard()).getByRole('button', { name: 'Accept' }));
    expect(await within(incomeCard()).findByText(/Checking connected government departments/)).toBeInTheDocument();
    finish(APPLICATION_A);
  });

  it('keeps the manual-upload fallback when no connected department holds a record', async () => {
    const message = 'No verified record was found in the connected departments. You can upload the document yourself.';
    api.applyToScheme.mockResolvedValue(withIncome({ status: 'FAILED', verificationState: 'NO_RECORD', canUpload: true, userAction: message }));
    render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
    await screen.findByText('APP-ZZZ-ALPHA-00001');
    expect(within(incomeCard()).getByText('No verified record was found in the connected departments.')).toBeInTheDocument();
    // The card really offers what it says: upload and camera, right here.
    expect(within(incomeCard()).getByRole('button', { name: 'Upload document' })).toBeInTheDocument();
    expect(within(incomeCard()).getByRole('button', { name: 'Take photo' })).toBeInTheDocument();
  });
});

describe('ApplicationFormPage -- every card offers the action its message promises', () => {
  const withRequirement = (code, patch) => ({ ...APPLICATION_A, requirements: APPLICATION_A.requirements.map(r => r.requirementCode === code ? { ...r, ...patch } : r) });
  const card = name => screen.getByRole('heading', { name }).closest('article');

  beforeEach(() => {
    api.applyToScheme.mockReset();
    api.service.mockReset();
    api.service.mockResolvedValue(SCHEME_A);
  });

  async function show(application) {
    api.applyToScheme.mockResolvedValue(application);
    render(<ApplicationFormPage schemeId="ZZZ-ALPHA-2099" citizen={CITIZEN} navigate={() => {}} />);
    await screen.findByText('APP-ZZZ-ALPHA-00001');
  }

  it('20: temporarily unavailable offers Retry first, plus Upload and Take photo -- never "no record"', async () => {
    await show(withRequirement('INCOME_PROOF', { status: 'WAITING', verificationState: 'TEMPORARILY_UNAVAILABLE', canUpload: true }));
    const income = card('Income proof');
    expect(within(income).getByText('Government verification is temporarily unavailable.')).toBeInTheDocument();
    expect(within(income).queryByText(/No verified record/)).not.toBeInTheDocument();
    expect(within(income).getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(within(income).getByRole('button', { name: 'Upload document' })).toBeInTheDocument();
    expect(within(income).getByRole('button', { name: 'Take photo' })).toBeInTheDocument();
  });

  it('19: a department record that could not be verified can be evidenced with an upload, right on the card', async () => {
    await show({ ...APPLICATION_A, requirements: [{ requirementCode: 'ACADEMIC_RECORD', displayLabel: 'Academic record', status: 'FAILED', mandatory: true, dataType: 'RECORD', verificationState: 'NO_RECORD', canUpload: true }] });
    const record = card('Academic record');
    await userEvent.setup().click(within(record).getByRole('button', { name: 'Upload document' }));
    expect(within(record).getByRole('button', { name: 'Upload from device' })).toBeInTheDocument();
  });

  it('never promises an upload where none is possible (identity)', async () => {
    await show(withRequirement('IDENTITY', { status: 'FAILED', verificationState: 'NO_RECORD', canUpload: false }));
    const identity = card('Identity');
    expect(within(identity).queryByRole('button', { name: 'Upload document' })).not.toBeInTheDocument();
    expect(within(identity).getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(within(identity).getByText('Please try again in a little while.')).toBeInTheDocument();
  });

  it('low-confidence and ambiguous matches explain why nothing was attached', async () => {
    await show(withRequirement('INCOME_PROOF', { status: 'ACTION_REQUIRED', verificationState: 'LOW_CONFIDENCE', canUpload: true }));
    expect(within(card('Income proof')).getByText("We couldn't verify this record with sufficient confidence.")).toBeInTheDocument();
  });

  it('a department-verified item shows its source and does not push a manual upload', async () => {
    await show(withRequirement('INCOME_PROOF', { status: 'VALIDATED', verificationState: 'VERIFIED', source: 'Revenue Department', canUpload: true }));
    const income = card('Income proof');
    expect(within(income).getByText(/Verified from Revenue Department/)).toBeInTheDocument();
    expect(within(income).queryByRole('button', { name: 'Upload document' })).not.toBeInTheDocument();
  });
});
