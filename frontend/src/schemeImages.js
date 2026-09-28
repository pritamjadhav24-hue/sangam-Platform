// Scheme card and page images, chosen for what each scheme actually does
// (see content/photoCredits.json for the openly licensed photos). Where no
// real photograph fits the service, a plain SANGAM illustration is used
// instead -- never an unrelated landmark, and never anything resembling an
// official document, seal or number plate. Purely illustrative: an image
// says nothing about who is eligible or which department holds a record.
const BY_SCHEME = {
  'SCH-MH-2026': 'scholarship',            // higher-education scholarship -> graduating students
  'EDU-ACADEMIC-2026': 'academic',         // academic record verification -> students writing in class
  'SKE-CERTIFICATION-2026': 'skills',      // skill certification & employment -> computer skills training
  'MUN-BIRTH-CERT-2026': 'birth',          // birth registration -> newborn
  'SW-ENROLLMENT-2026': 'welfare',         // social welfare enrolment -> community self-help group
  'AGR-INPUT-SUBSIDY-2026': 'farm-inputs', // seeds / fertilizer subsidy -> farmer sowing seed
  'REV-LAND-VERIFY-2026': 'farmland',      // land record verification -> agricultural land
  'HSG-ALLOTMENT-2026': 'housing',         // public housing allotment -> residential housing
  'FCS-RATION-CARD-2026': 'ration',        // ration card / PDS -> grain sacks and weighing scale (illustration)
  'TRN-VEHICLE-VERIFY-2026': 'vehicle',    // vehicle registration -> vehicle verified (illustration)
};
// A scheme not listed above falls back to its category's concept, and then
// to a neutral illustration -- never to a landmark.
const BY_CATEGORY = {
  EDUCATION: 'academic', AGRICULTURE: 'farm-inputs', TRANSPORT: 'vehicle', HEALTH: 'birth', HOUSING: 'housing',
  WELFARE: 'welfare', 'SOCIAL WELFARE': 'welfare', 'FOOD & PUBLIC DISTRIBUTION': 'ration', 'SKILL DEVELOPMENT & EMPLOYMENT': 'skills', REVENUE: 'farmland',
};
const ALT = {
  scholarship: ['Graduating college students celebrating in caps and gowns', 'पदवीदान समारंभात आनंद साजरा करणारे महाविद्यालयीन विद्यार्थी'],
  academic: ['Students writing at their desks in a classroom', 'वर्गात बाकावर बसून लिहिणारे विद्यार्थी'],
  skills: ['Students learning at a computer skills training lab', 'संगणक कौशल्य प्रशिक्षण प्रयोगशाळेत शिकणारे विद्यार्थी'],
  birth: ['A newborn baby wrapped in a hospital blanket', 'रुग्णालयातील कापडात गुंडाळलेले नवजात बाळ'],
  welfare: ['Women meeting as a community self-help group', 'सामुदायिक बचत गटाच्या बैठकीतील महिला'],
  'farm-inputs': ['Farmer sowing seed by hand from a basket', 'टोपलीतून हाताने बियाणे पेरणारा शेतकरी'],
  farmland: ['Agricultural land in a Maharashtra village', 'महाराष्ट्रातील गावातील शेतजमीन'],
  housing: ['Residential apartment buildings', 'निवासी सदनिका इमारती'],
  ration: ['Illustration of food-grain sacks and a weighing scale', 'धान्याची पोती व वजनकाटा दर्शवणारे चित्र'],
  vehicle: ['Illustration of a car with a verified check mark', 'पडताळणी चिन्हासह मोटारीचे चित्र'],
};

export function schemeImage(scheme, language = 'en') {
  const id = scheme?.serviceId || scheme?.schemeId || scheme?.id;
  const key = BY_SCHEME[id] || BY_CATEGORY[String(scheme?.category || '').toUpperCase()] || 'welfare';
  const [en, mr] = ALT[key];
  return { src: `/images/schemes/${key}.webp`, alt: language === 'mr' ? mr : en };
}

export const SCHEME_IMAGE_MAP = BY_SCHEME;

// Landing-page backgrounds, in display order. Purely decorative (no captions,
// place names or credits are shown); each has a smaller rendition for phones.
export const HERO_IMAGES = ['public-service', 'graduation', 'agriculture', 'classroom'].map(key => ({
  key, src: `/images/hero/${key}.webp`, srcSmall: `/images/hero/${key}-960.webp`,
}));
