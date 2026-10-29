import { $, esc, debounce, isTyping, prettyGroup } from "./util.js";
import { api } from "./api.js";
import {
  favorites, myList, recent, isWatched, lastPlaylist, lastChannel, preferredVersion, downChannels,
  loadShared, syncShared, onSharedChange, onSharedError,
} from "./store.js";
import * as player from "./player.js";
import * as live from "./live.js";
import * as zapper from "./zapper.js";
import { renderGrid, gridItem, saveButtonHtml } from "./grid.js";
import { showHtml, episodeList, locate, saveShowHtml } from "./show.js";
import { initPlaylists, refreshPlaylists } from "./playlists.js";
import "./idle.js";

const browseEl = $("#browse"), detailsEl = $("#details"), railEl = $("#rail"), searchEl = $("#q"), mainEl = $("#main");
const VIEW_BY_SLUG = { "ao-vivo": "live", filmes: "movie", series: "series" };
const SLUG_BY_VIEW = { live: "ao-vivo", movie: "filmes", series: "series" };
const PLACEHOLDER = { live: "Buscar canal", movie: "Buscar filme", series: "Buscar série", show: "Buscar série" };
const ALL_LABEL = { live: "Todos os canais", movie: "Todos os filmes", series: "Todas as séries" };
const TUNE_MS = 1300;
// CH± em sequência: só o canal em que você parar é carregado (cada carga cria um player de vídeo novo na TV)
const ZAP_SETTLE_MS = 500;
const GUIDE_REFRESH_MS = 60_000;
const BACK_KEY = 461; // botão Voltar do controle da LG (webOS)
// Só a TV abre já tocando o último canal: no Mac a página serve para mexer nas listas, e um canal da lista Xtream
// tocando ali derrubaria o da TV (a conta só tem uma conexão)
const ON_TV = /Web0S|webOS|SmartTV/i.test(navigator.userAgent);

let state = Object.freeze({
  pid: null, summary: null, live: [], view: "live", group: "", q: "", showId: null, show: null, season: null, theater: false,
});
const setState = (patch) => { state = Object.freeze({ ...state, ...patch }); };
const section = () => (state.view === "show" ? "series" : state.view);
const playingUrl = () => (player.nowPlaying() || {}).url;
// O canal ao vivo que está passando, pelo id: com versões, o link tocando é só um dos dele (e dois canais podem dividir um link)
const playingChannelId = () => { const p = player.nowPlaying(); return p && p.kind === "live" ? p.id : null; };
const nextAfter = (show, url) => (locate(show, url) || {}).next;
const showCache = new Map();
let visibleLive = [];
let shownLive = 0;
let liveObserver = null;
let tuneBuffer = "";
let tuneTimer = null;
let pendingZap = null;
let zapTimer = null;

// ---------- rotas: a URL guarda seção, categoria e busca ----------
function parseHash() {
  const [path, query = ""] = location.hash.slice(1).split("?");
  const [head, id] = path.split("/");
  if (head === "serie" && id) return { view: "show", showId: decodeURIComponent(id), group: "", q: "" };
  const params = new URLSearchParams(query);
  return { view: VIEW_BY_SLUG[head] || "live", showId: null, group: params.get("g") || "", q: params.get("q") || "" };
}

function hashFor({ view, group = "", q = "", showId }) {
  if (view === "show") return `#serie/${encodeURIComponent(showId)}`;
  const params = new URLSearchParams();
  if (group) params.set("g", group);
  if (q) params.set("q", q);
  const query = params.toString();
  return `#${SLUG_BY_VIEW[view]}${query ? `?${query}` : ""}`;
}

function go(route, { replace = false } = {}) {
  const target = hashFor(route);
  if (target === location.hash) return onRoute();
  if (!replace) { location.hash = target; return; }
  history.replaceState(null, "", target);
  onRoute();
}

function onRoute() {
  setState({ ...parseHash(), theater: false });
  render();
}

// ---------- layout: onde o player fica ----------
function applyLayout() {
  const playing = player.nowPlaying();
  const stage = state.theater && playing ? "theater" : state.view === "live" ? "dock" : playing ? "mini" : "off";
  const enteringOrLeavingTheater = (stage === "theater") !== (document.body.dataset.stage === "theater");
  if (enteringOrLeavingTheater) mainEl.scrollTop = 0;
  document.body.dataset.view = state.view;
  document.body.dataset.stage = stage;
  document.body.toggleAttribute("data-playing", !!playing);
  $("#miniOpen").textContent = (playing || {}).title || "";
  if (!playing) player.setStatus(state.view === "live" ? "Escolha um canal" : "");
}

