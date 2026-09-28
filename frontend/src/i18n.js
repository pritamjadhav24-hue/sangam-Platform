export const LANGUAGE_KEY = 'sangam-language';

export function initialLanguage() {
  return localStorage.getItem(LANGUAGE_KEY) || 'en';
}

export const text = {
  en: {
    dashboard: 'Dashboard', services: 'Services', tracking: 'Track application', signOut: 'Sign out',
    welcomeCopy: 'Your connected government services, in one place.',
    applyQuestion: 'What would you like to apply for?', search: 'Search for a service',
    trackTitle: 'Track your application', applicationId: 'Application ID', track: 'Track application',
    available: 'Available online', future: 'Coming soon', apply: 'Apply now',
    education: 'Education', health: 'Health', agriculture: 'Agriculture', welfare: 'Social Welfare', employment: 'Employment & Skills', other: 'Other services',
    noResults: 'No results found. Try another search.', current: 'Current application', explore: 'Explore services',
    plainPrivacy: 'Your information is securely checked with the concerned department.',
    homeNav: 'Home', schemesNav: 'Schemes', myApplicationsNav: 'My Applications', notificationsNav: 'Notifications', profileNav: 'Profile',
    heroBlurb: 'Apply for services and track your applications in one place.',
    activeApplications: 'Active applications', submittedApplications: 'Submitted', needsAttention: 'Needs attention',
    yourApplications: 'Your Applications', noApplicationsTitle: "You haven't applied to any scheme yet",
    noApplicationsBody: 'Browse the scheme catalogue and apply -- your applications will appear here.',
    viewApplication: 'Continue', alreadyApplied: 'Already applied', actionRequiredSection: 'Action Required',
    actionRequiredBlurb: 'These requirements need your attention before you can submit.',
  },
  mr: {
    dashboard: 'मुख्यपृष्ठ', services: 'सेवा', tracking: 'अर्जाचा मागोवा', signOut: 'बाहेर पडा',
    welcomeCopy: 'आपल्या सर्व शासकीय सेवा एका ठिकाणी.',
    applyQuestion: 'आपल्याला कोणत्या सेवेसाठी अर्ज करायचा आहे?', search: 'सेवा शोधा',
    trackTitle: 'आपल्या अर्जाचा मागोवा घ्या', applicationId: 'अर्ज क्रमांक', track: 'अर्जाचा मागोवा घ्या',
    available: 'ऑनलाइन उपलब्ध', future: 'लवकरच उपलब्ध', apply: 'आता अर्ज करा',
    education: 'शिक्षण', health: 'आरोग्य', agriculture: 'कृषी', welfare: 'समाज कल्याण', employment: 'रोजगार व कौशल्य', other: 'इतर सेवा',
    noResults: 'निकाल सापडला नाही. दुसरे नाव शोधा.', current: 'सध्याचा अर्ज', explore: 'सेवा शोधा',
    plainPrivacy: 'आपली माहिती संबंधित विभागाकडून सुरक्षितपणे तपासली जाते.',
    homeNav: 'मुख्यपृष्ठ', schemesNav: 'योजना', myApplicationsNav: 'माझे अर्ज', notificationsNav: 'सूचना', profileNav: 'प्रोफाइल',
    heroBlurb: 'सेवांसाठी अर्ज करा आणि आपल्या अर्जांचा एकाच ठिकाणी मागोवा घ्या.',
    activeApplications: 'सुरू असलेले अर्ज', submittedApplications: 'सादर केलेले', needsAttention: 'लक्ष आवश्यक',
    yourApplications: 'आपले अर्ज', noApplicationsTitle: 'आपण अद्याप कोणत्याही योजनेसाठी अर्ज केलेला नाही',
    noApplicationsBody: 'योजना सूची पहा व अर्ज करा -- आपले अर्ज येथे दिसतील.',
    viewApplication: 'पुढे सुरू ठेवा', alreadyApplied: 'आधीच अर्ज केला', actionRequiredSection: 'कृती आवश्यक',
    actionRequiredBlurb: 'सादर करण्यापूर्वी या आवश्यकतांवर आपले लक्ष आवश्यक आहे.',
  },
};

export const languageText = language => text[language] || text.en;

export const CATEGORY_LABELS = {
  en: {
    Education: 'Education', Health: 'Health', Agriculture: 'Agriculture',
    Welfare: 'Social Welfare', 'Social Welfare': 'Social Welfare',
    Employment: 'Employment & Skills', 'Employment & Skills': 'Employment & Skills',
    Housing: 'Housing', Revenue: 'Revenue', Transport: 'Transport',
    'Food & Public Distribution': 'Food & Public Distribution',
    'Skill Development & Employment': 'Skill Development & Employment',
    'Civil Registration & Public Health': 'Civil Registration & Public Health',
    Other: 'Other services',
  },
  mr: {
    Education: 'शिक्षण', Health: 'आरोग्य', Agriculture: 'कृषी',
    Welfare: 'समाज कल्याण', 'Social Welfare': 'समाज कल्याण',
    Employment: 'रोजगार व कौशल्य', 'Employment & Skills': 'रोजगार व कौशल्य',
    Housing: 'गृहनिर्माण', Revenue: 'महसूल', Transport: 'परिवहन',
    'Food & Public Distribution': 'अन्न व सार्वजनिक वितरण',
    'Skill Development & Employment': 'कौशल्य विकास व रोजगार',
    'Civil Registration & Public Health': 'नागरी नोंदणी व सार्वजनिक आरोग्य',
    Other: 'इतर सेवा',
  },
};

