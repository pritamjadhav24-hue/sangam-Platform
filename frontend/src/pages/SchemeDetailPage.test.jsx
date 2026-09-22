import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SchemeDetailPage from './SchemeDetailPage';
import { api } from '../api';

vi.mock('../api', () => ({ api: { service: vi.fn() } }));

const SCHEME_A = {
  serviceId: 'ZZZ-ALPHA-2099', schemeId: 'ZZZ-ALPHA-2099', name: 'Zeta Test Assistance Scheme', nameMr: 'झेटा चाचणी सहाय्य योजना',
  department: 'Zeta Test Department', category: 'Zeta Category', description: 'Alpha scheme description text.',
  benefits: 'Alpha benefits text.', eligibility: 'Alpha eligibility text.', enabled: true, synthetic: true,
  requirements: [{ code: 'IDENTITY', label: 'Identity', mandatory: true }],
};

const SCHEME_B = {
  serviceId: 'ZZZ-BETA-2099', schemeId: 'ZZZ-BETA-2099', name: 'Omega Test Support Programme', nameMr: 'ओमेगा चाचणी समर्थन कार्यक्रम',
  department: 'Omega Test Department', category: 'Omega Category', description: 'Beta programme description text.',
  benefits: 'Beta benefits text.', eligibility: 'Beta eligibility text.', enabled: true, synthetic: true,
  requirements: [{ code: 'BIRTH_CERTIFICATE', label: 'Birth certificate', mandatory: true }],
};

describe('SchemeDetailPage', () => {
  beforeEach(() => { api.service.mockReset(); });

  it('shows a loading state before the API responds', async () => {
    let resolvePromise;
    api.service.mockReturnValue(new Promise(resolve => { resolvePromise = resolve; }));
    render(<SchemeDetailPage schemeId="ZZZ-ALPHA-2099" navigate={() => {}} onApply={() => {}} />);
    expect(screen.getByRole('status')).toBeInTheDocument();
    resolvePromise(SCHEME_A);
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  });

  it('dynamically renders the fields returned by the API for the given scheme id (requirement 4)', async () => {
    api.service.mockResolvedValue(SCHEME_A);
    render(<SchemeDetailPage schemeId="ZZZ-ALPHA-2099" navigate={() => {}} onApply={() => {}} />);

    expect(await screen.findByRole('heading', { name: 'Zeta Test Assistance Scheme' })).toBeInTheDocument();
    expect(screen.getByText('Alpha scheme description text.')).toBeInTheDocument();
    expect(screen.getByText('Alpha benefits text.')).toBeInTheDocument();
    expect(screen.getByText('Alpha eligibility text.')).toBeInTheDocument();
    expect(screen.getByText('Identity')).toBeInTheDocument();
    expect(api.service).toHaveBeenCalledWith('ZZZ-ALPHA-2099');
  });

  it('renders genuinely different content for a different scheme id using the same component (requirement 5)', async () => {
    api.service.mockResolvedValue(SCHEME_B);
    render(<SchemeDetailPage schemeId="ZZZ-BETA-2099" navigate={() => {}} onApply={() => {}} />);

    expect(await screen.findByRole('heading', { name: 'Omega Test Support Programme' })).toBeInTheDocument();
    expect(screen.getByText('Beta programme description text.')).toBeInTheDocument();
    expect(screen.queryByText('Alpha scheme description text.')).not.toBeInTheDocument();
    expect(screen.getByText('Birth certificate')).toBeInTheDocument();
  });

  it('shows an error state when the API call fails', async () => {
    api.service.mockRejectedValue(new Error('Configured service not found'));
    render(<SchemeDetailPage schemeId="DOES-NOT-EXIST" navigate={() => {}} onApply={() => {}} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Configured service not found');
  });

  it('Apply receives the dynamically loaded scheme object, not a hardcoded one (requirement 6)', async () => {
    api.service.mockResolvedValue(SCHEME_A);
    const onApply = vi.fn();
    render(<SchemeDetailPage schemeId="ZZZ-ALPHA-2099" navigate={() => {}} onApply={onApply} />);
    await screen.findByRole('heading', { name: 'Zeta Test Assistance Scheme' });

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Apply' }));

    expect(onApply).toHaveBeenCalledWith(SCHEME_A);
  });
});
