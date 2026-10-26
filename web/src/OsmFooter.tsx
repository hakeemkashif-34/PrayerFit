// OpenStreetMap's licence (the ODbL) asks every app that shows its data to
// credit it, and OpenRouteService (drive times) asks for its own credit.
// One small line in the footer of each page that uses them: setup
// (addresses and masjids) and the settings page. The privacy link sits here too.
export function OsmFooter() {
  return (
    <footer className="site-footer">
      <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
        © OpenStreetMap contributors
      </a>
      <a href="https://openrouteservice.org/" target="_blank" rel="noreferrer">
        Drive times © openrouteservice.org by HeiGIT
      </a>
      <a href="/privacy">Privacy</a>
    </footer>
  );
}
