// The landing page for signed-out users, and the page for users whose
// Google sign-in expired. Welcome on the left, the sign-in card on the
// right. On a phone they stack.
//
// The hadith is the first thing a reader should notice, so it has its own
// look: a large serif (Amiri, which also has the ﷺ sign) in a quote block
// with a gold accent, and the source on its own line.

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
    <main className="landing">
      <section className="welcome">
        <h1>Welcome to Muslim Calendar</h1>
        <p className="lead">Keep your prayer times up to date, every day.</p>
        <figure className="hadith">
          <blockquote>
            <p>The Prophet ﷺ was asked which deed is most beloved to Allah, and he said <strong className="on-time">praying on time</strong>.</p>
          </blockquote>
          <figcaption>Sahih al-Bukhari 527</figcaption>
        </figure>
      </section>
      <section className="card sign-in" aria-label={expired ? "Sign in again" : "Sign in"}>
        {expired ? (
          <>
            <h2>Your Google sign-in has expired</h2>
            <p>Your Prayers calendar can't update until you sign in again. Your settings are still saved.</p>
            <a className="button google" href={SIGN_IN_URL}>
              Sign in again
            </a>
          </>
        ) : (
          <>
            <h2>Get started</h2>
            <a className="button google" href={SIGN_IN_URL}>
              Sign in with Google
            </a>
          </>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </section>
    </main>
  );
}
