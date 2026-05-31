// Central API configuration.
//
// BASE_URL          -> Laravel CMS (auth, products, cart, orders)
// BASE_URL_SECONDARY -> Python FastAPI AI service (uploads, measurements, recommendations)
//
// You can override at runtime BEFORE this file loads, e.g.:
//   <script>window.API_CONFIG = { BASE_URL: "https://shop.example.com/api/v1",
//                                  BASE_URL_SECONDARY: "https://ai.example.com/api/v1" };</script>
//
// Do NOT commit secret API keys here — the frontend is publicly visible.
// If a per-page key is required, inject it via a server-rendered <meta> tag.
window.API_CONFIG = Object.assign(
  {
    BASE_URL: "http://localhost:8000/api/v1",
    BASE_URL_SECONDARY: "http://localhost:8002/api/v1",
    API_KEY: "6p0RiczKIsIJV4SO5wGBnO1lssTWPhRnq5wm1gXq"
  },
  window.API_CONFIG || {}
);

// Optional: pick up an API key injected via <meta name="api-key" content="..."> at runtime.
(function pickupMetaApiKey() {
  if (window.API_CONFIG.API_KEY) return;
  if (typeof document === "undefined") return;
  var meta = document.querySelector('meta[name="api-key"]');
  if (meta && meta.content) {
    window.API_CONFIG.API_KEY = meta.content;
  }
})();

window.apiUrl = function apiUrl(path, baseKeyOrUrl) {
  var base = "";

  if (typeof baseKeyOrUrl === "string") {
    if (baseKeyOrUrl === "secondary") {
      base = window.API_CONFIG.BASE_URL_SECONDARY || "";
    } else if (baseKeyOrUrl === "primary" || baseKeyOrUrl === "default") {
      base = window.API_CONFIG.BASE_URL || "";
    } else {
      base = baseKeyOrUrl;
    }
  } else {
    base = window.API_CONFIG.BASE_URL || "";
  }

  if (!path) {
    return base || "";
  }
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  if (!base) {
    return path;
  }
  base = base.replace(/\/+$/, "");
  var suffix = String(path).replace(/^\/+/, "");
  return base + "/" + suffix;
};
