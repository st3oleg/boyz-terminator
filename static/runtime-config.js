/* Public, non-secret frontend settings. Set apiBaseUrl before a Netlify deploy. */
window.TERMINATOR_CONFIG = window.TERMINATOR_CONFIG || {
    // Example: "https://antenna.your-tailnet.ts.net" (Tailscale Serve)
    // Leave empty to use the same-host Rover WebSocket during local development.
    apiBaseUrl: ""
};
