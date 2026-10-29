// Ao vivo: lista numerada (andar com ↑↓, zapear com CH+/CH− ou digitando o número) e guia do canal atual.
// "Agora na TV" (@now) é a mesma lista, só com os canais que têm programa passando, separados por categoria na
// ordem da coluna ("o que está passando de notícia?") e, dentro dela, pelo número; o canal fica em destaque;
// "Filmes passando agora" (@movies), só os que estão passando um filme do catálogo, pelo nome do filme, do mais
// bem avaliado ao menos (ali se escolhe pelo filme).
// Programa do guia que é filme ou série do catálogo tem "vod" (nota, ano, sinopse, link do filme): vem do servidor.
// Cada canal pode ter várias versões (FHD, HD, SD, reserva): o servidor junta, e c.urls tem os links de todas.
import { esc, fold, groupNote, hhmm, meter, nowProg, plural, prettyGroup, ratingHtml, STAR } from "./util.js";
import { fullscreenButton } from "./player.js";

export const PAGE_ROWS = 100; // TV fraca: a lista cresce em lotes conforme rola
const GUIDE_SIZE = 8;

/** Acrescenta a chave de busca e os links das versões a cada canal, uma vez por lista. */
export const prepare = (channels) => channels.map((c) => ({
  ...c, key: fold(c.name), urls: c.variants.map((v) => v.url),
}));

export const hasUrl = (c, url) => c.urls.includes(url);
export const isFav = (c, favs) => c.urls.some((u) => favs.has(u));
/** down: Map link -> quando não abriu. O canal só conta como fora do ar se nenhuma versão abriu. */
export const downSince = (c, down) => (c.urls.every((u) => down.has(u)) ? Math.max(...c.urls.map((u) => down.get(u))) : undefined);

export const onAirCount = (channels, now = Date.now()) => channels.filter((c) => nowProg(c.epg, now)).length;

/** O filme do catálogo que o canal está passando agora, ou nada. */
export function movieOnAir(c, now = Date.now()) {
  const p = nowProg(c.epg, now);
  return p && p.vod && p.vod.kind === "movie" ? p : null;
}
export const moviesOnAirCount = (channels, now = Date.now()) => channels.filter((c) => movieOnAir(c, now)).length;
const byRating = (now) => (a, b) => (movieOnAir(b, now).vod.rating || 0) - (movieOnAir(a, now).vod.rating || 0);

// A ordem das categorias é a da coluna da esquerda (a de quando aparecem na lista)
function byCategory(channels) {
  const rank = new Map();
  channels.forEach((c) => c.groups.forEach((g) => { if (!rank.has(g)) rank.set(g, rank.size); }));
  return (a, b) => rank.get(a.group) - rank.get(b.group) || a.num - b.num;
}

export function filter(channels, { group, q, favs }) {
  const now = Date.now();
  const words = fold(q).split(/\s+/).filter(Boolean);
  const inGroup = (c) => (group === "@fav" ? isFav(c, favs) : group === "@now" ? !!nowProg(c.epg, now)
    : group === "@movies" ? !!movieOnAir(c, now) : !group || c.groups.includes(group));
  const found = channels.filter((c) => inGroup(c) && words.every((w) => c.key.includes(w)));
  if (group === "@now") return found.sort(byCategory(channels));
  return group === "@movies" ? found.sort(byRating(now)) : found;
}

function favButton(id, name, isFav) {
  const label = `${isFav ? "Tirar dos favoritos" : "Favoritar"}: ${name}`;
  return `<button type="button" class="fav" data-fav="${id}" aria-pressed="${isFav}" aria-label="${esc(label)}" title="${esc(label)}">${STAR}</button>`;
}

/** byProgram: o nome do filme em destaque (Filmes agora); withEnd: até que horas vai o programa (Agora na TV);
 *  downAt: quando o canal não abriu neste aparelho. A nota fica ao lado do nome do programa, onde quer que ele esteja. */
function row(c, now, { isCurrent, isFav, byProgram, withEnd, downAt }) {
  const p = nowProg(c.epg, now);
  const logo = c.logo ? `<img src="${esc(c.logo)}" alt="" loading="lazy" decoding="async" onerror="this.remove()">` : "";
  const name = byProgram && p ? p.title : c.name;
  const sub = downAt ? `Não abriu às ${hhmm(downAt)}` : byProgram && p ? `${c.name}, até ${hhmm(p.stop)}`
    : p && withEnd ? `${p.title}, até ${hhmm(p.stop)}` : p ? p.title : groupNote(c.group);
  const stars = p && p.vod && !downAt ? ratingHtml(p.vod.rating) : "";
  return `<li class="channel${downAt ? " down" : ""}">
    <button type="button" class="ch" data-ch="${c.id}" aria-current="${isCurrent}">
      <span class="ch-num">${c.num}</span>
      <span class="ch-logo">${logo}</span>
      <span class="ch-body">
        <span class="ch-line"><span class="ch-name">${esc(name)}</span>${byProgram ? stars : ""}</span>
        <span class="ch-line"><span class="ch-now">${esc(sub)}</span>${byProgram ? "" : stars}</span>
        ${p && !downAt ? meter((now - p.start) / (p.stop - p.start)) : ""}
      </span>
    </button>
    ${favButton(c.id, c.name, isFav)}
  </li>`;
}

