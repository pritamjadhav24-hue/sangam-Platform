import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EmptyState, StatusPill, ToastProvider, Tooltip, useToast } from './ui';

const SRC = resolve(__dirname, '..');
const css = readFileSync(resolve(SRC, 'design-system.css'), 'utf8');

function Trigger() {
  const toast = useToast();
  return <button onClick={() => toast({ tone: 'success', title: 'Revenue Department restored' })}>Restore</button>;
}

describe('shared UI kit and design system', () => {
  it('toasts announce politely and can be dismissed', async () => {
    render(<ToastProvider><Trigger /></ToastProvider>);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Restore' }));
    expect(screen.getByText('Revenue Department restored')).toBeInTheDocument();
    expect(screen.getByText('Revenue Department restored').closest('[aria-live]')).toHaveAttribute('aria-live', 'polite');
    await user.click(screen.getByRole('button', { name: 'Dismiss notification' }));
    expect(screen.queryByText('Revenue Department restored')).not.toBeInTheDocument();
  });

  it('status is always text plus colour, never colour alone', () => {
    render(<><StatusPill status="UNAVAILABLE" /><StatusPill status="AUTHORIZED_FALLBACK" label="Authorized fallback" /></>);
    expect(screen.getByText('Unavailable').className).toContain('tone-bad');
    expect(screen.getByText('Authorized fallback').className).toContain('tone-warn');
  });

  it('tooltips are reachable by keyboard and described to assistive technology', async () => {
    render(<Tooltip text="Authorized only when Revenue cannot answer"><button>Policy</button></Tooltip>);
    await userEvent.setup().tab();
    expect(screen.getByRole('tooltip')).toHaveClass('open');
    expect(screen.getByRole('button', { name: 'Policy' }).parentElement).toHaveAttribute('aria-describedby', screen.getByRole('tooltip').id);
  });

  it('empty states explain themselves', () => {
    render(<EmptyState title="No exchanges yet" message="Auto-Fill activity appears here." />);
    expect(screen.getByText('No exchanges yet')).toBeInTheDocument();
  });

  it('28: one global layer defines focus, hover, active and disabled states for every button style', () => {
    expect(css).toMatch(/:focus-visible/);
    ['.outline:not(:disabled):hover', '.primary:not(:disabled):active', '.primary:disabled', '.card.interactive:hover', 'table tbody tr:hover', 'prefers-reduced-motion']
      .forEach(rule => expect(css).toContain(rule));
    const main = readFileSync(resolve(SRC, 'main.jsx'), 'utf8');
    expect(main.indexOf("./design-system.css")).toBeGreaterThan(main.indexOf("./sangam.css"));
    expect(main).toContain('<ToastProvider>');
  });

  it('29: citizen and admin pages are built from the same shared components', () => {
    const adminPages = readdirSync(resolve(SRC, 'pages/admin')).filter(name => name.endsWith('Page.jsx'));
    const usingKit = adminPages.filter(name => readFileSync(resolve(SRC, 'pages/admin', name), 'utf8').includes("components/ui'"));
    expect(usingKit.length).toBeGreaterThanOrEqual(8);
    expect(readFileSync(resolve(SRC, 'pages/ApplicationFormPage.jsx'), 'utf8')).toContain("components/ui'");
  });
});
