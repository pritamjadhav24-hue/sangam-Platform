import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DepartmentHealthPanel from './DepartmentHealthPanel';

const department = (key, name, status, extra = {}) => ({
  key, name, nameMr: name, headline: true, status, simulatedOutage: false, latencyMs: 12, lastSuccessfulVerification: null,
  supportedRequirements: [], activeIncidents: 0, fallbackUsage: { servedAsFallback: 0, fallbacksTriggered: 0 },
  affectedApplications: 0, affectedCitizens: 0,
  providers: [{ providerId: `${key}-P`, name: `${name} API`, status, requirements: [{ requirementCode: `${key}_REQ`, priority: 10, role: 'PRIMARY' }] }],
  ...extra,
});

const DATA = {
  platform: { name: 'SANGAM', status: 'HEALTHY' },
  departments: [
    department('REVENUE', 'Revenue Department', 'UNAVAILABLE', { activeIncidents: 2, affectedApplications: 3, affectedCitizens: 2 }),
    department('EDUCATION', 'Education Department', 'AVAILABLE'),
    department('SOCIAL_WELFARE', 'Social Welfare Department', 'AVAILABLE', { fallbackUsage: { servedAsFallback: 1, fallbacksTriggered: 0 } }),
  ],
  departmentsNotHealthy: ['Revenue Department'],
};

describe('DepartmentHealthPanel', () => {
  it('shows each department on its own, with the SANGAM platform still healthy', async () => {
    render(<DepartmentHealthPanel api={{ adminDepartments: vi.fn().mockResolvedValue(DATA) }} />);
    const revenue = (await screen.findByRole('heading', { name: 'Revenue Department' })).closest('article');
    expect(within(revenue).getByText('Unavailable')).toBeInTheDocument();
    expect(within(revenue).getByText('3 applications · 2 citizens')).toBeInTheDocument();
    const education = screen.getByRole('heading', { name: 'Education Department' }).closest('article');
    expect(within(education).getByText('Available')).toBeInTheDocument();
    expect(screen.getByText('SANGAM platform').closest('.department-pill')).toHaveTextContent('Available');
  });

  it('simulates an outage for a whole department and reflects the returned state', async () => {
    const setAvailability = vi.fn().mockResolvedValue({ ...DATA, departments: DATA.departments.map(item => item.key === 'EDUCATION' ? { ...item, status: 'UNAVAILABLE', simulatedOutage: true } : item) });
    render(<DepartmentHealthPanel api={{ adminDepartments: vi.fn().mockResolvedValue(DATA), adminSetDepartmentAvailability: setAvailability }} />);
    const education = (await screen.findByRole('heading', { name: 'Education Department' })).closest('article');
    await userEvent.setup().click(within(education).getByRole('button', { name: 'Simulate outage' }));
    expect(setAvailability).toHaveBeenCalledWith('EDUCATION', false);
    expect(await within(screen.getByRole('heading', { name: 'Education Department' }).closest('article')).findByRole('button', { name: 'Restore department' })).toBeInTheDocument();
  });

  it('never offers "Restore" for a real (not simulated) outage, and its button simulates rather than restores', async () => {
    const setAvailability = vi.fn().mockResolvedValue(DATA);
    render(<DepartmentHealthPanel api={{ adminDepartments: vi.fn().mockResolvedValue(DATA), adminSetDepartmentAvailability: setAvailability }} />);
    const revenue = (await screen.findByRole('heading', { name: 'Revenue Department' })).closest('article');
    expect(within(revenue).queryByRole('button', { name: 'Restore department' })).not.toBeInTheDocument();
    await userEvent.setup().click(within(revenue).getByRole('button', { name: 'Simulate outage' }));
    expect(setAvailability).toHaveBeenCalledWith('REVENUE', false);
  });
});