function render() {
  applyLayout();
  renderTabs();
  renderRail();
  syncSearch();
  if (!state.summary) return;
  if (state.view !== "live" && state.view !== "show" && !state.summary[state.view].count) {
    return go({ view: "live" }, { replace: true }); // esta lista não tem filmes/séries
  }
  if (state.view === "live") renderLive();
  else if (state.view === "show") renderShow();
  else {
    mainEl.scrollTop = 0;
    renderGrid(browseEl, {
      pid: state.pid, kind: state.view, group: state.group, q: state.q,
      recentItems: recent.list(state.pid, state.view), savedItems: myList.list(state.pid, state.view),
    });
  }
  renderDetails();
}

function renderTabs() {
  const s = state.summary;
  document.querySelectorAll("[data-tab]").forEach((a) => {
    const count = (s && s[a.dataset.tab].count) || 0;
    a.hidden = !!s && a.dataset.tab !== "live" && !count;
    a.setAttribute("aria-current", a.dataset.tab === section() ? "page" : "false");
    a.querySelector(".count").textContent = count ? count.toLocaleString("pt-BR") : "";
  });
}

function railEntries(kind) {
  if (kind === "live") {
    const favs = favorites.set();
    const onAir = live.onAirCount(state.live);
    const movies = live.moviesOnAirCount(state.live);
    const n = state.live.filter((c) => live.isFav(c, favs)).length;
    return [
      ...(onAir ? [{ id: "@now", name: "Agora na TV", count: onAir }] : []),
      ...(movies ? [{ id: "@movies", name: "Filmes agora", count: movies }] : []),
      ...(n ? [{ id: "@fav", name: "Favoritos", count: n }] : []),
    ];
  }
  const n = recent.list(state.pid, kind).length;
  const saved = myList.list(state.pid, kind).length;
  return [
    ...(n ? [{ id: "@recent", name: "Continuar assistindo", count: n }] : []),
    ...(saved ? [{ id: "@saved", name: "Minha lista", count: saved }] : []),
  ];
}

function renderRail() {
  const kind = section();
  const info = (state.summary || {})[kind];
  if (!info) { railEl.innerHTML = ""; return; }
  const active = state.view === "show" ? (state.show || {}).group : state.q ? null : state.group;
  const pinned = railEntries(kind);
  const items = [
    ...pinned,
    { id: "", name: ALL_LABEL[kind], count: info.count },
    ...info.groups.map((g) => ({ id: g.name, name: prettyGroup(g.name), count: g.count })),
  ];
  railEl.innerHTML = `<ul>${items.map((it, i) => `<li${i && i === pinned.length ? ' class="after-pinned"' : ""}><a href="${hashFor({ view: kind, group: it.id })}"
    class="${it.id.startsWith("@") ? "pinned" : ""}" aria-current="${it.id === active}">
    <span>${esc(it.name)}</span><small>${it.count.toLocaleString("pt-BR")}</small></a></li>`).join("")}</ul>`;
}

function syncSearch() {
  searchEl.placeholder = PLACEHOLDER[state.view];
  if (document.activeElement !== searchEl) searchEl.value = state.q;
}

// ---------- ao vivo ----------
/** keep: redesenho no lugar (guia, favorito) mantém quantas linhas já apareceram e o foco do controle. */
function renderLive({ keep = false } = {}) {
  const favs = favorites.set();
  visibleLive = live.filter(state.live, { group: state.group, q: state.q, favs });
  const heading = liveHeading();
  const emptyText = state.q ? `Nenhum canal com “${esc(state.q)}”.`
    : state.group === "@now" ? "Nenhum canal com guia está passando algo agora."
    : state.group === "@movies" ? "Nenhum canal está passando um filme do catálogo agora." : "Nenhum canal nesta categoria.";
  const focused = keep && browseEl.contains(document.activeElement) ? focusSelector(document.activeElement) : null;
  shownLive = Math.min(visibleLive.length, Math.max(live.PAGE_ROWS, keep ? shownLive : 0));
  browseEl.innerHTML = live.listHtml(visibleLive, { heading, emptyText, shown: shownLive, ...rowOptions() });
  const again = focused && browseEl.querySelector(focused);
  if (again) again.focus({ preventScroll: true });
  watchListEnd();
}

const PINNED_HEADING = { "@fav": "Favoritos", "@now": "Agora na TV", "@movies": "Filmes passando agora" };
const liveHeading = () => (state.q ? `Busca por “${state.q}”` : PINNED_HEADING[state.group]
  || (state.group ? prettyGroup(state.group) : ALL_LABEL.live));

