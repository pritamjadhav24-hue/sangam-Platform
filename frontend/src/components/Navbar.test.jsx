import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Navbar from './Navbar';
import { api } from '../api';

vi.mock('../api', () => ({ api: { notifications: vi.fn(), markNotificationRead: vi.fn() } }));

const CITIZEN = { role: 'CITIZEN', userId: 'SYN-CIT-00001', citizenId: 'SYN-CIT-00001', name: 'Amit Kale' };

const DEMO_CITIZENS = [
  { citizenId: 'SYN-CIT-00001', name: 'Amit Kale', persona: 'JOBSEEKER', district: 'Pune' },
  { citizenId: 'SYN-CIT-00002', name: 'Neha Kale', persona: 'FARMER', district: 'Akola' },
  { citizenId: 'SYN-CIT-00003', name: 'Manisha Gawde', persona: 'BUSINESS_OWNER', district: 'Satara' },
];

describe('Navbar demo citizen switcher', () => {
  beforeEach(() => {
    api.notifications.mockResolvedValue({ notifications: [] });
  });

  it('does not render the switcher when the backend returns no demo citizens', () => {
    render(<Navbar page="dashboard" setPage={() => {}} citizen={CITIZEN} demoCitizens={[]} onDemoSwitch={vi.fn()} />);
    expect(screen.queryByLabelText('Switch demo citizen')).not.toBeInTheDocument();
    expect(screen.queryByText('DEMO')).not.toBeInTheDocument();
  });

  it('renders a clearly labeled DEMO switcher populated from the backend-provided list, not a hardcoded one', () => {
    render(<Navbar page="dashboard" setPage={() => {}} citizen={CITIZEN} demoCitizens={DEMO_CITIZENS} onDemoSwitch={vi.fn()} />);
    expect(screen.getByText('DEMO')).toBeInTheDocument();
    const select = screen.getByLabelText('Switch demo citizen');
    const options = Array.from(select.querySelectorAll('option')).map(o => o.textContent);
    expect(options.some(text => text.includes('Neha Kale'))).toBe(true);
    expect(options.some(text => text.includes('Manisha Gawde'))).toBe(true);
  });

  it('the currently signed-in citizen cannot re-select themselves', () => {
    render(<Navbar page="dashboard" setPage={() => {}} citizen={CITIZEN} demoCitizens={DEMO_CITIZENS} onDemoSwitch={vi.fn()} />);
    const select = screen.getByLabelText('Switch demo citizen');
    const ownOption = Array.from(select.querySelectorAll('option')).find(o => o.value === 'SYN-CIT-00001');
    expect(ownOption.disabled).toBe(true);
  });

  it('selecting a different citizen calls onDemoSwitch with that real citizen id', async () => {
    const onDemoSwitch = vi.fn().mockResolvedValue(undefined);
    render(<Navbar page="dashboard" setPage={() => {}} citizen={CITIZEN} demoCitizens={DEMO_CITIZENS} onDemoSwitch={onDemoSwitch} />);
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText('Switch demo citizen'), 'SYN-CIT-00002');
    expect(onDemoSwitch).toHaveBeenCalledWith('SYN-CIT-00002');
  });

  it('never renders the switcher for a non-citizen role', () => {
    render(<Navbar page="officer" setPage={() => {}} citizen={{ role: 'OFFICER', userId: 'OFFICER_MH_01', name: 'Officer' }} demoCitizens={DEMO_CITIZENS} onDemoSwitch={vi.fn()} />);
    expect(screen.queryByLabelText('Switch demo citizen')).not.toBeInTheDocument();
  });
});
