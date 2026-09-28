import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminActivityPage from './AdminActivityPage';

const EXCHANGE = {
  applicationId: 'SCH-MH-2026-00146', requirementCode: 'INCOME_PROOF', requirementLabel: 'Income proof',
  consumerDepartment: 'Higher Education Department', targetDepartment: 'Social Welfare Department',
  startedAt: '2026-09-27T10:42:31Z', completedAt: '2026-09-27T10:42:32Z', outcome: 'AUTO_FILLED_VIA_FALLBACK', fallbackUsed: true,
  steps: [
    { at: '2026-09-27T10:42:31Z', stage: 'REQUEST', title: 'Higher Education Department application requested Income proof', status: 'info', actor: 'Higher Education Department', target: 'SANGAM' },
    { at: '2026-09-27T10:42:31Z', stage: 'PROVIDER_UNAVAILABLE', title: 'Revenue Department unavailable — skipped (incident open)', status: 'fail' },
    { at: '2026-09-27T10:42:31Z', stage: 'FALLBACK_POLICY', title: 'Fallback policy evaluated — Social Welfare Department is an authorized fallback for this requirement', status: 'warn' },
    { at: '2026-09-27T10:42:32Z', stage: 'ENTITY_RESOLUTION', title: 'Entity resolution → Strong match', status: 'ok', method: 'demographic', confidence: 1 },
    { at: '2026-09-27T10:42:32Z', stage: 'RESULT', title: 'Auto-Fill completed via authorized fallback', status: 'warn' },
  ],
};

describe('AdminActivityPage', () => {
  it('shows each exchange as requesting department → SANGAM → provider department, with its steps', async () => {
    const onOpenApplication = vi.fn();
    render(<AdminActivityPage api={{ adminActivity: vi.fn().mockResolvedValue({ exchanges: [EXCHANGE], total: 1, summary: { viaFallback: 1 } }) }} onOpenApplication={onOpenApplication} />);
    const card = (await screen.findByRole('heading', { name: 'Income proof' })).closest('article');
    const route = within(card).getByLabelText('Exchange route');
    expect(route).toHaveTextContent('Higher Education Department');
    expect(route).toHaveTextContent('SANGAM');
    expect(route).toHaveTextContent('Social Welfare Department');
    expect(within(card).getByText('Auto-filled via authorized fallback')).toBeInTheDocument();
    expect(within(card).getByText(/Social Welfare Department is an authorized fallback/)).toBeInTheDocument();
    expect(within(card).getByText(/Found by demographic/)).toBeInTheDocument();
    await userEvent.setup().click(within(card).getByRole('button', { name: EXCHANGE.applicationId }));
    expect(onOpenApplication).toHaveBeenCalledWith(EXCHANGE.applicationId);
  });

  it('explains what will appear when there has been no activity yet', async () => {
    render(<AdminActivityPage api={{ adminActivity: vi.fn().mockResolvedValue({ exchanges: [], total: 0, summary: {} }) }} />);
    expect(await screen.findByText('No exchanges yet')).toBeInTheDocument();
  });

  it('never renders identity or record values -- only what the sanitized trace carries', async () => {
    render(<AdminActivityPage api={{ adminActivity: vi.fn().mockResolvedValue({ exchanges: [EXCHANGE], total: 1, summary: {} }) }} />);
    await screen.findByRole('heading', { name: 'Income proof' });
    expect(document.body.textContent).not.toMatch(/password|token|sangam_db|revenue_db/i);
  });
});