const rowOptions = () => ({
  currentId: playingChannelId(), favs: favorites.set(), down: downChannels.map(), byProgram: (state.group === "@now" || state.group === "@movies") && !state.q,
});

const focusSelector = (el) => (el.dataset.ch ? `[data-ch="${el.dataset.ch}"]` : el.dataset.fav ? `[data-fav="${el.dataset.fav}"]` : null);

function showLiveUpTo(count) {
  const list = browseEl.querySelector(".channels");
  const to = Math.min(visibleLive.length, count);
  if (!list || to <= shownLive) return;
  list.insertAdjacentHTML("beforeend", live.rowsHtml(visibleLive, shownLive, to, rowOptions()));
  shownLive = to;
  if (shownLive < visibleLive.length) return;
  const sentinel = $("#liveMore");
  if (sentinel) sentinel.remove();
  if (liveObserver) liveObserver.disconnect();
}

function watchListEnd() {
  if (liveObserver) liveObserver.disconnect();
  const sentinel = $("#liveMore");
  if (!sentinel) return;
  const root = getComputedStyle(browseEl).overflowY === "auto" ? browseEl : null;
  liveObserver = new IntersectionObserver((entries) => {
    if (!entries.some((e) => e.isIntersecting)) return;
    showLiveUpTo(shownLive + live.PAGE_ROWS);
    // Tela alta: o fim da lista ainda está visível, então reobservar traz o próximo lote
    if (sentinel.isConnected) { liveObserver.unobserve(sentinel); liveObserver.observe(sentinel); }
  }, { root, rootMargin: "800px 0px" });
  liveObserver.observe(sentinel);
}

/** Trocar de canal só remarca duas linhas: redesenhar a lista inteira trava a TV. */
function markPlaying() {
  const prev = browseEl.querySelector('.ch[aria-current="true"]');
  if (prev) prev.setAttribute("aria-current", "false");
  const p = player.nowPlaying();
  const row = p && p.kind === "live" ? browseEl.querySelector(`.ch[data-ch="${p.id}"]`) : null;
  if (row) row.setAttribute("aria-current", "true");
}

/** url: a versão do canal que vai tocar; tried: as que já falharam nesta tentativa. */
const liveEntry = (ch, url = ch.url, tried = []) => ({
  kind: "live", id: ch.id, num: ch.num, url, title: ch.name, epg: ch.epg, group: ch.group, logo: ch.logo,
  variants: ch.variants, tried,
});

/** A versão que tocou por último neste aparelho; senão a melhor que não falhou há pouco. */
function versionFor(ch) {
  const down = downChannels.map();
  const preferred = preferredVersion.get(ch.url);
  if (preferred && live.hasUrl(ch, preferred) && !down.has(preferred)) return preferred;
  return ch.urls.find((u) => !down.has(u)) || ch.url;
}

function playChannel(ch, url = versionFor(ch)) {
  clearTimeout(zapTimer); // escolheu outro canal enquanto o CH± esperava: vale a escolha
  pendingZap = null;
  player.play(liveEntry(ch, url));
}

const playingIndex = () => visibleLive.findIndex((c) => c.id === playingChannelId());

function focusChannel(i) {
  const ch = visibleLive[i];
  if (!ch) return;
  showLiveUpTo(i + 1);
  const btn = browseEl.querySelector(`.ch[data-ch="${ch.id}"]`);
  if (!btn) return;
  btn.focus({ preventScroll: true });
  btn.scrollIntoView({ block: "nearest" });
}

// O número e o nome aparecem na hora; o vídeo só carrega quando os apertos param
function zap(step) {
  const len = visibleLive.length;
  if (!len) return;
  const down = downChannels.map();
  const at = pendingZap ? visibleLive.indexOf(pendingZap) : playingIndex();
  const from = at < 0 ? (step > 0 ? -1 : len) : at;
  let next = (from + step + len) % len;
  // Passa por cima dos canais que não abriram há pouco; se nenhum abriu, anda um só
  for (let k = 1; k < len && live.downSince(visibleLive[next], down); k++) next = (next + step + len) % len;
  if (live.downSince(visibleLive[next], down)) next = (from + step + len) % len;
  pendingZap = visibleLive[next];
  player.showChannel(liveEntry(pendingZap));
  focusChannel(next);
  if (zapper.isOpen()) zapper.select(next);
  clearTimeout(zapTimer);
  zapTimer = setTimeout(() => playChannel(pendingZap), ZAP_SETTLE_MS);
}

function openZapper() {
  const i = playingIndex();
  zapper.open(visibleLive, {
    at: Math.max(0, i), heading: liveHeading(), playing: (c) => c.id === playingChannelId(), down: downChannels.map,
  });
}

