import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SchemesPage from './SchemesPage';
import { api } from '../api';

vi.mock('../api', () => ({ api: { services: vi.fn() } }));

const MOCK_SCHEMES = [
  { serviceId: 'ZZZ-ALPHA-2099', schemeId: 'ZZZ-ALPHA-2099', name: 'Zeta Test Assistance Scheme', nameMr: 'झेटा चाचणी सहाय्य योजना', department: 'Zeta Test Department', category: 'Zeta Category', description: 'A scheme that only exists in this test to prove the catalogue is API-driven.', enabled: true, synthetic: true },
  { serviceId: 'ZZZ-BETA-2099', schemeId: 'ZZZ-BETA-2099', name: 'Omega Test Support Programme', nameMr: 'ओमेगा चाचणी समर्थन कार्यक्रम', department: 'Omega Test Department', category: 'Omega Category', description: 'A second, differently-categorised scheme for filter testing.', enabled: true, synthetic: true },
];

describe('SchemesPage', () => {
  beforeEach(() => { api.services.mockReset(); });

  it('shows a loading state before the API responds', async () => {
    let resolvePromise;
    api.services.mockReturnValue(new Promise(resolve => { resolvePromise = resolve; }));
    render(<SchemesPage onViewScheme={() => {}} />);
    expect(screen.getByRole('status')).toBeInTheDocument();
    resolvePromise({ services: [] });
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  });

  it('renders scheme cards sourced entirely from the API response (requirement 1)', async () => {
    api.services.mockResolvedValue({ services: MOCK_SCHEMES });
    render(<SchemesPage onViewScheme={() => {}} />);
    expect(await screen.findByText('Zeta Test Assistance Scheme')).toBeInTheDocument();
    expect(screen.getByText('Omega Test Support Programme')).toBeInTheDocument();
    expect(screen.getByText(/A scheme that only exists in this test/)).toBeInTheDocument();
  });

  it('shows an empty state when the API returns no schemes', async () => {
    api.services.mockResolvedValue({ services: [] });
    render(<SchemesPage onViewScheme={() => {}} />);
    await waitFor(() => expect(screen.getByText(/No results found/)).toBeInTheDocument());
  });

  it('shows an error state when the API call fails', async () => {
    api.services.mockRejectedValue(new Error('The service could not complete this request.'));
    render(<SchemesPage onViewScheme={() => {}} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('The service could not complete this request.');
  });

  it('search filters operate on the fetched API data, not a hardcoded list (requirement 3)', async () => {
    api.services.mockResolvedValue({ services: MOCK_SCHEMES });
    render(<SchemesPage onViewScheme={() => {}} />);
    await screen.findByText('Zeta Test Assistance Scheme');

    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Search schemes'), 'Omega');

    expect(screen.queryByText('Zeta Test Assistance Scheme')).not.toBeInTheDocument();
    expect(screen.getByText('Omega Test Support Programme')).toBeInTheDocument();
  });

  it('category filter chips are derived from the API response, not hardcoded, and narrow results', async () => {
    api.services.mockResolvedValue({ services: MOCK_SCHEMES });
    render(<SchemesPage onViewScheme={() => {}} />);
    await screen.findByText('Zeta Test Assistance Scheme');

    const user = userEvent.setup();
    expect(screen.getByRole('button', { name: 'Zeta Category' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Omega Category' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Omega Category' }));
    expect(screen.queryByText('Zeta Test Assistance Scheme')).not.toBeInTheDocument();
    expect(screen.getByText('Omega Test Support Programme')).toBeInTheDocument();
  });

  it('Apply/view-details action receives the selected scheme id dynamically (requirement 6)', async () => {
    api.services.mockResolvedValue({ services: MOCK_SCHEMES });
    const onViewScheme = vi.fn();
    render(<SchemesPage onViewScheme={onViewScheme} />);
    await screen.findByText('Omega Test Support Programme');

    const user = userEvent.setup();
    const buttons = screen.getAllByRole('button', { name: 'View details' });
    await user.click(buttons[1]);

    expect(onViewScheme).toHaveBeenCalledWith('ZZZ-BETA-2099');
  });
});
