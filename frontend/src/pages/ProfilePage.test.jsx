import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import ProfilePage from './ProfilePage';

const CITIZEN_A = { citizenId: 'SYN-CIT-00001', name: 'Amit Kale', dob: '1991-11-16', phone: '+91-9123456789', district: 'Pune', persona: 'JOBSEEKER' };
const CITIZEN_B = { citizenId: 'CITIZEN_001', name: 'Rahul Kumar', dob: '2005-06-15', phone: '+91-9876543210' }; // no district/persona

describe('ProfilePage', () => {
  it('renders the real authenticated citizen profile fields', () => {
    render(<ProfilePage citizen={CITIZEN_A} applications={[]} />);
    expect(screen.getByText('Amit Kale')).toBeInTheDocument();
    expect(screen.getAllByText('SYN-CIT-00001').length).toBeGreaterThan(0);
    expect(screen.getByText('1991-11-16')).toBeInTheDocument();
    expect(screen.getByText('Pune')).toBeInTheDocument();
  });

  it('gracefully omits fields the backend did not supply for this citizen, rather than inventing them', () => {
    render(<ProfilePage citizen={CITIZEN_B} applications={[]} />);
    expect(screen.getByText('Rahul Kumar')).toBeInTheDocument();
    expect(screen.queryByText('District')).not.toBeInTheDocument();
    expect(screen.queryByText('Category')).not.toBeInTheDocument();
  });

  it('two different citizens produce two different profile renders', () => {
    const { unmount } = render(<ProfilePage citizen={CITIZEN_A} applications={[]} />);
    expect(screen.getByText('Amit Kale')).toBeInTheDocument();
    unmount();
    render(<ProfilePage citizen={CITIZEN_B} applications={[]} />);
    expect(screen.getByText('Rahul Kumar')).toBeInTheDocument();
    expect(screen.queryByText('Amit Kale')).not.toBeInTheDocument();
  });

  it('shows a real application summary derived from the applications array', () => {
    const apps = [
      { appId: 'A1', status: 'IN_PROGRESS', requirements: [] },
      { appId: 'A2', status: 'SUBMITTED', requirements: [] },
      { appId: 'A3', status: 'SUBMITTED', requirements: [] },
    ];
    render(<ProfilePage citizen={CITIZEN_A} applications={apps} />);
    const summarySection = screen.getByText('Application summary').closest('section');
    expect(summarySection.textContent).toContain('3');
  });
});