// OK num canal da lista rápida troca para ele e deixa a lista aberta (dá para ir testando); no que já passa, fecha
function pickFromZapper(c) {
  if (!c) return;
  if (c.id === playingChannelId()) return zapper.close();
  playChannel(c);
  zapper.move(0); // conta de novo o tempo para sumir
}

// ---------- controle remoto: ↑↓ andam pela categoria ou pela lista, ←→ trocam de coluna ----------
function stepChannel(step) {
  if (!visibleLive.length) return;
  const row = browseEl.contains(document.activeElement) ? document.activeElement.closest(".channel") : null;
  const from = row ? visibleLive.findIndex((c) => String(c.id) === row.querySelector(".ch").dataset.ch) : playingIndex();
  focusChannel(from < 0 ? 0 : Math.max(0, Math.min(visibleLive.length - 1, from + step)));
}

function focusRailLink(step = 0) {
  const links = Array.from(railEl.querySelectorAll("a"));
  const i = links.indexOf(document.activeElement);
  const from = i < 0 ? Math.max(0, links.findIndex((a) => a.getAttribute("aria-current") === "true")) : i + step;
  const link = links[Math.max(0, Math.min(links.length - 1, from))];
  if (!link) return;
  link.focus({ preventScroll: true });
  link.scrollIntoView({ block: "nearest" });
}

/** true quando a tecla foi usada para mover o foco. */
function navigate(key) {
  const active = document.activeElement;
  const inRail = railEl.contains(active);
  const inList = browseEl.contains(active);
  if (!inRail && !inList && active !== document.body) return false; // topo, guia, player: comportamento normal
  if (key === "ArrowUp" || key === "ArrowDown") {
    const step = key === "ArrowDown" ? 1 : -1;
    if (inRail) focusRailLink(step);
    else stepChannel(step);
  } else if (key === "ArrowLeft") {
    if (inList && active.dataset.fav) active.closest(".channel").querySelector(".ch").focus();
    else focusRailLink();
  } else if (key === "ArrowRight") {
    if (inList && active.dataset.ch) active.closest(".channel").querySelector(".fav").focus();
    else if (!inList) stepChannel(0);
  } else return false;
  return true;
}

/** Canal guardado ({ channel, url }) e a versão que tocou, se ela ainda for dele. */
function remembered(mem) {
  const ch = mem && (state.live.find((c) => c.url === mem.channel) || state.live.find((c) => live.hasUrl(c, mem.url)));
  return ch ? { ch, url: live.hasUrl(ch, mem.url) ? mem.url : versionFor(ch) } : null;
}

// 0 sozinho volta para o canal anterior, como na TV a cabo (nenhum canal começa com 0)
function previousChannel() {
  const mem = lastChannel.get(state.pid);
  const prev = remembered(mem && mem.prev);
  if (prev) playChannel(prev.ch, prev.url);
  else player.flash("Ainda não há canal anterior");
}

function tune(digit) {
  if (!tuneBuffer && digit === "0") return previousChannel();
  tuneBuffer = (tuneBuffer + digit).slice(-4);
  player.showTuning(tuneBuffer);
  clearTimeout(tuneTimer);
  tuneTimer = setTimeout(() => {
    const num = Number(tuneBuffer);
    tuneBuffer = "";
    const ch = state.live.find((c) => c.num === num);
    if (ch) playChannel(ch);
    else player.flash(`Não existe canal ${num}`);
  }, TUNE_MS);
}

// ---------- séries ----------
async function loadShow(id) {
  const key = `${state.pid}:${id}`;
  if (!showCache.has(key)) showCache.set(key, api.show(state.pid, id));
  try {
    return await showCache.get(key);
  } catch (e) {
    showCache.delete(key);
    throw e;
  }
}

const resumeFor = (show) => recent.list(state.pid, "series").find((r) => r.showId === show.id);

function defaultSeason(show) {
  const p = player.nowPlaying();
  if (p && p.kind === "episode" && p.show.id === show.id) return p.season;
  const resume = resumeFor(show);
  if (resume && resume.season != null) return resume.season;
  return show.seasons.length ? show.seasons[0].number : undefined;
}

