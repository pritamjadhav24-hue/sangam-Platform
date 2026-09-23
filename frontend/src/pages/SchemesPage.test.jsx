import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SchemesPage from './SchemesPage';

const MOCK_SCHEMES = [
  { serviceId: 'ZZZ-ALPHA-2099', schemeId: 'ZZZ-ALPHA-2099', name: 'Zeta Test Assistance Scheme', nameMr: 'झेटा चाचणी सहाय्य योजना', department: 'Zeta Test Department', category: 'Zeta Category', description: 'A scheme that only exists in this test to prove the catalogue is data-driven.', enabled: true, synthetic: true },
  { serviceId: 'ZZZ-BETA-2099', schemeId: 'ZZZ-BETA-2099', name: 'Omega Test Support Programme', nameMr: 'ओमेगा चाचणी समर्थन कार्यक्रम', department: 'Omega Test Department', category: 'Omega Category', description: 'A second, differently-categorised scheme for filter testing.', enabled: true, synthetic: true },
];

describe('SchemesPage', () => {
  it('shows a loading state while the shared scheme catalogue has not arrived yet', () => {
    render(<SchemesPage schemes={[]} onViewScheme={() => {}} />);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('renders scheme cards sourced entirely from the shared catalogue prop (requirement 1)', () => {
    render(<SchemesPage schemes={MOCK_SCHEMES} onViewScheme={() => {}} />);
    expect(screen.getByText('Zeta Test Assistance Scheme')).toBeInTheDocument();
    expect(screen.getByText('Omega Test Support Programme')).toBeInTheDocument();
    expect(screen.getByText(/A scheme that only exists in this test/)).toBeInTheDocument();
  });

  it('search filters operate on the provided data, not a hardcoded list (requirement 3)', async () => {
    render(<SchemesPage schemes={MOCK_SCHEMES} onViewScheme={() => {}} />);

    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Search schemes'), 'Omega');

    expect(screen.queryByText('Zeta Test Assistance Scheme')).not.toBeInTheDocument();
    expect(screen.getByText('Omega Test Support Programme')).toBeInTheDocument();
  });

  it('category filter chips are derived from the provided data, not hardcoded, and narrow results', async () => {
    render(<SchemesPage schemes={MOCK_SCHEMES} onViewScheme={() => {}} />);

    const user = userEvent.setup();
    expect(screen.getByRole('button', { name: 'Zeta Category' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Omega Category' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Omega Category' }));
    expect(screen.queryByText('Zeta Test Assistance Scheme')).not.toBeInTheDocument();
    expect(screen.getByText('Omega Test Support Programme')).toBeInTheDocument();
  });

  it('Apply/view-details action receives the selected scheme id dynamically (requirement 6)', async () => {
    const onViewScheme = vi.fn();
    render(<SchemesPage schemes={MOCK_SCHEMES} onViewScheme={onViewScheme} />);

    const user = userEvent.setup();
    const buttons = screen.getAllByRole('button', { name: 'View details' });
    await user.click(buttons[1]);

    expect(onViewScheme).toHaveBeenCalledWith('ZZZ-BETA-2099');
  });
});
