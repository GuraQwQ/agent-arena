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
  summary: () => request("/api/admin/summary"),
  runtime: () => request("/api/admin/runtime"),
  events: (sinceSeq = 0, limit = 100) => request(`/api/admin/events?since_seq=${encodeURIComponent(sinceSeq)}&limit=${encodeURIComponent(limit)}`),
  perspective: (seatId, signal) => request(`/api/admin/perspective?seat_id=${encodeURIComponent(seatId)}`, { signal }),
  joinHost: password => jsonRequest("/api/admin/session", { password }),
  command: body => jsonRequest("/api/admin/command", body),
  settings: body => jsonRequest("/api/admin/settings", body),
  gameControl: operation => jsonRequest(`/api/admin/game/${operation}`, {}),
  gameFrontend: () => request("/api/admin/game/frontend"),
  games: () => request("/api/admin/games"),
  startGame: body => jsonRequest("/api/admin/game", body),
  scenario: () => request("/api/admin/scenario"),
  loadScenario: body => jsonRequest("/api/admin/scenario", body),
  startFlow: steps => jsonRequest("/api/admin/flow", { steps }),
  flowControl: operation => jsonRequest(`/api/admin/flow/${operation}`, {}),
  archiveMods: roomId => request(`/api/admin/archives/${encodeURIComponent(roomId)}/mods`),
  restoreArchive: roomId => jsonRequest(`/api/admin/archives/${encodeURIComponent(roomId)}/restore`, {}),
  workspace: (seatId, directory) => jsonRequest("/api/admin/workspaces", { seat_id: seatId, directory }),
  archives: () => request("/api/admin/archives"),
  archive: roomId => request(`/api/admin/archives/${encodeURIComponent(roomId)}`),
  saveArchive: () => jsonRequest("/api/admin/archives", {}, "POST"),
  mods: () => request("/api/admin/mods"),
  contentPacks: () => request("/api/admin/content-packs"),
  avatarModels: () => request("/api/admin/avatars/models"),
  uploadAvatar: dataUrl => jsonRequest("/api/admin/avatars/images", { data_url: dataUrl }),
  setModelAvatar: (model, avatarId) => jsonRequest("/api/admin/avatars/models", { model, avatar_id: avatarId }, "PUT"),
  seatAppearance: (seatId, fields) => jsonRequest(`/api/admin/seats/${encodeURIComponent(seatId)}/appearance`, fields, "PATCH"),
  applyMods: enabled => jsonRequest("/api/admin/mods", { enabled }),
  modSettings: (modId, values) => jsonRequest(`/api/admin/mods/${encodeURIComponent(modId)}/settings`, { values }, "PUT")
};
