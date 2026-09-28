import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { SCHEME_IMAGE_MAP, schemeImage } from './schemeImages';

const PUBLIC = resolve(__dirname, '../public');
const credits = JSON.parse(readFileSync(resolve(__dirname, 'content/photoCredits.json'), 'utf8'));
const SCHEMES = [
  'SCH-MH-2026', 'EDU-ACADEMIC-2026', 'SKE-CERTIFICATION-2026', 'MUN-BIRTH-CERT-2026', 'SW-ENROLLMENT-2026',
  'AGR-INPUT-SUBSIDY-2026', 'REV-LAND-VERIFY-2026', 'HSG-ALLOTMENT-2026', 'FCS-RATION-CARD-2026', 'TRN-VEHICLE-VERIFY-2026',
];

describe('scheme images', () => {
  it('gives every connected scheme its own image, and the file exists', () => {
    const sources = SCHEMES.map(id => schemeImage({ serviceId: id }).src);
    expect(new Set(sources).size).toBe(SCHEMES.length);
    sources.forEach(src => expect(existsSync(resolve(PUBLIC, `.${src}`))).toBe(true));
  });

  it('never uses a landmark or an unrelated stock scene for a scheme', () => {
    const landmarks = ['csmt', 'fort', 'sealink', 'university', 'hospital', 'village', 'bus', 'grain'];
    Object.values(SCHEME_IMAGE_MAP).forEach(key => expect(landmarks).not.toContain(key));
    expect(schemeImage({ serviceId: 'UNKNOWN', category: 'Something new' }).src).not.toMatch(/csmt|fort|sealink/);
  });

  it('describes what the image shows (alt text), in English and Marathi', () => {
    SCHEMES.forEach(id => {
      const en = schemeImage({ serviceId: id }, 'en').alt;
      const mr = schemeImage({ serviceId: id }, 'mr').alt;
      expect(en.length).toBeGreaterThan(15);
      expect(en.toLowerCase()).not.toContain('scheme image');
      expect(mr).not.toBe(en);
    });
    expect(schemeImage({ serviceId: 'SKE-CERTIFICATION-2026' }).alt).toMatch(/training/i);
    expect(schemeImage({ serviceId: 'EDU-ACADEMIC-2026' }).alt).toMatch(/students/i);
  });

  it('credits every photograph it shows (illustrations are SANGAM originals)', () => {
    const credited = new Set(credits.schemes.map(item => item.file));
    const illustrations = new Set(['/images/schemes/ration.webp', '/images/schemes/vehicle.webp']);
    SCHEMES.map(id => schemeImage({ serviceId: id }).src).filter(src => !illustrations.has(src))
      .forEach(src => expect(credited.has(src)).toBe(true));
    credits.schemes.forEach(item => expect(item.license).toMatch(/CC|Public domain/));
  });
});

describe('landing backgrounds', () => {
  it('rotates exactly the four supplied backgrounds, each with a phone-sized rendition on disk', async () => {
    const { HERO_IMAGES } = await import('./schemeImages');
    expect(HERO_IMAGES.map(image => image.key)).toEqual(['public-service', 'graduation', 'agriculture', 'classroom']);
    HERO_IMAGES.forEach(image => {
      expect(existsSync(resolve(PUBLIC, `.${image.src}`))).toBe(true);
      expect(existsSync(resolve(PUBLIC, `.${image.srcSmall}`))).toBe(true);
      expect(image).not.toHaveProperty('en'); // no captions or place names
    });
  });

  it('no longer ships or references the removed background images, and shows no photo credits', () => {
    const { readdirSync } = require('node:fs');
    const removed = ['fort', 'csmt', 'fields', 'university', 'hospital', 'sealink'];
    const heroFiles = readdirSync(resolve(PUBLIC, 'images/hero'));
    removed.forEach(key => expect(heroFiles.some(file => file.startsWith(key))).toBe(false));
    const sources = ['App.jsx', 'pages/LoginPage.jsx', 'schemeImages.js'].map(file => readFileSync(resolve(__dirname, file), 'utf8')).join('\n');
    removed.forEach(key => expect(sources).not.toContain(`hero/${key}`));
    expect(sources).not.toMatch(/photo-credits|Photo credits|photoCredits\.hero/);
    expect(readFileSync(resolve(__dirname, '../index.html'), 'utf8')).toContain('/images/hero/public-service.webp');
  });
});
