import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import NotificationsPage from './NotificationsPage';

const NOTIFICATIONS = [
  { notificationId: 'CN-1', type: 'ACTION_REQUIRED', title: 'Action needed', message: 'Your Income Certificate could not be retrieved automatically. Please upload it manually.', applicationId: 'APP-1', requirementCode: 'INCOME_PROOF', read: false, createdAt: '2026-09-23T04:30:00Z' },
  { notificationId: 'CN-2', type: 'DOCUMENT_VERIFIED', title: 'Document verified', message: 'Your Maharashtra Domicile Certificate has been verified.', applicationId: 'APP-1', requirementCode: 'DOMICILE_PROOF', read: true, createdAt: '2026-09-22T10:00:00Z' },
];

describe('NotificationsPage (Phase 6G3 Task 1)', () => {
  it('shows a "caught up" empty state when there are no notifications, never fabricated data', () => {
    render(<NotificationsPage notifications={[]} onSelect={vi.fn()} language="en" />);
    expect(screen.getByText("You're all caught up")).toBeInTheDocument();
    expect(screen.queryByText('CN-1')).not.toBeInTheDocument();
  });

  it('renders real persisted notifications: title, message, unread state', () => {
    render(<NotificationsPage notifications={NOTIFICATIONS} onSelect={vi.fn()} language="en" />);
    expect(screen.getByText('Action needed')).toBeInTheDocument();
    expect(screen.getByText(/Income Certificate could not be retrieved/)).toBeInTheDocument();
    expect(screen.getByText('Document verified')).toBeInTheDocument();
  });

  it('visually distinguishes unread from read notifications', () => {
    render(<NotificationsPage notifications={NOTIFICATIONS} onSelect={vi.fn()} language="en" />);
    const unreadItem = screen.getByText('Action needed').closest('button');
    const readItem = screen.getByText('Document verified').closest('button');
    expect(unreadItem.className).toContain('unread');
    expect(readItem.className).not.toContain('unread');
  });

  it('clicking a notification calls onSelect with that notification', async () => {
    const onSelect = vi.fn();
    render(<NotificationsPage notifications={NOTIFICATIONS} onSelect={onSelect} language="en" />);
    const user = userEvent.setup();
    await user.click(screen.getByText('Action needed'));
    expect(onSelect).toHaveBeenCalledWith(NOTIFICATIONS[0]);
  });

  it('translates notification text into Marathi via the existing i18n helper', () => {
    render(<NotificationsPage notifications={NOTIFICATIONS} onSelect={vi.fn()} language="mr" />);
    expect(screen.getByText('कृती आवश्यक')).toBeInTheDocument();
    expect(screen.getByText('दस्तऐवज पडताळला')).toBeInTheDocument();
  });
});
