export async function request(url, options = {}) {
  const response = await fetch(url, { credentials: "same-origin", ...options });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const error = new Error(typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `请求失败 (${response.status})`);
    error.issues = data?.issues;
    error.status = response.status;
    throw error;
  }
  return data;
}

export function jsonRequest(url, body, method = "POST") {
  return request(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export const arenaApi = {
  access: () => request("/api/host/access"),
  snapshot: () => request("/api/admin/snapshot"),
  perspective: seatId => request(`/api/admin/perspective?seat_id=${encodeURIComponent(seatId)}`),
  joinHost: password => jsonRequest("/api/admin/session", { password }),
  command: body => jsonRequest("/api/admin/command", body),
  settings: body => jsonRequest("/api/admin/settings", body),
  gameControl: operation => jsonRequest(`/api/admin/game/${operation}`, {}),
  gameFrontend: () => request("/api/admin/game/frontend"),
  archives: () => request("/api/admin/archives"),
  archive: roomId => request(`/api/admin/archives/${encodeURIComponent(roomId)}`),
  saveArchive: () => jsonRequest("/api/admin/archives", {}, "POST"),
  mods: () => request("/api/admin/mods"),
  applyMods: enabled => jsonRequest("/api/admin/mods", { enabled }),
  modSettings: (modId, values) => jsonRequest(`/api/admin/mods/${encodeURIComponent(modId)}/settings`, { values }, "PUT")
};