async function renderShow() {
  const id = state.showId;
  if ((state.show || {}).id !== id) {
    browseEl.innerHTML = `<p class="note">Carregando a série…</p>`;
    try {
      const show = await loadShow(id);
      if (state.showId !== id) return;
      setState({ show, season: defaultSeason(show) });
      renderRail();
    } catch (e) {
      browseEl.innerHTML = `<p class="note">${esc(e.message)}. <a href="#series">Ver todas as séries</a></p>`;
      return;
    }
  }
  browseEl.innerHTML = showHtml(state.show, {
    season: state.season, currentUrl: playingUrl(), resume: resumeFor(state.show),
    saved: myList.has(state.pid, "series", state.show),
  });
}

function playEpisode(show, url) {
  const loc = locate(show, url);
  if (!loc) return;
  setState({ theater: true, show, season: loc.season });
  player.play({
    kind: "episode", url, show, season: loc.season, num: loc.episode.num, epTitle: loc.episode.title,
    title: `${show.name}, T${loc.season} E${loc.episode.num}`, logo: show.logo,
  });
}

async function openEpisode(showId, url) {
  try {
    playEpisode(await loadShow(showId), url);
  } catch (e) {
    player.flash(e.message);
  }
}

// ---------- filmes / grade ----------
function playMovie(m) {
  setState({ theater: true });
  player.play({ kind: "movie", url: m.url, title: m.title, year: m.year, subtitled: m.subtitled, group: m.group, logo: m.logo });
}

function openGridItem(it) {
  if (!it) return;
  if (it.showId) openEpisode(it.showId, it.url);
  else if (state.view === "movie") playMovie(it);
  else go({ view: "show", showId: it.id });
}

// ---------- painel abaixo do player ----------
function vodDetailsHtml(p) {
  const back = state.theater
    ? `<button type="button" class="btn ghost back" data-action="leave">${p.kind === "episode" ? `Voltar para ${esc(p.show.name)}` : "Voltar para os filmes"}</button>` : "";
  const copy = `${player.fullscreenButton}<button type="button" class="btn" data-action="copy">Copiar link do vídeo (para abrir no VLC)</button>`;
  if (p.kind === "movie") {
    const meta = [p.year, p.subtitled ? "Legendado" : "", prettyGroup(p.group)].filter(Boolean);
    const save = saveShowHtml(myList.has(state.pid, "movie", p)).replace('data-action="save-show"', 'data-action="save-movie"');
    return `<div class="vod">${back}<h1 class="vod-title">${esc(p.title)}</h1>
      <p class="vod-meta">${meta.map((m) => `<span>${esc(m)}</span>`).join("")}</p>
      <div class="vod-actions">${save}${copy}</div></div>`;
  }
  const loc = locate(p.show, p.url);
  const season = p.show.seasons.find((s) => s.number === p.season);
  const next = loc && loc.next ? `<button type="button" class="btn primary" data-action="next">Próximo episódio</button>` : "";
  return `<div class="vod">${back}<h1 class="vod-title">${esc(p.show.name)}</h1>
    <p class="vod-meta"><span>Temporada ${p.season}, episódio ${p.num}${/^epis[óo]dio \d+$/i.test(p.epTitle) ? "" : `: ${esc(p.epTitle)}`}</span></p>
    <div class="vod-actions">${next}${copy}</div>
    <h2 class="vod-sub">Temporada ${p.season}</h2>${season ? episodeList(season, p.url) : ""}</div>`;
}

// Sinopse dos filmes do guia: o painel dá uma por vez e tem limite de consultas, então só do programa que está
// passando e do próximo, e só quando o guia não trouxe descrição. Fica guardada aqui e no servidor.
const INFO_RETRY_MS = 60_000;
const movieInfos = new Map(); // "lista:id" -> sinopse e gênero, ou { pendingAt } enquanto o painel não respondeu
const infoKey = (vod) => `${state.pid}:${vod.id}`;
const infoFor = (vod) => { const got = movieInfos.get(infoKey(vod)); return got && !got.pendingAt ? got : null; };

function loadMovieInfos(entry) {
  const now = Date.now(), pid = state.pid;
  const wanted = entry.epg.filter((p) => p.stop > now).slice(0, 2).filter((p) => p.vod && p.vod.kind === "movie" && !p.desc);
  wanted.forEach(({ vod }) => {
    const key = infoKey(vod), got = movieInfos.get(key);
    if (got && (!got.pendingAt || now - got.pendingAt < INFO_RETRY_MS)) return;
    movieInfos.set(key, { pendingAt: now });
    api.vodInfo(pid, vod.id).then((info) => {
      if (info.pending) return;
      movieInfos.set(key, info);
      if (state.pid === pid && playingChannelId() === entry.id) renderDetails(); // mesmo canal, qualquer versão
    }).catch(() => {});
  });
}

