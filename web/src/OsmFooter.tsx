// OpenStreetMap's licence (the ODbL) asks every app that shows its data to
// credit it. One small link in the footer of each page that uses it:
// setup (addresses and masjids) and the settings page.
export function OsmFooter() {
  return (
    <footer className="site-footer">
      <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
        © OpenStreetMap contributors
      </a>
    </footer>
  );
}
