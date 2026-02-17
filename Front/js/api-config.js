// Central API configuration.
// Update BASE_URL / BASE_URL_SECONDARY and API_KEY as needed.
window.API_CONFIG = {
  BASE_URL: "http://localhost:8000/api/v1",
  BASE_URL_SECONDARY: "http://localhost:8002/api/v1",
  API_KEY: "6p0RiczKIsIJV4SO5wGBnO1lssTWPhRnq5wm1gXq"
};

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
