// One notification presentation for the bell panel and the Notifications
// page, for citizens and administrators alike.
import { CircleAlert, CircleCheck, Clock, CloudOff, FileUp, MailOpen, ServerCrash, ShieldAlert, Shuffle } from 'lucide-react';

export const TYPE_ICON = {
  ACTION_REQUIRED: CircleAlert, DOCUMENT_VERIFIED: CircleCheck, APPLICATION_SUBMITTED: FileUp,
  PROVIDER_DOWN: CloudOff, PROVIDER_RECOVERED: CircleCheck, FALLBACK_ACTIVATED: Shuffle, APPLICATION_BLOCKED: Clock,
  INTEGRATION_ERROR: ServerCrash, INTEGRATION_FAILURE: CloudOff, INTEGRATION_RECOVERY: CircleCheck, VERIFICATION_ISSUE: ShieldAlert,
};

export const TYPE_CLASS = {
  ACTION_REQUIRED: 'exception', DOCUMENT_VERIFIED: 'found', APPLICATION_SUBMITTED: 'found',
  PROVIDER_DOWN: 'exception', PROVIDER_RECOVERED: 'found', FALLBACK_ACTIVATED: 'pending', APPLICATION_BLOCKED: 'pending',
  INTEGRATION_ERROR: 'exception', INTEGRATION_FAILURE: 'pending', INTEGRATION_RECOVERY: 'found', VERIFICATION_ISSUE: 'pending',
};

export function notificationIcon(notification) {
  return TYPE_ICON[notification.type] || MailOpen;
}

export function notificationTone(notification) {
  return TYPE_CLASS[notification.type] || 'pending';
}

/** "Today, 4:31 pm" / "Yesterday, 9:05 am" / "25 Sept 2026, 4:31 pm" */
export function formatNotificationTime(iso, language = 'en') {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const locale = language === 'mr' ? 'mr-IN' : 'en-IN';
  const time = date.toLocaleTimeString(locale, { hour: 'numeric', minute: '2-digit' });
  const today = new Date();
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return `${language === 'mr' ? 'आज' : 'Today'}, ${time}`;
  if (date.toDateString() === yesterday.toDateString()) return `${language === 'mr' ? 'काल' : 'Yesterday'}, ${time}`;
  return date.toLocaleString(locale, { dateStyle: 'medium', timeStyle: 'short' });
}
