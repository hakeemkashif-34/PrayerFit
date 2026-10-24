// The screen for signed-out users, and for users whose Google sign-in expired.

import { SIGN_IN_URL } from "./api";
import { SIGN_IN_ERRORS } from "./labels";

type Props = {
  // True when the user is signed in here but Google's sign-in has expired.
  expired?: boolean;
  errorCode?: string | null;
};

export function SignIn({ expired = false, errorCode = null }: Props) {
  const error = errorCode ? (SIGN_IN_ERRORS[errorCode] ?? SIGN_IN_ERRORS.google) : "";
  return (
    <main className="page narrow">
      <h1>Muslim Calendar</h1>
      {expired ? (
        <>
          <p>Your Google sign-in has expired, so your Prayers calendar can't update. Your settings are still saved.</p>
          <a className="button" href={SIGN_IN_URL}>
            Sign in again
          </a>
        </>
      ) : (
        <>
          <p>Keeps your prayer times up to date in a "Prayers" calendar in your Google Calendar.</p>
          <p className="hint">It only asks for access to the calendar it makes. Never Gmail, and never your other calendars.</p>
          <a className="button" href={SIGN_IN_URL}>
            Sign in with Google
          </a>
        </>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </main>
  );
}