function renderDetails() {
  const p = player.nowPlaying();
  if (!p) detailsEl.innerHTML = state.view === "live" ? live.hintHtml() : "";
  else if (p.kind === "live") {
    detailsEl.innerHTML = live.detailsHtml(p, favorites.hasAny(p.variants.map((v) => v.url)), infoFor);
    loadMovieInfos(p);
  } else detailsEl.innerHTML = vodDetailsHtml(p);
}

// "Assistir do começo": o filme que o canal está passando, do catálogo, desde o início
function playFromGuide(start) {
  const p = player.nowPlaying();
  const prog = p && p.kind === "live" && p.epg.find((x) => String(x.start) === start);
  if (prog && prog.vod && prog.vod.kind === "movie") playMovie(prog.vod);
}

function leaveTheater() {
  const p = player.nowPlaying();
  setState({ theater: false });
  if (p && p.kind === "episode" && state.showId !== p.show.id) return go({ view: "show", showId: p.show.id });
  applyLayout();
  renderDetails();
  if (state.view === "show") renderShow();
}

async function copyLink(btn) {
  try {
    await navigator.clipboard.writeText(player.nowPlaying().url);
    btn.textContent = "Link copiado. No VLC: Arquivo > Abrir Rede, e cole";
  } catch {
    btn.textContent = "Não foi possível copiar o link";
  }
}

// "Minha lista" guarda só o que a capa precisa para aparecer
const savedShape = (kind, it) => (kind === "movie"
  ? { url: it.url, title: it.title, year: it.year, subtitled: it.subtitled, group: it.group, logo: it.logo }
  : { id: it.id, name: it.name, group: it.group, logo: it.logo, seasonCount: it.seasonCount, episodeCount: it.episodeCount });

function toggleSaved(kind, item) {
  const on = myList.toggle(state.pid, kind, savedShape(kind, item));
  renderRail();
  return on;
}

// A estrela muda ali mesmo; na "Minha lista" a capa fica até sair dela (dá para desfazer)
function onSaveCard(btn) {
  const i = Number(btn.dataset.save), item = gridItem(i);
  const on = toggleSaved(section(), item);
  btn.outerHTML = saveButtonHtml(i, item.title || item.name, on);
  const again = browseEl.querySelector(`[data-save="${i}"]`);
  if (again) again.focus({ preventScroll: true });
}

function pickVersion(url) {
  const p = player.nowPlaying();
  const ch = p && p.kind === "live" && state.live[p.id];
  if (ch && url !== p.url) playChannel(ch, url);
}

// ---------- eventos ----------
function onClick(e) {
  const t = e.target.closest("[data-ch],[data-zap],[data-fav],[data-save],[data-version],[data-prog],[data-i],[data-ep],[data-season],[data-action]");
  if (!t) return;
  const d = t.dataset;
  if (d.zap) pickFromZapper(zapper.pick(Number(d.zap)));
  else if (d.ch) {
    const c = state.live[Number(d.ch)];
    const isPlaying = c.id === playingChannelId();
    // OK de novo no canal que já está passando abre a tela cheia; se ele parou de responder, tenta de novo.
    // Se o navegador não deixou começar sozinho (a TV abrindo no último canal), esse OK é o que começa.
    if (isPlaying && player.isBlocked()) player.resume();
    else if (isPlaying && !player.hasFailed()) player.toggleFullscreen();
    else playChannel(c);
  } else if (d.save) onSaveCard(t);
  else if (d.version) pickVersion(d.version);
  else if (d.prog) playFromGuide(d.prog);
  else if (d.fav) {
    favorites.toggleAny(state.live[Number(d.fav)].urls);
    renderRail();
    if (state.view === "live") renderLive({ keep: true });
    renderDetails();
  } else if (d.i) openGridItem(gridItem(Number(d.i)));
  else if (d.ep) {
    const p = player.nowPlaying();
    playEpisode(t.closest("#details") && p && p.show ? p.show : state.show, d.ep);
  } else if (d.season) {
    setState({ season: Number(d.season) });
    renderShow();
  } else if (d.action === "leave") leaveTheater();
  else if (d.action === "next") {
    const p = player.nowPlaying();
    const next = nextAfter(p.show, p.url);
    if (next) playEpisode(p.show, next.episode.url);
  } else if (d.action === "save-show") {
    toggleSaved("series", state.show);
    renderShow();
  } else if (d.action === "save-movie") {
    toggleSaved("movie", player.nowPlaying());
    renderDetails();
  } else if (d.action === "copy") copyLink(t);
  else if (d.action === "fullscreen") player.toggleFullscreen();
}

