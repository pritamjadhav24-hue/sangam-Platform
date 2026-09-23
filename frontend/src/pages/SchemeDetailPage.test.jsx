import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SchemeDetailPage from './SchemeDetailPage';

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

const SCHEMES = [SCHEME_A, SCHEME_B];

describe('SchemeDetailPage', () => {
  it('shows a loading state while the shared scheme catalogue has not arrived yet', () => {
    render(<SchemeDetailPage schemeId="ZZZ-ALPHA-2099" schemes={[]} navigate={() => {}} onApply={() => {}} />);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('renders the fields for the given scheme id from the already-loaded catalogue, without a per-scheme request (requirement 4)', () => {
    render(<SchemeDetailPage schemeId="ZZZ-ALPHA-2099" schemes={SCHEMES} navigate={() => {}} onApply={() => {}} />);

    expect(screen.getByRole('heading', { name: 'Zeta Test Assistance Scheme' })).toBeInTheDocument();
    expect(screen.getByText('Alpha scheme description text.')).toBeInTheDocument();
    expect(screen.getByText('Alpha benefits text.')).toBeInTheDocument();
    expect(screen.getByText('Alpha eligibility text.')).toBeInTheDocument();
    expect(screen.getByText('Identity')).toBeInTheDocument();
  });

  it('renders genuinely different content for a different scheme id using the same component (requirement 5)', () => {
    render(<SchemeDetailPage schemeId="ZZZ-BETA-2099" schemes={SCHEMES} navigate={() => {}} onApply={() => {}} />);

    expect(screen.getByRole('heading', { name: 'Omega Test Support Programme' })).toBeInTheDocument();
    expect(screen.getByText('Beta programme description text.')).toBeInTheDocument();
    expect(screen.queryByText('Alpha scheme description text.')).not.toBeInTheDocument();
    expect(screen.getByText('Birth certificate')).toBeInTheDocument();
  });

  it('shows a not-found state for a scheme id absent from the catalogue', () => {
    render(<SchemeDetailPage schemeId="DOES-NOT-EXIST" schemes={SCHEMES} navigate={() => {}} onApply={() => {}} />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('Apply receives the actual scheme object from the catalogue, not a hardcoded one (requirement 6)', async () => {
    const onApply = vi.fn();
    render(<SchemeDetailPage schemeId="ZZZ-ALPHA-2099" schemes={SCHEMES} navigate={() => {}} onApply={onApply} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Apply' }));

    expect(onApply).toHaveBeenCalledWith(SCHEME_A);
  });
});
