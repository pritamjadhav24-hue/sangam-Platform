import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import LoginPage from './LoginPage';

describe('LoginPage', () => {
  it('never ships a password in the UI or pre-fills one', () => {
    const { container } = render(<LoginPage onLogin={vi.fn()} language="en" />);
    expect(container.textContent).not.toMatch(/@2026/);
    expect(container.querySelector('input[type="password"]').value).toBe('');
  });

  it('hides the demo citizen sign-in unless the backend enables demo switching', () => {
    render(<LoginPage onLogin={vi.fn()} language="en" demoCitizens={[]} onDemoSwitch={vi.fn()} />);
    expect(screen.queryByLabelText('Continue as a demo citizen')).toBeNull();
  });

  it('signs in as the chosen demo citizen without a password', () => {
    const onDemoSwitch = vi.fn().mockResolvedValue(undefined);
    render(<LoginPage onLogin={vi.fn()} language="en" demoCitizens={[{ citizenId: 'SYN-CIT-00002', name: 'Neha Kale', persona: 'FARMER' }]} onDemoSwitch={onDemoSwitch} />);
    fireEvent.change(screen.getByLabelText('Continue as a demo citizen'), { target: { value: 'SYN-CIT-00002' } });
    expect(onDemoSwitch).toHaveBeenCalledWith('SYN-CIT-00002');
  });
});