function onKey(e) {
  if (e.metaKey || e.ctrlKey || e.altKey || $("#dlg").open) return;
  const typing = isTyping(document.activeElement);
  if (e.key === "/" && !typing) { e.preventDefault(); searchEl.focus(); return; }
  if (e.key === "Escape" && state.theater) { leaveTheater(); return; }
  if (typing) return;
  // F abre e fecha a tela cheia, como no YouTube
  if (e.key === "f" || e.key === "F") { player.toggleFullscreen(); return; }
  if (player.isFullscreen() && fullscreenKey(e)) { e.preventDefault(); return; }
  if (state.view !== "live") return;
  const step = channelStep(e);
  if (step) { e.preventDefault(); zap(step); }
  else if (navigate(e.key)) e.preventDefault();
  else if (/^[0-9]$/.test(e.key)) tune(e.key);
}

// Tela cheia: OK abre a lista rápida; com ela aberta, ↑↓ andam, OK troca de canal e ← fecha.
// Voltar sai da tela cheia (o navegador da TV cuida dele; se a tecla chegar aqui, fecha a lista antes).
function fullscreenKey(e) {
  const back = e.keyCode === BACK_KEY;
  if (zapper.isOpen()) {
    if (e.key === "ArrowUp" || e.key === "ArrowDown") zapper.move(e.key === "ArrowDown" ? 1 : -1);
    else if (e.key === "Enter") pickFromZapper(zapper.selected());
    else if (e.key === "ArrowLeft" || back) zapper.close();
    else return false; // CH± e números continuam valendo
    return true;
  }
  const canZap = state.view === "live" && visibleLive.length > 0 && (player.nowPlaying() || {}).kind === "live";
  if (e.key === "Enter" && canZap) openZapper();
  else if (e.key === "Enter" || back) player.toggleFullscreen(); // filme e episódio: OK sai, como antes
  else if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && canZap) player.showChannel();
  else return false;
  return true;
}

// CH+/CH− do controle da LG chegam como PageUp/PageDown (33/34). Em tela cheia a lista não está
// à vista (e o Chrome não deixa focar nada fora da moldura), então ↑↓ também trocam de canal.
function channelStep(e) {
  if (e.key === "PageUp" || e.keyCode === 33) return 1;
  if (e.key === "PageDown" || e.keyCode === 34) return -1;
  if (!player.isFullscreen()) return 0;
  return e.key === "ArrowUp" ? 1 : e.key === "ArrowDown" ? -1 : 0;
}

function rememberProgress({ entry, t, d }) {
  const watched = isWatched({ t, d });
  if (entry.kind === "movie") {
    const item = { playlist: state.pid, kind: "movie", url: entry.url, title: entry.title, year: entry.year,
      subtitled: entry.subtitled, group: entry.group, logo: entry.logo, t, d };
    if (watched) recent.remove(item);
    else recent.touch(item);
    return;
  }
  if (entry.kind !== "episode") return;
  const base = { playlist: state.pid, kind: "series", showId: entry.show.id, showName: entry.show.name, logo: entry.show.logo };
  const next = watched ? nextAfter(entry.show, entry.url) : null;
  if (watched && !next) recent.remove(base);
  else if (next) recent.touch({ ...base, url: next.episode.url, season: next.season, num: next.episode.num, t: 0, d: 0 });
  else recent.touch({ ...base, url: entry.url, season: entry.season, num: entry.num, t, d });
}

player.on("change", (p) => {
  if (!p) setState({ theater: false });
  if (p && p.kind === "live" && state.live[p.id]) lastChannel.set(state.pid, state.live[p.id].url, p.url);
  applyLayout();
  renderDetails();
  if (state.view === "live" && state.summary) markPlaying();
  zapper.refresh();
  if (state.view === "show" && (state.show || {}).id === state.showId) renderShow();
});
player.on("progress", rememberProgress);

// Versão que nem abriu fica apagada por umas horas; se voltar a tocar, deixa de ficar.
// O canal só aparece apagado quando nenhuma versão abriu.
function redrawDownMarks() {
  if (state.view === "live" && state.summary) renderLive({ keep: true });
  zapper.refresh();
}

const versionLabel = (ch, url) => (ch.variants.find((v) => v.url === url) || {}).label;

// Uma versão falhou (não abriu, parou de responder ou travou): tenta a próxima que ainda não falhou
function tryNextVersion(entry, why) {
  const ch = state.live[entry.id];
  if (!ch || !live.hasUrl(ch, entry.url)) return false;
  const tried = [...entry.tried, entry.url];
  const down = downChannels.map();
  const next = ch.urls.find((u) => !tried.includes(u) && !down.has(u));
  if (!next) return false;
  player.play(liveEntry(ch, next, tried));
  player.flash(`${versionLabel(ch, entry.url)} ${why}. Tentando ${versionLabel(ch, next)}`);
  return true;
}