// Selo da categoria antes do primeiro canal dela, com quantos canais tem (só separa: ↑↓ e CH± passam direto)
function groupHead(list, i) {
  const g = list[i].group;
  if (i > 0 && list[i - 1].group === g) return "";
  const n = list.filter((c) => c.group === g).length;
  return `<li class="group-head"><h2><span>${esc(prettyGroup(g))}</span><small>${n}</small></h2></li>`;
}

/** down: Map link -> quando não abriu. grouped: título de categoria entre os canais (a lista vem ordenada por ela). */
export function rowsHtml(list, from, to, { currentId, favs, down, byProgram = false, withEnd = false, grouped = false }) {
  const now = Date.now();
  return list.slice(from, to).map((c, k) => (grouped ? groupHead(list, from + k) : "") + row(c, now, {
    isCurrent: c.id === currentId, isFav: isFav(c, favs), byProgram, withEnd, downAt: downSince(c, down),
  })).join("");
}

export function listHtml(list, { heading, emptyText, shown, ...rowOptions }) {
  const more = list.length > shown ? `<div class="sentinel" id="liveMore"></div>` : "";
  return `<header class="list-head"><h1>${esc(heading)}</h1><p>${plural(list.length, "canal", "canais")}</p></header>
    ${list.length ? `<ul class="channels">${rowsHtml(list, 0, shown, rowOptions)}</ul>${more}` : `<p class="note">${emptyText}</p>`}`;
}

// Escolher a versão à mão: a melhor pode estar travando e outra não
function versionsHtml(entry) {
  if (!entry.variants || entry.variants.length < 2) return "";
  return `<div class="versions" role="group" aria-label="Versões do canal"><span>Versão</span>${entry.variants.map((v) =>
    `<button type="button" class="version" data-version="${esc(v.url)}" aria-pressed="${v.url === entry.url}">${esc(v.label)}</button>`).join("")}</div>`;
}

// Filme ou série do catálogo: nota, ano, gênero, sinopse e o que dá para fazer com ele.
// O filme passando agora pode ser visto do começo; o que ainda vai passar, já.
function catalogHtml(p, onAir, info) {
  const v = p.vod;
  const genre = v.genre || (info && info.genre) || "";
  const meta = [ratingHtml(v.rating), v.year ? `<span>${v.year}</span>` : "", genre ? `<span>${esc(genre)}</span>` : ""].join("");
  const plot = p.desc || v.plot || (info && info.plot) || "";
  const action = v.kind === "movie"
    ? `<button type="button" class="btn small" data-prog="${p.start}">${onAir ? "Assistir do começo" : "Assistir agora"}</button>`
    : `<a class="btn small" href="#serie/${encodeURIComponent(v.showId)}">Ver a série</a>`;
  return `${meta ? `<p class="prog-meta">${meta}</p>` : ""}${plot ? `<p>${esc(plot)}</p>` : ""}<div class="prog-actions">${action}</div>`;
}

/** infoFor(vod): sinopse e gênero de um filme que a página já buscou no painel (ou nada). */
export function detailsHtml(entry, isFav, infoFor = () => null) {
  const now = Date.now();
  const guide = (entry.epg || []).filter((p) => p.stop > now).slice(0, GUIDE_SIZE);
  const items = guide.map((p) => {
    const onAir = p.start <= now;
    const about = p.vod ? catalogHtml(p, onAir, infoFor(p.vod)) : p.desc ? `<p>${esc(p.desc)}</p>` : "";
    return `<li class="${onAir ? "current" : ""}">
      <time>${hhmm(p.start)}</time>
      <div><b>${esc(p.title)}</b>${about}
      ${onAir ? meter((now - p.start) / (p.stop - p.start)) : ""}</div>
    </li>`;
  }).join("");
  return `<div class="now-head">
      <span class="on-air">Ao vivo</span>
      <h2><span class="now-num">${entry.num}</span>${esc(entry.title)}</h2>
      ${favButton(entry.id, entry.title, isFav)}
      ${fullscreenButton}
    </div>
    <p class="now-group">${esc(groupNote(entry.group))}</p>
    ${versionsHtml(entry)}
    ${guide.length ? `<ol class="guide">${items}</ol>` : `<p class="note">Este canal não tem guia de programação.</p>`}`;
}

export const hintHtml = () => `<div class="hint">
    <p>Escolha um canal na lista.</p>
    <p><kbd>↑</kbd> <kbd>↓</kbd> andam pela lista e <kbd>OK</kbd> (<kbd>Enter</kbd>) assiste; <kbd>OK</kbd> de novo no mesmo canal abre a tela cheia. Lá, <kbd>↑</kbd> <kbd>↓</kbd> trocam de canal, <kbd>←</kbd> <kbd>→</kbd> mostram o que está passando, <kbd>OK</kbd> mostra a lista rápida e <kbd>Voltar</kbd> sai.
    <kbd>CH+</kbd> <kbd>CH−</kbd> (<kbd>PgUp</kbd> <kbd>PgDn</kbd>) trocam de canal. Digite o número para ir direto a ele, e <kbd>0</kbd> sozinho volta ao canal anterior. <kbd>/</kbd> abre a busca.</p>
    <p>Sem saber o que ver? “Agora na TV”, nas categorias, lista o que está passando, e “Filmes agora” mostra os filmes do catálogo, do mais bem avaliado para o menos.</p>
  </div>`;
