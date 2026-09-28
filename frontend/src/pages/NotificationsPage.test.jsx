import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import NotificationsPage from './NotificationsPage';

const NOTIFICATIONS = [
  { notificationId: 'CN-1', type: 'ACTION_REQUIRED', title: 'Action needed', message: 'Your Income Certificate could not be retrieved automatically. Please upload it manually.', applicationId: 'APP-1', requirementCode: 'INCOME_PROOF', read: false, createdAt: '2026-09-23T04:30:00Z' },
  { notificationId: 'CN-2', type: 'DOCUMENT_VERIFIED', title: 'Document verified', message: 'Your Maharashtra Domicile Certificate has been verified.', applicationId: 'APP-1', requirementCode: 'DOMICILE_PROOF', read: true, createdAt: '2026-09-22T10:00:00Z' },
];

const item = title => screen.getByText(title).closest('li');

describe('NotificationsPage', () => {
  it('shows a "caught up" empty state when there are no notifications, never fabricated data', () => {
    render(<NotificationsPage notifications={[]} language="en" />);
    expect(screen.getByText("You're all caught up")).toBeInTheDocument();
    expect(screen.queryByText('CN-1')).not.toBeInTheDocument();
  });

  it('renders real persisted notifications: title, message, time and unread count', () => {
    render(<NotificationsPage notifications={NOTIFICATIONS} language="en" />);
    expect(screen.getByText('Action needed')).toBeInTheDocument();
    expect(screen.getByText(/Income Certificate could not be retrieved/)).toBeInTheDocument();
    expect(screen.getByText('Document verified')).toBeInTheDocument();
    expect(screen.getByText('1 unread')).toBeInTheDocument();
  });

  it('marks unread notifications with a visible "New" label, not colour alone', () => {
    render(<NotificationsPage notifications={NOTIFICATIONS} language="en" />);
    expect(item('Action needed').className).toContain('unread');
    expect(within(item('Action needed')).getByText('New')).toBeInTheDocument();
    expect(item('Document verified').className).not.toContain('unread');
    expect(within(item('Document verified')).queryByText('New')).not.toBeInTheDocument();
  });

  it('"View application" visits the notification and "Mark as read" only marks it', async () => {
    const onVisit = vi.fn();
    const onMarkRead = vi.fn();
    render(<NotificationsPage notifications={NOTIFICATIONS} onVisit={onVisit} onMarkRead={onMarkRead} language="en" />);
    const user = userEvent.setup();
    await user.click(within(item('Action needed')).getByRole('button', { name: 'Mark as read' }));
    expect(onMarkRead).toHaveBeenCalledWith(NOTIFICATIONS[0]);
    expect(onVisit).not.toHaveBeenCalled();
    await user.click(within(item('Action needed')).getByRole('button', { name: /View application/ }));
    expect(onVisit).toHaveBeenCalledWith(NOTIFICATIONS[0]);
  });

  it('offers Mark as read only for unread notifications, and Mark all as read when any are unread', async () => {
    const onMarkRead = vi.fn();
    render(<NotificationsPage notifications={NOTIFICATIONS} onMarkRead={onMarkRead} language="en" />);
    expect(within(item('Document verified')).queryByRole('button', { name: 'Mark as read' })).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Mark all as read' }));
    expect(onMarkRead).toHaveBeenCalledTimes(1);
    expect(onMarkRead).toHaveBeenCalledWith(NOTIFICATIONS[0]);
  });

  it('translates notification text into Marathi via the existing i18n helper', () => {
    render(<NotificationsPage notifications={NOTIFICATIONS} language="mr" />);
    expect(screen.getByText('कृती आवश्यक')).toBeInTheDocument();
    expect(screen.getByText('दस्तऐवज पडताळला')).toBeInTheDocument();
  });
});

describe('NotificationsPage -- administrator (operational) notifications', () => {
  const OPS = [
    { notificationId: 'NTF-1', type: 'PROVIDER_DOWN', title: 'Provider unavailable', message: 'Revenue Sandbox API - Income Certificates is unavailable.', read: false, severity: 'CRITICAL', createdAt: '2026-09-27T10:42:31Z', target: { kind: 'incident', incidentId: 'INC-1', providerId: 'REVENUE-SANDBOX-INCOME' } },
    { notificationId: 'NTF-2', type: 'FALLBACK_ACTIVATED', title: 'Authorized fallback used', message: 'Income proof was verified by Social Welfare.', read: false, severity: 'WARNING', applicationId: 'APP-9', createdAt: '2026-09-27T10:42:32Z', target: { kind: 'application', applicationId: 'APP-9' } },
    { notificationId: 'NTF-3', type: 'INTEGRATION_ERROR', title: 'Integration error', message: 'A department API returned an error.', read: true, severity: 'CRITICAL', createdAt: '2026-09-27T10:43:00Z', target: { kind: 'provider', providerId: 'EDU' } },
  ];

  it('26: leads to the incident, the application or the provider, and marks as read', async () => {
    const onVisit = vi.fn();
    const onMarkRead = vi.fn();
    render(<NotificationsPage notifications={OPS} onVisit={onVisit} onMarkRead={onMarkRead} audience="ADMIN" language="en" />);
    const user = userEvent.setup();
    await user.click(within(item('Provider unavailable')).getByRole('button', { name: /Open incident/ }));
    expect(onVisit).toHaveBeenCalledWith(OPS[0]);
    expect(within(item('Authorized fallback used')).getByRole('button', { name: /View application/ })).toBeInTheDocument();
    expect(within(item('Integration error')).getByRole('button', { name: /Open provider/ })).toBeInTheDocument();
    await user.click(within(item('Authorized fallback used')).getByRole('button', { name: 'Mark as read' }));
    expect(onMarkRead).toHaveBeenCalledWith(OPS[1]);
    expect(screen.getByText('2 unread')).toBeInTheDocument();
    expect(item('Provider unavailable').className).toContain('severity-critical');
  });

  it('describes operational updates when there are none', () => {
    render(<NotificationsPage notifications={[]} audience="ADMIN" language="en" />);
    expect(screen.getByText(/Provider outages and recoveries/)).toBeInTheDocument();
  });
});
