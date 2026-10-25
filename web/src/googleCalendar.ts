// Opening Google Calendar for the account the user signed in with.
//
// Someone signed in to 2 Google accounts would otherwise land in whichever
// one is first in their browser, which may not have the Prayers calendar.
// authuser picks the account. Google's docs only show it with a number
// (the account's place in the browser's list), but people report the
// email works for Calendar too, and the email doesn't change when the
// list order does. If that account isn't signed in, Google asks to sign in.
export function googleCalendarUrl(email: string): string {
  return `https://calendar.google.com/calendar/r?authuser=${encodeURIComponent(email)}`;
}

// Its own function so tests can see the redirect without leaving the site.
export function goToGoogleCalendar(email: string): void {
  window.location.assign(googleCalendarUrl(email));
}
