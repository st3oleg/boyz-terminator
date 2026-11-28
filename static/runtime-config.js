/* Public, non-secret frontend settings. Set apiBaseUrl before a Netlify deploy. */
window.TERMINATOR_CONFIG = window.TERMINATOR_CONFIG || {
    // Example: "https://antenna.your-tailnet.ts.net" (Tailscale Serve)
    // Leave empty to use the same-host Rover WebSocket during local development.
    apiBaseUrl: "",
    // URL HTTPS dell'Hub su HP (Tailscale Serve).
    hubMapUrl: "",
    // WebSocket Rover facoltativo per la copia PC quando apiBaseUrl non e' configurato.
    roverWsUrl: ""
};
