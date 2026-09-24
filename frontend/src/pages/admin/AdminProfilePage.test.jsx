import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import AdminProfilePage from './AdminProfilePage';

const PROFILE = {
  user: { userId: 'ADMIN_MH_01', name: 'Platform Administrator', role: 'ADMIN' },
  session: { issuedAt: '2026-09-24T10:00:00+00:00', expiresAt: '2026-09-24T10:30:00+00:00', lifetimeSeconds: 1800, sessionRef: 'abc123…' },
  access: {
    roles: ['CITIZEN', 'OFFICER', 'ADMIN'], mutablePermissions: false,
    areas: [
      { area: '/api/admin', endpoints: 24, public: 0, byRole: { ADMIN: 24 } },
      { area: '/api/officer', endpoints: 5, public: 0, byRole: { OFFICER: 5, ADMIN: 2 } },
    ],
  },
};

describe('AdminProfilePage', () => {
  it('shows identity, session and the read-only effective access model', async () => {
    render(<AdminProfilePage api={{ adminProfile: vi.fn().mockResolvedValue(PROFILE) }} />);
    await waitFor(() => expect(screen.getByText('Platform Administrator')).toBeInTheDocument());
    expect(screen.getByText('ADMIN_MH_01')).toBeInTheDocument();
    expect(screen.getByText('Admin operations console')).toBeInTheDocument();
    expect(screen.getByText('2 of 5')).toBeInTheDocument();
    expect(screen.getByText(/permissions are not editable at runtime/)).toBeInTheDocument();
    // No fake permission toggles.
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });

  it('shows an understandable error when the profile cannot load', async () => {
    render(<AdminProfilePage api={{ adminProfile: vi.fn().mockRejectedValue(new Error('Role CITIZEN is not allowed for this resource.')) }} />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('not allowed'));
  });
});
