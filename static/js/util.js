export const $ = (sel, root = document) => root.querySelector(sel);

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s) => (s == null ? "" : String(s)).replace(/[&<>"']/g, (c) => ESC[c]);

/** Minúsculas sem acento: a busca casa "vinganca" com "Vingança". */
export const fold = (s) => String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

export const hhmm = (ms) => new Date(ms).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });

const pad = (n) => String(n).padStart(2, "0");
export function clock(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor(sec / 60) % 60, s = Math.floor(sec % 60);
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

export function remaining(t, d) {
  const min = Math.max(1, Math.round((d - t) / 60));
  return min < 60 ? `faltam ${min} min` : `faltam ${Math.floor(min / 60)} h ${pad(min % 60)}`;
}

// As categorias da lista grátis (iptv-org) vêm em inglês
const GROUP_PT = {
  Animation: "Animação", Auto: "Carros", Business: "Negócios", Classic: "Clássicos", Comedy: "Comédia",
  Cooking: "Culinária", Culture: "Cultura", Documentary: "Documentários", Education: "Educação",
  Entertainment: "Entretenimento", Family: "Família", General: "Variedades", Kids: "Infantil",
  Legislative: "Legislativo", Lifestyle: "Estilo de vida", Movies: "Filmes", Music: "Música", News: "Notícias",
  Outdoor: "Campo e natureza", Relax: "Relaxar", Religious: "Religiosos", Science: "Ciência", Series: "Séries",
  Shop: "Compras", Sports: "Esportes", Travel: "Viagem", Undefined: "Outros", Weather: "Tempo",
};

/** "Filmes: Drama" -> "Drama", "SÉRIES | Netflix" -> "Netflix", "News" -> "Notícias". */
export function prettyGroup(g) {
  const name = String(g).replace(/^\s*(filmes|s[ée]ries|canais)\s*[:|]\s*/i, "").trim() || g;
  return GROUP_PT[name] || name;
}

/** Categoria embaixo do nome do canal: "Undefined" (sem categoria) não diz nada, fica em branco. */
export const groupNote = (g) => (g === "Undefined" ? "" : prettyGroup(g));

/** Nota de 0 a 10 do filme ou da série ("★ 6,6"); nada quando o painel não tem. */
export function ratingHtml(r) {
  if (!r) return "";
  const text = r.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return `<span class="rating" title="Nota ${text}">${STAR}${text}</span>`;
}

export const STAR = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.6l2.6 5.3 5.8.8-4.2 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z"/></svg>`;

export const nowProg = (epg, now = Date.now()) => epg.find((p) => p.start <= now && p.stop > now);

export function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

export const isTyping = (el) => !!el && (el.isContentEditable || /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName));

export const plural = (n, one, many) => `${n.toLocaleString("pt-BR")} ${n === 1 ? one : many}`;

// Ignora palavras curtas ("de", "a") para "Força de Elite" virar "FE"
export const initials = (title) =>
  String(title).split(/\s+/).filter((w) => /^[\p{L}\d]{3,}|^\d/u.test(w)).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

/** Capa com iniciais por baixo: se a imagem falhar, as iniciais aparecem. */
export function poster(src, title, overlay = "") {
  const img = src ? `<img src="${esc(src)}" alt="" loading="lazy" decoding="async" onerror="this.remove()">` : "";
  return `<span class="poster" data-initials="${esc(initials(title))}">${img}${overlay}</span>`;
}

export const meter = (ratio) =>
  ratio > 0 ? `<span class="meter"><i style="width:${Math.round(Math.min(1, ratio) * 100)}%"></i></span>` : "";
