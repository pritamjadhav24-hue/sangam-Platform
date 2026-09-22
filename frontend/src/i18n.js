export const LANGUAGE_KEY = 'sangam-language';

export function initialLanguage() {
  return localStorage.getItem(LANGUAGE_KEY) || 'en';
}

export const text = {
  en: {
    dashboard: 'Dashboard', services: 'Services', tracking: 'Track application', signOut: 'Sign out',
    welcome: 'Welcome back, Rahul', welcomeCopy: 'Your connected government services, in one place.',
    applyQuestion: 'What would you like to apply for?', search: 'Search for a service',
    trackTitle: 'Track your application', applicationId: 'Application ID', track: 'Track application',
    available: 'Available in prototype', future: 'Coming in future deployment', apply: 'Apply now',
    education: 'Education', health: 'Health', agriculture: 'Agriculture', welfare: 'Social Welfare', employment: 'Employment & Skills', other: 'Other services',
    noResults: 'No results found. Try another search.', current: 'Current application', explore: 'Explore services',
    plainPrivacy: 'Your information is securely checked with the concerned department.',
    homeNav: 'Home', schemesNav: 'Schemes', myApplicationsNav: 'My Applications', notificationsNav: 'Notifications', profileNav: 'Profile',
  },
  mr: {
    dashboard: 'मुख्यपृष्ठ', services: 'सेवा', tracking: 'अर्जाचा मागोवा', signOut: 'बाहेर पडा',
    welcome: 'पुन्हा स्वागत आहे, राहुल', welcomeCopy: 'आपल्या सर्व शासकीय सेवा एका ठिकाणी.',
    applyQuestion: 'आपल्याला कोणत्या सेवेसाठी अर्ज करायचा आहे?', search: 'सेवा शोधा',
    trackTitle: 'आपल्या अर्जाचा मागोवा घ्या', applicationId: 'अर्ज क्रमांक', track: 'अर्जाचा मागोवा घ्या',
    available: 'प्रोटोटाइपमध्ये उपलब्ध', future: 'भविष्यातील सेवेसाठी', apply: 'आता अर्ज करा',
    education: 'शिक्षण', health: 'आरोग्य', agriculture: 'कृषी', welfare: 'समाज कल्याण', employment: 'रोजगार व कौशल्य', other: 'इतर सेवा',
    noResults: 'निकाल सापडला नाही. दुसरे नाव शोधा.', current: 'सध्याचा अर्ज', explore: 'सेवा शोधा',
    plainPrivacy: 'आपली माहिती संबंधित विभागाकडून सुरक्षितपणे तपासली जाते.',
    homeNav: 'मुख्यपृष्ठ', schemesNav: 'योजना', myApplicationsNav: 'माझे अर्ज', notificationsNav: 'सूचना', profileNav: 'प्रोफाइल',
  },
};

export const languageText = language => text[language] || text.en;
