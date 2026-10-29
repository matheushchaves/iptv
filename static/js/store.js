// O que a página lembra. Favoritos, ponto dos vídeos e "continuar assistindo" ficam no servidor (a TV e o Mac
// veem os mesmos); aqui fica uma cópia para ler na hora, e cada mudança vai para lá como uma operação pequena.
// Última lista, último canal, versão preferida e canais que não abriram são deste aparelho e ficam no navegador.
// Tudo do navegador em try/catch: modo anônimo ou dados bloqueados não podem quebrar o player.
import { api } from "./api.js";

const KEYS = {
  playlist: "iptv.playlist", channels: "iptv.channels", down: "iptv.down", versions: "iptv.versions",
  // até a versão anterior, cada navegador guardava os seus
  favs: "iptv.favs", progress: "iptv.progress", recent: "iptv.recent",
};
const MAX_RECENT = 30;
const WATCHED_RATIO = 0.92;
const MIN_RESUME_SEC = 30;
const DOWN_MS = 6 * 60 * 60 * 1000;
const MAX_VERSIONS = 300;

function read(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function write(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // sem armazenamento: o player funciona, só não lembra
  }
}

function forget(key) {
  try { localStorage.removeItem(key); } catch { /* idem */ }
}

// Guardado como texto puro desde a versão anterior da página
export const lastPlaylist = {
  get() {
    try { return localStorage.getItem(KEYS.playlist); } catch { return null; }
  },
  set(id) {
    try { localStorage.setItem(KEYS.playlist, id); } catch { /* idem */ }
  },
};

// Último canal de cada lista neste aparelho e o anterior a ele (o 0 do controle volta para lá).
// channel: o link principal, que identifica o canal; url: a versão que tocou. Trocar de versão não mexe no anterior.
// Até a versão anterior era só o link ({ url, prev: link }).
const asChannel = (e) => (typeof e === "string" ? { channel: e, url: e } : { channel: e.channel || e.url, url: e.url });
export const lastChannel = {
  get(pid) {
    const mem = read(KEYS.channels, {})[pid];
    return mem ? { ...asChannel(mem), prev: mem.prev ? asChannel(mem.prev) : null } : null;
  },
  set(pid, channel, url) {
    const all = read(KEYS.channels, {});
    const was = all[pid] ? lastChannel.get(pid) : null;
    if (was && was.channel === channel && was.url === url) return;
    const prev = !was ? null : was.channel === channel ? was.prev : { channel: was.channel, url: was.url };
    write(KEYS.channels, { ...all, [pid]: { channel, url, prev } });
  },
};

// Versão do canal (FHD, HD, reserva...) que tocou por último neste aparelho: é a primeira que ele tenta
export const preferredVersion = {
  get: (channelUrl) => read(KEYS.versions, {})[channelUrl] || null,
  set(channelUrl, url) {
    const { [channelUrl]: was, ...others } = read(KEYS.versions, {});
    if (was === url) return;
    write(KEYS.versions, Object.fromEntries([...Object.entries(others), [channelUrl, url]].slice(-MAX_VERSIONS)));
  },
};

// Canais que não abriram neste aparelho: ficam apagados na lista por umas horas e o CH± passa por cima.
// Fica só aqui: no Mac, um canal da lista Xtream recusa enquanto a TV usa a única conexão, e isso não é defeito dele.
const freshDown = () => {
  const now = Date.now();
  return Object.entries(read(KEYS.down, {})).filter(([, at]) => now - at < DOWN_MS);
};
export const downChannels = {
  map: () => new Map(freshDown()),
  mark: (url) => write(KEYS.down, Object.fromEntries([...freshDown(), [url, Date.now()]])),
  clear: (url) => write(KEYS.down, Object.fromEntries(freshDown().filter(([u]) => u !== url))),
};

// ---------- guardado no servidor ----------
const recentKey = (r) => r.showId || r.url;
// "Minha lista": o filme pelo link, a série pelo id, sempre dentro da lista (cada uma tem seus ids)
const savedKey = (pid, section, item) => `${pid}|${section === "movie" ? item.url : item.id}`;
const entryKey = (s) => savedKey(s.playlist, s.section, s.item);
const signature = (s) => [s.favs, s.recent.map(recentKey), s.saved.map(entryKey)].map((l) => l.join("\n")).join("|");
let shared = { favs: [], progress: {}, recent: [], saved: [] };
let edits = 0; // mudanças feitas aqui; uma leitura que começou antes de uma delas já chega velha
let pending = 0; // operações a caminho do servidor
const changeWatchers = [];
const errorWatchers = [];

