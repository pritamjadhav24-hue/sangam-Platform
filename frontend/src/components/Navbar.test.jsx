import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Navbar from './Navbar';

const CITIZEN = { role: 'CITIZEN', userId: 'SYN-CIT-00001', citizenId: 'SYN-CIT-00001', name: 'Amit Kale' };

describe('Navbar production presentation', () => {
  it('shows no demo/prototype controls or wording for any role', () => {
    for (const citizen of [CITIZEN, { role: 'OFFICER', userId: 'OFFICER_MH_01', name: 'Officer' }, { role: 'ADMIN', userId: 'ADMIN_MH_01', name: 'Admin' }]) {
      const { container, unmount } = render(<Navbar page="dashboard" setPage={() => {}} citizen={citizen} notifications={[]} />);
      expect(container.textContent).not.toMatch(/demo|prototype|SIH|hackathon/i);
      expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
      unmount();
    }
  });

  it('marks the current page for assistive technology', () => {
    render(<Navbar page="schemes" setPage={() => {}} citizen={CITIZEN} notifications={[]} />);
    expect(screen.getByRole('button', { name: 'Schemes' })).toHaveAttribute('aria-current', 'page');
  });
});

describe('Navbar notifications entry (Phase 6G3 Task 2)', () => {
  it('has exactly one Notifications entry, and no separate bell/popup', () => {
    render(<Navbar page="dashboard" setPage={() => {}} citizen={CITIZEN} notifications={[]} />);
    expect(screen.getAllByText('Notifications')).toHaveLength(1);
    expect(document.querySelector('.notification-panel')).not.toBeInTheDocument();
    expect(document.querySelector('.notification-wrap')).not.toBeInTheDocument();
  });

  it('shows an unread-count badge on the Notifications nav item, derived from the notifications prop', () => {
    const notifications = [
      { notificationId: 'CN-1', read: false, title: 'Action needed', message: 'x', createdAt: '2026-09-23T00:00:00Z' },
      { notificationId: 'CN-2', read: true, title: 'Document verified', message: 'y', createdAt: '2026-09-23T00:00:00Z' },
    ];
    render(<Navbar page="dashboard" setPage={() => {}} citizen={CITIZEN} notifications={notifications} />);
    const navItem = screen.getByRole('button', { name: /Notifications/ });
    expect(navItem).toHaveTextContent('1');
  });

  it('shows no badge when every notification is read', () => {
    const notifications = [{ notificationId: 'CN-1', read: true, title: 'Document verified', message: 'y', createdAt: '2026-09-23T00:00:00Z' }];
    render(<Navbar page="dashboard" setPage={() => {}} citizen={CITIZEN} notifications={notifications} />);
    expect(document.querySelector('.nav-notification-badge')).not.toBeInTheDocument();
  });

  it('clicking the Notifications nav item navigates to the notifications page', async () => {
    const setPage = vi.fn();
    render(<Navbar page="dashboard" setPage={setPage} citizen={CITIZEN} notifications={[]} />);
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
    expect(labels).toEqual(['Overview', 'Applications', 'Providers', 'Activity', 'Analytics', 'Schemes', 'Incidents', 'Audit', 'Profile']);
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
    render(<Navbar page="dashboard" setPage={() => {}} citizen={CITIZEN} notifications={[]} />);
    for (const label of ['Analytics', 'Providers', 'Incidents', 'Audit']) {
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
    render(<Navbar page="dashboard" setPage={() => {}} citizen={CITIZEN} notifications={NOTIFICATIONS} onNotificationSelect={vi.fn()} />);
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

describe('Navbar -- administrator notification bell', () => {
  const ADMIN_USER = { userId: 'ADMIN_MH_01', name: 'Platform Administrator', role: 'ADMIN' };
  const NOTES = [
    { notificationId: 'NTF-1', type: 'PROVIDER_DOWN', title: 'Provider unavailable', message: 'Revenue is unavailable.', read: false, createdAt: new Date().toISOString(), target: { kind: 'incident', incidentId: 'INC-1' } },
    { notificationId: 'NTF-2', type: 'FALLBACK_ACTIVATED', title: 'Authorized fallback used', message: 'Income verified by Social Welfare.', read: true, createdAt: new Date().toISOString(), target: { kind: 'application', applicationId: 'APP-1' } },
  ];

  it('shows the unread count, typed items with readable times, mark-all and opens what a notice is about', async () => {
    const onNotificationSelect = vi.fn();
    const onMarkAllRead = vi.fn();
    const setPage = vi.fn();
    render(<Navbar page="adminDashboard" setPage={setPage} citizen={ADMIN_USER} notifications={NOTES} onNotificationSelect={onNotificationSelect} onMarkAllRead={onMarkAllRead} />);
    const user = userEvent.setup();
    const bell = screen.getByRole('button', { name: 'Notifications' });
    expect(bell).toHaveTextContent('1');
    await user.click(bell);
    expect(screen.getAllByText(/^Today, /).length).toBe(2);
    await user.click(screen.getByRole('button', { name: /Mark all as read/ }));
    expect(onMarkAllRead).toHaveBeenCalled();
    await user.click(screen.getByText('Provider unavailable'));
    expect(onNotificationSelect).toHaveBeenCalledWith(NOTES[0]);
    await user.click(bell);
    await user.click(screen.getByRole('button', { name: 'View all notifications' }));
    expect(setPage).toHaveBeenCalledWith('notificationsPage');
  });

  it('never shows a demo badge in the navigation', () => {
    render(<Navbar page="dashboard" setPage={vi.fn()} citizen={{ citizenId: 'DEMO-CIT-001', name: 'Rahul Kumar', role: 'CITIZEN', isPublicDemo: true }} notifications={[]} />);
    expect(screen.queryByText(/Demo account/i)).not.toBeInTheDocument();
    expect(document.querySelector('.demo-badge')).toBeNull();
  });
});
