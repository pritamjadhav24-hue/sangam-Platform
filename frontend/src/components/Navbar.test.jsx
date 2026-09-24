import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Navbar from './Navbar';

const CITIZEN = { role: 'CITIZEN', userId: 'SYN-CIT-00001', citizenId: 'SYN-CIT-00001', name: 'Amit Kale' };

const DEMO_CITIZENS = [
  { citizenId: 'SYN-CIT-00001', name: 'Amit Kale', persona: 'JOBSEEKER', district: 'Pune' },
  { citizenId: 'SYN-CIT-00002', name: 'Neha Kale', persona: 'FARMER', district: 'Akola' },
  { citizenId: 'SYN-CIT-00003', name: 'Manisha Gawde', persona: 'BUSINESS_OWNER', district: 'Satara' },
];

describe('Navbar demo citizen switcher', () => {
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

describe('Navbar notifications entry (Phase 6G3 Task 2)', () => {
  it('has exactly one Notifications entry, and no separate bell/popup', () => {
    render(<Navbar page="dashboard" setPage={() => {}} citizen={CITIZEN} notifications={[]} demoCitizens={[]} onDemoSwitch={vi.fn()} />);
    expect(screen.getAllByText('Notifications')).toHaveLength(1);
    expect(document.querySelector('.notification-panel')).not.toBeInTheDocument();
    expect(document.querySelector('.notification-wrap')).not.toBeInTheDocument();
  });

  it('shows an unread-count badge on the Notifications nav item, derived from the notifications prop', () => {
    const notifications = [
      { notificationId: 'CN-1', read: false, title: 'Action needed', message: 'x', createdAt: '2026-09-23T00:00:00Z' },
      { notificationId: 'CN-2', read: true, title: 'Document verified', message: 'y', createdAt: '2026-09-23T00:00:00Z' },
    ];
    render(<Navbar page="dashboard" setPage={() => {}} citizen={CITIZEN} notifications={notifications} demoCitizens={[]} onDemoSwitch={vi.fn()} />);
    const navItem = screen.getByRole('button', { name: /Notifications/ });
    expect(navItem).toHaveTextContent('1');
  });

  it('shows no badge when every notification is read', () => {
    const notifications = [{ notificationId: 'CN-1', read: true, title: 'Document verified', message: 'y', createdAt: '2026-09-23T00:00:00Z' }];
    render(<Navbar page="dashboard" setPage={() => {}} citizen={CITIZEN} notifications={notifications} demoCitizens={[]} onDemoSwitch={vi.fn()} />);
    expect(document.querySelector('.nav-notification-badge')).not.toBeInTheDocument();
  });

  it('clicking the Notifications nav item navigates to the notifications page', async () => {
    const setPage = vi.fn();
    render(<Navbar page="dashboard" setPage={setPage} citizen={CITIZEN} notifications={[]} demoCitizens={[]} onDemoSwitch={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Notifications' }));
    expect(setPage).toHaveBeenCalledWith('notificationsPage');
  });
});

describe('Navbar Admin navigation (final Admin portal structure)', () => {
  const ADMIN = { role: 'ADMIN', userId: 'ADMIN_MH_01', name: 'Admin One' };

  it('shows the complete Admin navigation in order', () => {
    render(<Navbar page="adminDashboard" setPage={() => {}} citizen={ADMIN} notifications={[]} onNotificationSelect={vi.fn()} />);
    const labels = Array.from(document.querySelectorAll('.navlinks button')).map(b => b.textContent);
    expect(labels).toEqual(['Dashboard', 'Applications', 'Providers', 'Analytics', 'Schemes', 'Alerts', 'Audit', 'Profile']);
  });

  it('highlights the parent section while viewing a detail page', () => {
    const { rerender } = render(<Navbar page="adminSchemeDetail" setPage={() => {}} citizen={ADMIN} notifications={[]} onNotificationSelect={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Schemes' })).toHaveClass('active');
    rerender(<Navbar page="adminProviderDetail" setPage={() => {}} citizen={ADMIN} notifications={[]} onNotificationSelect={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Providers' })).toHaveClass('active');
    rerender(<Navbar page="adminApplicationDetail" setPage={() => {}} citizen={ADMIN} notifications={[]} onNotificationSelect={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Applications' })).toHaveClass('active');
  });

  it('navigates to the new Admin modules', async () => {
    const setPage = vi.fn();
    render(<Navbar page="adminDashboard" setPage={setPage} citizen={ADMIN} notifications={[]} onNotificationSelect={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Analytics' }));
    await user.click(screen.getByRole('button', { name: 'Schemes' }));
    await user.click(screen.getByRole('button', { name: 'Profile' }));
    expect(setPage.mock.calls.map(call => call[0])).toEqual(['adminAnalytics', 'adminSchemes', 'adminProfile']);
  });

  it('never shows Admin sections to citizens', () => {
    render(<Navbar page="dashboard" setPage={() => {}} citizen={CITIZEN} notifications={[]} demoCitizens={[]} onDemoSwitch={vi.fn()} />);
    for (const label of ['Analytics', 'Providers', 'Alerts', 'Audit']) {
      expect(screen.queryByRole('button', { name: label })).not.toBeInTheDocument();
    }
  });
});

describe('Navbar Officer/Admin notification bell (regression fix)', () => {
  const OFFICER = { role: 'OFFICER', userId: 'OFFICER_MH_01', name: 'Officer One' };
  const ADMIN = { role: 'ADMIN', userId: 'ADMIN_MH_01', name: 'Admin One' };
  const NOTIFICATIONS = [
    { notificationId: 'NTF-1', read: false, title: 'Application needs review', message: 'x', createdAt: '2026-09-24T00:00:00Z' },
  ];

  it('Officer sees a notification bell with an unread badge, not a nav-item badge', () => {
    render(<Navbar page="officer" setPage={() => {}} citizen={OFFICER} notifications={NOTIFICATIONS} onNotificationSelect={vi.fn()} />);
    expect(document.querySelector('.notification-wrap')).toBeInTheDocument();
    expect(document.querySelector('.notification-badge')).toHaveTextContent('1');
    // Officer/Admin never get the citizen-style nav-item badge.
    expect(document.querySelector('.nav-notification-badge')).not.toBeInTheDocument();
  });

  it('Admin also sees the restored notification bell', () => {
    render(<Navbar page="health" setPage={() => {}} citizen={ADMIN} notifications={NOTIFICATIONS} onNotificationSelect={vi.fn()} />);
    expect(document.querySelector('.notification-wrap')).toBeInTheDocument();
  });

  it('opening the bell shows the notification list and clicking one calls onNotificationSelect', async () => {
    const onNotificationSelect = vi.fn();
    render(<Navbar page="officer" setPage={() => {}} citizen={OFFICER} notifications={NOTIFICATIONS} onNotificationSelect={onNotificationSelect} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Notifications/ }));
    expect(screen.getByText('Application needs review')).toBeInTheDocument();
    await user.click(screen.getByText('Application needs review'));
    expect(onNotificationSelect).toHaveBeenCalledWith(NOTIFICATIONS[0]);
  });

  it('clicking outside the open bell closes it', async () => {
    render(<>
      <Navbar page="officer" setPage={() => {}} citizen={OFFICER} notifications={NOTIFICATIONS} onNotificationSelect={vi.fn()} />
      <button>elsewhere</button>
    </>);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Notifications/ }));
    expect(document.querySelector('.notification-panel')).toBeInTheDocument();
    await user.click(screen.getByText('elsewhere'));
    expect(document.querySelector('.notification-panel')).not.toBeInTheDocument();
  });

  it('Citizens still never render the bell popup, only Officer/Admin do', () => {
    render(<Navbar page="dashboard" setPage={() => {}} citizen={CITIZEN} notifications={NOTIFICATIONS} onNotificationSelect={vi.fn()} demoCitizens={[]} onDemoSwitch={vi.fn()} />);
    expect(document.querySelector('.notification-wrap')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Notifications/ })).toHaveTextContent('1');
  });
});

describe('Navbar language switch when signed out', () => {
  it('lets a signed-out visitor change the language', async () => {
    const onLanguageChange = vi.fn();
    render(<Navbar page="dashboard" setPage={() => {}} language="mr" onLanguageChange={onLanguageChange} />);
    await userEvent.click(screen.getByLabelText('Change language'));
    expect(onLanguageChange).toHaveBeenCalledWith('en');
  });
});