/** fn(): favoritos ou "continuar assistindo" mudaram por causa do outro aparelho (ou de uma falha ao salvar). */
export const onSharedChange = (fn) => changeWatchers.push(fn);
/** fn(): o servidor não aceitou uma mudança feita aqui. */
export const onSharedError = (fn) => errorWatchers.push(fn);

function adopt(next) {
  next = { saved: [], ...next }; // servidor de antes da "Minha lista"
  const changed = signature(next) !== signature(shared);
  shared = next;
  if (changed) changeWatchers.forEach((fn) => fn());
}

/** Busca o que o servidor tem (o outro aparelho pode ter mudado algo). */
export async function syncShared() {
  const startedAt = edits;
  const next = await api.prefs();
  if (startedAt === edits && !pending) adopt(next);
}

function send(op) {
  edits += 1;
  pending += 1;
  api.updatePrefs(op).then(
    () => { pending -= 1; },
    () => {
      pending -= 1;
      errorWatchers.forEach((fn) => fn());
      syncShared().catch(() => {}); // volta para o que o servidor tem; se nem isso, fica a cópia daqui
    },
  );
}

function changeLocally(patch) {
  shared = { ...shared, ...patch };
}

// Manda uma vez para o servidor o que este navegador guardava só para ele, e apaga daqui
async function moveLocalToServer() {
  const data = { favs: read(KEYS.favs, []), progress: read(KEYS.progress, {}), recent: read(KEYS.recent, []) };
  if (!data.favs.length && !Object.keys(data.progress).length && !data.recent.length) return;
  await api.updatePrefs({ op: "import", data });
  [KEYS.favs, KEYS.progress, KEYS.recent].forEach(forget);
}

export async function loadShared() {
  await moveLocalToServer();
  await syncShared();
}

// Um canal pode ter várias versões (links): é favorito se qualquer uma for
export const favorites = {
  set: () => new Set(shared.favs),
  hasAny: (urls) => urls.some((u) => shared.favs.includes(u)),
  /** Favorita a primeira versão, ou tira todas as que estiverem nos favoritos. */
  toggleAny(urls) {
    const on = !favorites.hasAny(urls);
    const changed = on ? [urls[0]] : urls.filter((u) => shared.favs.includes(u));
    changeLocally({ favs: on ? [...shared.favs, ...changed] : shared.favs.filter((u) => !changed.includes(u)) });
    changed.forEach((url) => send({ op: "fav", url, on }));
    return on;
  },
};

/** "Minha lista" de filmes e séries. item: o que a capa precisa para aparecer (título, capa, link ou id). */
export const myList = {
  list: (pid, section) => shared.saved.filter((s) => s.playlist === pid && s.section === section).map((s) => s.item),
  has: (pid, section, item) => shared.saved.some((s) => entryKey(s) === savedKey(pid, section, item)),
  toggle(pid, section, item) {
    const key = savedKey(pid, section, item);
    const on = !myList.has(pid, section, item);
    const others = shared.saved.filter((s) => entryKey(s) !== key);
    const entry = { playlist: pid, section, item };
    changeLocally({ saved: on ? [{ ...entry, at: Date.now() }, ...others] : others });
    send(on ? { op: "save", entry } : { op: "unsave", key });
    return on;
  },
};

export const isWatched = (p) => !!p && p.d > 0 && p.t / p.d >= WATCHED_RATIO;
export const canResume = (p) => !!p && p.t > MIN_RESUME_SEC && !isWatched(p);

export const progress = {
  get: (url) => shared.progress[url] || null,
  ratio(url) {
    const p = progress.get(url);
    return p && p.d ? p.t / p.d : 0;
  },
  save(url, t, d) {
    changeLocally({ progress: { ...shared.progress, [url]: { t, d, at: Date.now() } } });
    send({ op: "progress", url, t, d });
  },
};

// "Continuar assistindo": um item por filme e um por série (o episódio da vez)
export const recent = {
  list: (playlist, kind) => shared.recent.filter((r) => r.playlist === playlist && r.kind === kind),
  touch(item) {
    const others = shared.recent.filter((r) => recentKey(r) !== recentKey(item));
    changeLocally({ recent: [{ ...item, at: Date.now() }, ...others].slice(0, MAX_RECENT) });
    send({ op: "touch", item });
  },
  remove(item) {
    changeLocally({ recent: shared.recent.filter((r) => recentKey(r) !== recentKey(item)) });
    send({ op: "forget", key: recentKey(item) });
  },
};
