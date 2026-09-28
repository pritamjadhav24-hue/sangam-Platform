import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

// The Admin overview chunk fails to download the first time, then succeeds.
let dashboardImports = 0;
vi.mock('./pages/admin/AdminDashboardPage', () => {
  dashboardImports += 1;
  if (dashboardImports === 1) throw new Error('Failed to fetch dynamically imported module');
  return { default: () => <main><h1>Operations Overview</h1></main> };
});

vi.mock('./api', () => ({
  setSessionToken: vi.fn(),
  setAuthFailureHandler: vi.fn(),
  api: {
    login: vi.fn().mockResolvedValue({ token: 't', user: { userId: 'ADMIN_TEST', name: 'Test Admin', role: 'ADMIN' } }),
    notifications: vi.fn().mockResolvedValue({ notifications: [] }),
    applications: vi.fn().mockResolvedValue({ applications: [] }),
    services: vi.fn().mockResolvedValue({ services: [] }),
  },
}));

import App from './App';

describe('lazy-loaded staff pages', () => {
  it('shows a friendly error with Try again instead of a blank screen when a staff page fails to load, and recovers on retry', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<App />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('User ID'), 'ADMIN_TEST');
    await user.type(screen.getByLabelText('Password'), 'test-only');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('This page could not be loaded');
    expect(alert.textContent).not.toMatch(/Failed to fetch|dynamically imported|Error:|at /);
    expect(screen.getByRole('navigation')).toBeInTheDocument(); // the rest of the app is still there

    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'Operations Overview' })).toBeInTheDocument();
    expect(screen.queryByText('This page could not be loaded')).not.toBeInTheDocument();
    consoleError.mockRestore();
  });
});