export function categoryLabel(category, language) {
  if (!category) return '';
  const labels = CATEGORY_LABELS[language] || CATEGORY_LABELS.en;
  return labels[category] || category;
}

export function userActionLabel(action, language) {
  if (!action || language !== 'mr') return action;
  const mrActions = {
    'No action required': 'कोणतीही कृती आवश्यक नाही',
    'Use Auto-Fill or Manual Upload to provide this.': 'हे देण्यासाठी ऑटो-फिल किंवा स्वतः अपलोडचा वापर करा.',
    'Automatic retrieval was not allowed. You can provide this manually.': 'स्वयंचलित पुनर्प्राप्तीस अनुमती दिली नाही. आपण हे स्वतः अपलोड करू शकता.',
    'The retrieved information could not be verified. You can provide this manually.': 'मिळालेली माहिती पडताळता आली नाही. आपण हे स्वतः प्रदान करू शकता.',
    'Retrieval is in progress. You can try again shortly.': 'माहिती मिळवण्याची प्रक्रिया सुरू आहे. कृपया थोड्या वेळाने पुन्हा प्रयत्न करा.',
    'Your application is temporarily delayed because one of the required verifications is currently unavailable. Your application has been retained; please try again later.': 'आवश्यक पडताळण्यांपैकी एक सध्या उपलब्ध नसल्यामुळे आपल्या अर्जाला तात्पुरता विलंब होत आहे. आपला अर्ज जतन केला आहे; कृपया नंतर पुन्हा प्रयत्न करा.',
    'Automatic retrieval could not complete. You can provide this manually.': 'स्वयंचलित पुनर्प्राप्ती पूर्ण होऊ शकली नाही. आपण हे स्वतः अपलोड करू शकता.',
    'Retry verification or request help': 'पुन्हा पडताळणी करा किंवा मदत मागा',
    'Unable to confirm the record belongs to you. You can upload the document yourself.': 'ही नोंद आपलीच असल्याची खात्री करता आली नाही. आपण दस्तऐवज स्वतः अपलोड करू शकता.',
    'No verified record was found in the connected departments. You can upload the document yourself.': 'जोडलेल्या विभागांमध्ये आपली कोणतीही पडताळलेली नोंद आढळली नाही. आपण दस्तऐवज स्वतः अपलोड करू शकता.',
  };
  return mrActions[action] || action;
}

const NOTIFICATION_TITLES_MR = {
  'Action needed': 'कृती आवश्यक',
  'Document verified': 'दस्तऐवज पडताळला',
  'Application submitted': 'अर्ज सादर झाला',
};

const DOCUMENT_NAMES_MR = {
  'Domicile Certificate': 'अधिवास प्रमाणपत्र',
  'domicile certificate': 'अधिवास प्रमाणपत्र',
  'Income Certificate': 'उत्पन्न प्रमाणपत्र',
  'income certificate': 'उत्पन्न प्रमाणपत्र',
  'Ration Card': 'रेशन कार्ड',
  'ration card': 'रेशन कार्ड',
  'Land Holding Record': 'जमीन धारणा नोंद',
  'land holding record': 'जमीन धारणा नोंद',
  'Caste Certificate': 'जातीचा दाखला',
  'caste certificate': 'जातीचा दाखला',
  'Academic Record': 'शैक्षणिक नोंद',
  'academic record': 'शैक्षणिक नोंद',
};

export function translateNotification(notification, language) {
  if (!notification || language !== 'mr') return notification || {};
  const rawTitle = notification.title || '';
  const rawMessage = notification.message || '';
  const title = NOTIFICATION_TITLES_MR[rawTitle] || rawTitle;

  let message = rawMessage;
  // Match "Your <name> could not be retrieved automatically. Please upload it manually."
  const failDocMatch = rawMessage.match(/^Your (.*) could not be retrieved automatically\. Please upload it manually\.$/);
  if (failDocMatch) {
    const docName = DOCUMENT_NAMES_MR[failDocMatch[1]] || failDocMatch[1];
    message = `आपले ${docName} आपोआप मिळवता आले नाही. कृपया स्वतः अपलोड करा.`;
  } else {
    // Match "We could not verify your <name> automatically. Please try again later."
    const failNonDocMatch = rawMessage.match(/^We could not verify your (.*) automatically\. Please try again later\.$/);
    if (failNonDocMatch) {
      const fieldName = DOCUMENT_NAMES_MR[failNonDocMatch[1]] || failNonDocMatch[1];
      message = `आम्ही आपले ${fieldName} आपोआप पडताळू शकलो नाही. कृपया नंतर पुन्हा प्रयत्न करा.`;
    } else {
      // Match "Your <name> has been verified."
      const verifiedMatch = rawMessage.match(/^Your (.*) has been verified\.$/);
      if (verifiedMatch) {
        const docName = DOCUMENT_NAMES_MR[verifiedMatch[1]] || verifiedMatch[1];
        message = `आपले ${docName} पडताळले गेले आहे.`;
      } else {
        // Match "Your application for <scheme> was submitted successfully."
        const submitMatch = rawMessage.match(/^Your application for (.*) was submitted successfully\.$/);
        if (submitMatch) {
          message = `${submitMatch[1]} साठीचा आपला अर्ज यशस्वीपणे सादर झाला आहे.`;
        }
      }
    }
  }

  return { ...notification, title, message };
}