player.on("failed", ({ entry, opened }) => {
  if (entry.kind !== "live") return;
  if (!opened) downChannels.mark(entry.url);
  if (!tryNextVersion(entry, opened ? "parou" : "não abriu") && !opened) redrawDownMarks();
});
// Vídeo parado 20 s com o servidor demorando: troca antes de o player desistir (sem outra versão, segue tentando)
player.on("stalled", (entry) => {
  if (entry.kind === "live") tryNextVersion(entry, "travou");
});
player.on("playing", (entry) => {
  if (entry.kind !== "live") return;
  const ch = state.live[entry.id];
  if (ch && live.hasUrl(ch, entry.url) && ch.urls.length > 1) preferredVersion.set(ch.url, entry.url);
  if (!downChannels.map().has(entry.url)) return;
  downChannels.clear(entry.url);
  redrawDownMarks();
});

// Favoritos e "continuar assistindo" mudaram no outro aparelho
onSharedChange(() => {
  renderRail();
  if (state.view === "live" && state.summary) renderLive({ keep: true });
  if ((player.nowPlaying() || {}).kind === "live") renderDetails();
});
onSharedError(() => player.flash("Não foi possível salvar no servidor"));
// Leitura em segundo plano: se o servidor não responder, o resto da página também vai mostrar
const syncQuietly = () => syncShared().catch(() => {});
document.addEventListener("visibilitychange", () => { if (!document.hidden) syncQuietly(); });
player.on("ended", (entry) => {
  if (entry.kind !== "episode") return;
  const next = nextAfter(entry.show, entry.url);
  if (!next) return;
  playEpisode(entry.show, next.episode.url);
  player.flash("Próximo episódio");
});

document.addEventListener("click", onClick);
document.addEventListener("keydown", onKey);
// A tela cheia tira o foco da lista; ao sair, ele volta para o canal que está passando
document.addEventListener("fullscreenchange", () => {
  if (document.fullscreenElement) return;
  zapper.close();
  if (state.view === "live") focusChannel(playingIndex());
});
window.addEventListener("hashchange", onRoute);
searchEl.addEventListener("input", debounce(() => {
  go({ view: section(), q: searchEl.value.trim(), group: "" }, { replace: true });
}, 250));
$("#miniOpen").addEventListener("click", () => {
  const p = player.nowPlaying();
  if (!p) return;
  if (p.kind === "live") return go({ view: "live" });
  setState({ theater: true });
  applyLayout();
  renderDetails();
});
$("#miniClose").addEventListener("click", () => player.stop());
setInterval(() => {
  syncQuietly();
  if (state.view === "live" && state.summary) renderLive({ keep: true });
  if ((player.nowPlaying() || {}).kind === "live") renderDetails();
}, GUIDE_REFRESH_MS);

// ---------- início ----------
async function loadPlaylist(pid) {
  player.stop();
  showCache.clear();
  setState({ pid, summary: null, live: [], show: null });
  render();
  if (!pid) {
    browseEl.innerHTML = `<p class="note">Nenhuma lista salva. Adicione uma em “Listas”.</p>`;
    return;
  }
  lastPlaylist.set(pid);
  browseEl.innerHTML = `<p class="note">Carregando a lista… Na primeira vez pode levar alguns segundos.</p>`;
  try {
    const [summary, channels] = await Promise.all([api.catalog(pid), api.live(pid)]);
    if (state.pid !== pid) return;
    setState({ summary, live: live.prepare(channels) });
  } catch (e) {
    browseEl.innerHTML = `<p class="note">Não foi possível carregar a lista: ${esc(e.message)}</p>`;
    return;
  }
  onRoute();
  if (ON_TV) resumeLastChannel();
}

// A TV abre no canal em que parou, como uma TV de verdade (só na seção ao vivo)
function resumeLastChannel() {
  const last = state.view === "live" && remembered(lastChannel.get(state.pid));
  if (!last) return;
  playChannel(last.ch, last.url);
  focusChannel(playingIndex());
}

initPlaylists({ onSelect: loadPlaylist });
const sharedReady = loadShared().catch(() => player.flash("Não foi possível carregar os favoritos"));
Promise.all([refreshPlaylists(lastPlaylist.get()), sharedReady])
  .then(([pid]) => loadPlaylist(pid))
  .catch((e) => { browseEl.innerHTML = `<p class="note">Não foi possível abrir as listas: ${esc(e.message)}</p>`; });
