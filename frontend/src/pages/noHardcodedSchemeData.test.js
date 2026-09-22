import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));

// The old CitizenDashboard shipped a hardcoded `fallbackDomains` array of
// fake scheme-like objects (fabricated names, categories, "available: false"
// placeholders) used whenever the API returned no configured services. Phase
// 6A removed it -- the catalogue must show only what the API returns, with a
// real empty/error state instead of fabricated data. This is a regression
// guard against that pattern reappearing, plus a broader scan of every new
// Phase 6A page for the same kind of fabricated content.
const FORBIDDEN_SNIPPETS = [
  'fallbackDomains',
  'Health assistance', 'Farmer assistance', 'Financial assistance', 'Skill development',
  'More government services', // the old fake per-category placeholder scheme names
];

const SCANNED_FILES = [
  'CitizenDashboard.jsx',
  'SchemesPage.jsx',
  'SchemeDetailPage.jsx',
  'ApplicationFormPage.jsx',
  'ReviewApplicationPage.jsx',
];

describe('no hardcoded scheme/department data in the Phase 6A catalogue pages (requirement 2)', () => {
  it.each(SCANNED_FILES)('%s contains no fabricated scheme placeholder data', filename => {
    const source = readFileSync(join(HERE, filename), 'utf-8');
    for (const snippet of FORBIDDEN_SNIPPETS) {
      expect(source).not.toContain(snippet);
    }
  });

  it('SchemesPage and SchemeDetailPage source real scheme fields only from api.services()/api.service(), never from an inline literal object', () => {
    for (const filename of ['SchemesPage.jsx', 'SchemeDetailPage.jsx']) {
      const source = readFileSync(join(HERE, filename), 'utf-8');
      expect(source).toMatch(/api\.(services|service)\(/);
      // No inline array/object literal assigned to a variable that looks like
      // static scheme data (e.g. `const schemes = [{ name: ...`).
      expect(source).not.toMatch(/const\s+\w*[Ss]chemes?\w*\s*=\s*\[\s*\{/);
    }
  });
});

// Phase 6B: the dynamic application form has its own, sharper hardcoding
// risks -- a per-scheme field list, a hardcoded document checklist (the exact
// task brief example: Domicile/Income/Academic), department/provider names,
// or (most importantly) a single global "Auto-Fill All" control instead of
// one action per requirement card.
describe('Phase 6B application form: no hardcoded fields/documents/departments, no global Auto-Fill (requirement: static audit)', () => {
  const source = readFileSync(join(HERE, 'ApplicationFormPage.jsx'), 'utf-8');

  it('never hardcodes the example document checklist from the task brief', () => {
    for (const snippet of ['Domicile Certificate', 'Income Certificate', 'Academic Record']) {
      expect(source).not.toContain(snippet);
    }
  });

  it('never names a department or provider', () => {
    for (const snippet of ['Revenue Department', 'Education Department', 'Social Welfare Department', 'Department', 'DigiLocker', 'API Setu']) {
      // "Department" alone would also match "Skill Development & Employment
      // Department" etc. coming back from the API at runtime, so only forbid
      // it as a literal string constant, not as any substring of rendered
      // API data (which this static source scan cannot distinguish) --
      // scan only for the specific known department/source-system names.
      if (snippet === 'Department') continue;
      expect(source).not.toContain(snippet);
    }
  });

  it('has no global Auto-Fill-all control', () => {
    expect(source).not.toMatch(/auto-?fill\s*all/i);
    expect(source).not.toMatch(/fillAll|autoFillAll/i);
  });

  it('renders requirements via a single reusable component in a .map(), not per-requirement branches', () => {
    expect(source).toMatch(/\.map\(\s*requirement\s*=>/);
    expect(source).not.toMatch(/if\s*\(\s*(requirement|scheme)(Code|Id)?\s*===/);
  });

  it('requirement actions are sourced from api.autoFillRequirement/api.uploadRequirement, never a hardcoded provider/department call', () => {
    expect(source).toMatch(/api\.autoFillRequirement\(/);
    expect(source).toMatch(/api\.uploadRequirement\(/);
  });
});

// Phase 6E: the review/submit page reads scheme, personal and requirement
// data entirely from the API response -- no scheme-specific checklist, no
// department/provider/source leakage in the confirmation view either.
describe('Phase 6E review/submit page: data-driven, no hardcoded checklist or provider leakage', () => {
  const source = readFileSync(join(HERE, 'ReviewApplicationPage.jsx'), 'utf-8');

  it('never hardcodes the example document checklist from the task brief', () => {
    for (const snippet of ['Domicile Certificate', 'Income Certificate', 'Academic Record']) {
      expect(source).not.toContain(snippet);
    }
  });

  it('never names a department, provider or source system', () => {
    for (const snippet of ['Revenue Department', 'Education Department', 'Social Welfare Department', 'DigiLocker', 'API Setu', 'adapter', 'providerId']) {
      expect(source).not.toContain(snippet);
    }
  });

  it('renders requirements via a single reusable .map(), not per-requirement branches', () => {
    expect(source).toMatch(/\.map\(\s*requirement\s*=>/);
    expect(source).not.toMatch(/if\s*\(\s*(requirement|scheme)(Code|Id)?\s*===/);
  });

  it('submission is sourced from api.submitApplication, never a client-computed readiness override', () => {
    expect(source).toMatch(/api\.submitApplication\(/);
    expect(source).toMatch(/application\.readyForSubmission/);
  });
});
