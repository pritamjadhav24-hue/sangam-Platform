import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import LoginPage from './LoginPage';

describe('LoginPage', () => {
  it('is a plain production sign-in: no demo identities, credentials, prototype wording or endorsement', () => {
    const { container } = render(<LoginPage onLogin={vi.fn()} language="en" />);
    expect(container.textContent).not.toMatch(/demo|prototype|SIH|hackathon|@2026|CITIZEN_00|ADMIN_MH|OFFICER_MH/i);
    expect(container.textContent).not.toMatch(/महाराष्ट्र शासन/);
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.getByLabelText('User ID')).toHaveValue('');
    expect(screen.getByLabelText('Password')).toHaveValue('');
  });

  it('signs in with the entered user ID and password', async () => {
    const onLogin = vi.fn().mockResolvedValue(undefined);
    render(<LoginPage onLogin={onLogin} language="en" />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('User ID'), '  someone ');
    await user.type(screen.getByLabelText('Password'), 'secret');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(onLogin).toHaveBeenCalledWith('someone', 'secret');
  });

  it('shows a plain message for wrong credentials, tied to the fields', async () => {
    const error = Object.assign(new Error('Invalid credentials.'), { status: 401 });
    render(<LoginPage onLogin={vi.fn().mockRejectedValue(error)} language="en" />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('User ID'), 'someone');
    await user.type(screen.getByLabelText('Password'), 'wrong');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The user ID or password is incorrect.');
    expect(screen.getByLabelText('Password')).toHaveAttribute('aria-describedby', 'login-error');
  });

  it('is a clean landing page: SANGAM logo and name, no decorative network artefacts', () => {
    const { container } = render(<LoginPage onLogin={vi.fn()} language="en" />);
    expect(screen.getByRole('heading', { level: 1, name: 'SANGAM' })).toBeInTheDocument();
    expect(screen.getByText('Federated Government Interoperability Platform')).toBeInTheDocument();
    expect(container.querySelector('img[src="/brand/sangam-logo-240.webp"]')).not.toBeNull();
    expect(container.querySelector('.network-visual, .network-node')).toBeNull();
  });

  it('offers no guest access unless the server lists guest accounts', async () => {
    render(<LoginPage onLogin={vi.fn()} loadDemoAccounts={vi.fn().mockRejectedValue(Object.assign(new Error('Not found'), { status: 404 }))} language="en" />);
    await Promise.resolve();
    expect(screen.queryByRole('button', { name: 'Continue with a guest account' })).not.toBeInTheDocument();
  });

  it('a guest account signs in through guest sign-in only, with a plain "Sign in" and no demo wording', async () => {
    const onLogin = vi.fn();
    const onDemoLogin = vi.fn().mockResolvedValue(undefined);
    const accounts = [{ citizenId: 'DEMO-CIT-001', name: 'Rahul Kumar', scenario: 'ELIGIBLE', scenarioLabel: 'Eligible citizen — all records verified' }];
    const { container } = render(<LoginPage onLogin={onLogin} onDemoLogin={onDemoLogin} loadDemoAccounts={vi.fn().mockResolvedValue({ accounts })} language="en" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Continue with a guest account' }));
    await user.selectOptions(screen.getByLabelText('Guest account'), 'DEMO-CIT-001');
    expect(screen.getByText('Rahul Kumar')).toBeInTheDocument();
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument(); // no password is ever shown for a guest
    expect(container.textContent).not.toMatch(/demo|demonstration|synthetic|Eligible citizen/i);
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(onDemoLogin).toHaveBeenCalledWith('DEMO-CIT-001');
    expect(onLogin).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Change' }));
    expect(screen.getByLabelText('Password')).toHaveValue('');
  });

  it('shows the four landing backgrounds without captions, place names or credits', () => {
    const { container } = render(<LoginPage onLogin={vi.fn()} language="en" />);
    const photo = container.querySelector('.landing-photo');
    expect(photo.getAttribute('src')).toBe('/images/hero/public-service.webp');
    expect(photo.getAttribute('alt')).toBe('');
    expect(container.textContent).not.toMatch(/credit|photo|Wikimedia|Commons|Delhi|Maharashtra|Pune|Mumbai|Raigad|Connected to department records|purpose-bound/i);
    expect(screen.getByText('Access public services through one connected platform.')).toBeInTheDocument();
  });

  it('shows a session-expired notice passed by the app', () => {
    render(<LoginPage onLogin={vi.fn()} language="en" notice="Your session has expired. Please sign in again." />);
    expect(screen.getByRole('status')).toHaveTextContent('Your session has expired');
  });
});
