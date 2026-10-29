async function request(path, opts = {}) {
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `Erro ${r.status}`);
  return data;
}

const qs = (params) => new URLSearchParams(params).toString();
// JSON força preflight: outro site não consegue mandar sem a página
const postJson = (path, body) =>
  request(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  playlists: () => request("/api/playlists"),
  addPlaylist: (name, url) => postJson("/api/playlists", { name, url }),
  // octet-stream não é "simple request": outro site não consegue enviar sem preflight
  uploadPlaylist: (name, file) =>
    request(`/api/playlists/upload?${qs({ name, filename: file.name })}`, {
      method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file,
    }),
  removePlaylist: (id) => request(`/api/playlists/${encodeURIComponent(id)}`, { method: "DELETE" }),
  catalog: (playlist) => request(`/api/catalog?${qs({ playlist })}`),
  live: (playlist) => request(`/api/live?${qs({ playlist })}`),
  browse: (playlist, kind, { group = "", q = "", offset = 0, limit = 60 } = {}) =>
    request(`/api/browse?${qs({ playlist, kind, group, q, offset, limit })}`),
  show: (playlist, id) => request(`/api/show?${qs({ playlist, id })}`),
  // Área de trabalho: tempo, câmbio, foguete, manchetes e a situação da conta da lista
  desk: (playlist) => request(`/api/desk?${qs({ playlist })}`),
  // Sinopse de um filme do painel; { pending: true } enquanto o painel não pode ser consultado
  vodInfo: (playlist, id) => request(`/api/vodinfo?${qs({ playlist, id })}`),
  log: (msg) => postJson("/api/log", { msg }),
  prefs: () => request("/api/prefs"),
  version: () => request("/api/version"),
  updatePrefs: (op) => postJson("/api/prefs", op),
};
