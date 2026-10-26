// The privacy policy at /privacy. Google asks for one on the sign-in
// screen, and it has to be a public page on the app's own address, so it
// works without signing in. Keep it in step with what the app really does.

const CONTACT = "hakeemkashif34@gmail.com";

export function PrivacyPage() {
  return (
    <main className="page narrow privacy-page">
      <p>
        <a href="/">← PrayerFit</a>
      </p>
      <h1>Privacy policy</h1>
      <p className="hint">Last updated October 26, 2026</p>

      <p>
        PrayerFit adds your daily prayers to your Google Calendar. This page explains what it keeps about you,
        what it does with your Google account, and how to delete everything.
      </p>

      <h2>What PrayerFit keeps</h2>
      <ul>
        <li>Your Google account email and Google's ID for your account, so you can sign in.</li>
        <li>Google sign-in tokens, encrypted, so it can update your Prayers calendar every night.</li>
        <li>Your address and its location, encrypted, to work out prayer times and drive times.</li>
        <li>Your answers in setup and Settings: your masjid, which prayers you pray there, and your Jumuah choice.</li>
        <li>The prayer events it made for the next 2 weeks, so it can update them instead of adding copies.</li>
        <li>A sign-in cookie in your browser. PrayerFit has no ads and no tracking.</li>
      </ul>

      <h2>Your Google Calendar</h2>
      <p>PrayerFit asks Google for 2 calendar permissions, and never for Gmail or anything else:</p>
      <ul>
        <li>
          <strong>Calendars it creates</strong> (calendar.app.created): it makes a separate "Prayers" calendar
          and only changes events in that calendar. It can't see or change your other calendars.
        </li>
        <li>
          <strong>Free/busy</strong> (calendar.freebusy): it sees when you're busy in your main calendar, so it
          can move a prayer around a class or a meeting. It never sees what your events are, and busy times
          aren't saved.
        </li>
      </ul>
      <p>
        PrayerFit's use and transfer of information received from Google APIs follows the{" "}
        <a href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank" rel="noreferrer">
          Google API Services User Data Policy
        </a>
        , including the Limited Use requirements.
      </p>

      <h2>Who else sees your data</h2>
      <p>PrayerFit never sells your data or shares it for ads. It only sends what each service needs:</p>
      <ul>
        <li>Google Calendar: your prayer events, and the request for your busy times.</li>
        <li>Photon (OpenStreetMap): the text you type in the address and masjid boxes, to suggest places.</li>
        <li>OpenRouteService: the locations of your home and masjid, to get the drive time.</li>
        <li>Microsoft Azure: hosts the server and database in Canada.</li>
      </ul>

      <h2>Deleting your data</h2>
      <ul>
        <li>
          In Settings, <strong>Delete my account</strong> deletes everything PrayerFit keeps about you and your
          Prayers calendar in Google Calendar. Daily backups are kept for 14 days, then deleted.
        </li>
        <li>
          You can also remove PrayerFit's access at any time from your{" "}
          <a href="https://myaccount.google.com/permissions" target="_blank" rel="noreferrer">
            Google account permissions
          </a>
          .
        </li>
      </ul>

      <h2>Contact</h2>
      <p>
        Questions or requests: <a href={`mailto:${CONTACT}`}>{CONTACT}</a>
      </p>
    </main>
  );
}
