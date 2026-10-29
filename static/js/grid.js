// Filmes e séries: grade de capas paginada no servidor, carregando mais ao rolar.
// A estrela no canto da capa guarda o filme ou a série na "Minha lista" (a TV e o Mac veem a mesma).
import { api } from "./api.js";
import { $, esc, plural, poster, prettyGroup, remaining, meter, STAR } from "./util.js";
import { progress, isWatched, myList } from "./store.js";

const PAGE = 60;
const NOUN = { movie: ["filme", "filmes"], series: ["série", "séries"] };
let generation = 0;
let observer = null;
let loaded = [];
let pid = null;

/** Item clicado na grade (o botão guarda só o índice). */
export const gridItem = (i) => loaded[i];

function metaFor(item, kind) {
  if (item.kind === "series") return [`Temporada ${item.season}, episódio ${item.num}`];
  if (item.kind === "movie") return [item.d ? remaining(item.t, item.d) : ""];
  if (kind === "series") {
    return [item.seasonCount > 1 ? plural(item.seasonCount, "temporada", "temporadas")
      : plural(item.episodeCount, "episódio", "episódios")];
  }
  return [item.year, item.subtitled ? "Legendado" : "", isWatched(progress.get(item.url)) ? "Visto" : ""];
}

export function saveButtonHtml(i, title, saved) {
  const label = `${saved ? "Tirar da minha lista" : "Guardar na minha lista"}: ${title}`;
  return `<button type="button" class="save" data-save="${i}" aria-pressed="${saved}" aria-label="${esc(label)}" title="${esc(label)}">${STAR}</button>`;
}

// Itens de "continuar assistindo" (item.kind) são um episódio ou um ponto do filme: a estrela fica nas capas comuns
function card(item, i, kind) {
  const title = item.showName || item.title || item.name;
  const ratio = item.kind ? (item.d ? item.t / item.d : 0) : kind === "movie" ? progress.ratio(item.url) : 0;
  const meta = metaFor(item, kind).filter(Boolean).map((m) => `<span>${esc(m)}</span>`).join("");
  return `<li class="card-cell"><button type="button" class="card" data-i="${i}">
    ${poster(item.logo, title, meter(ratio))}
    <span class="card-title">${esc(title)}</span>
    <span class="card-meta">${meta}</span>
  </button>${item.kind ? "" : saveButtonHtml(i, title, myList.has(pid, kind, item))}</li>`;
}

function append(items, kind) {
  const start = loaded.length;
  loaded = [...loaded, ...items];
  $("#posters").insertAdjacentHTML("beforeend", items.map((it, j) => card(it, start + j, kind)).join(""));
}

function heading({ kind, group, q }) {
  if (q) return `Busca por “${q}”`;
  if (group === "@recent") return "Continuar assistindo";
  if (group === "@saved") return "Minha lista";
  if (group) return prettyGroup(group);
  return kind === "movie" ? "Todos os filmes" : "Todas as séries";
}

function emptyHtml({ kind, q, group }) {
  if (group === "@saved") return `<p class="note">Sua lista está vazia. A estrela no canto de cada capa guarda o filme ou a série aqui.</p>`;
  if (!q) return `<p class="note">Nada por aqui ainda.</p>`;
  const other = kind === "movie" ? ["series", "séries"] : ["filmes", "filmes"];
  return `<p class="note">Nenhum resultado para “${esc(q)}”. Confira a grafia ou
    <a href="#${other[0]}?q=${encodeURIComponent(q)}">procure em ${other[1]}</a>.</p>`;
}

/** opts.recentItems / opts.savedItems: o que "Continuar assistindo" e "Minha lista" mostram (vêm do servidor de favoritos). */
export async function renderGrid(el, opts) {
  const { kind, group, q, recentItems, savedItems } = opts;
  pid = opts.pid;
  const gen = ++generation;
  if (observer) observer.disconnect();
  loaded = [];
  el.innerHTML = `<div class="grid-page"><header class="grid-head"><h1>${esc(heading(opts))}</h1><p id="gridCount"></p></header>
    <ul class="posters" id="posters"></ul><div id="sentinel" class="sentinel"></div></div>`;
  const count = $("#gridCount");

  const pinned = group === "@recent" ? recentItems : group === "@saved" ? savedItems : null;
  if (pinned) {
    append(pinned, kind);
    count.textContent = plural(pinned.length, "item", "itens");
    if (!pinned.length) $("#sentinel").insertAdjacentHTML("beforebegin", emptyHtml(opts));
    return;
  }

  count.textContent = "Carregando…";
  let offset = 0, total = Infinity, busy = false;
  const sentinel = $("#sentinel");
  const more = async () => {
    if (busy || offset >= total || gen !== generation) return;
    busy = true;
    try {
      const page = await api.browse(pid, kind, { group, q, offset, limit: PAGE });
      if (gen !== generation) return;
      total = page.total;
      offset += page.items.length;
      append(page.items, kind);
      count.textContent = plural(total, ...NOUN[kind]);
      if (!total) sentinel.insertAdjacentHTML("beforebegin", emptyHtml(opts));
    } catch (e) {
      if (gen === generation) count.textContent = `Não foi possível carregar: ${e.message}`;
    } finally {
      busy = false;
    }
    // Tela alta: o fim da grade ainda está visível, então reobservar dispara a próxima página
    if (gen === generation && offset < total) { observer.unobserve(sentinel); observer.observe(sentinel); }
  };
  const main = el.closest("#main");
  const root = getComputedStyle(main).overflowY === "auto" ? main : null;
  observer = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && more(),
    { root, rootMargin: "600px 0px" });
  observer.observe(sentinel);
}
