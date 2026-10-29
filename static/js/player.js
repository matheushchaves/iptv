// Um único <video> para tudo: o layout muda de lugar (lateral, cinema, miniplayer), o elemento não.
import { $, esc, clock, hhmm, meter, nowProg, ratingHtml } from "./util.js";
import { progress, canResume } from "./store.js";
import { api } from "./api.js";

const video = $("#video");
const screen = $(".screen");
const statusEl = $("#status");
const osd = $("#osd");
const SAVE_EVERY_MS = 5000;
const OSD_MS = 3500;
const RETRY_WAIT_MS = [2000, 4000, 8000]; // pausas antes de retomar um canal que deu erro; acabou a lista, desiste

export const fullscreenButton = `<button type="button" class="btn full" data-action="fullscreen">Tela cheia</button>`;

const bus = new EventTarget();
let hls = null;
let current = null;
let lastSave = 0;
let osdTimer = null;
let failed = false;
let blocked = false;

export const on = (type, fn) => bus.addEventListener(type, (e) => fn(e.detail));
const emit = (type, detail) => bus.dispatchEvent(new CustomEvent(type, { detail }));

export const nowPlaying = () => current;
export const hasFailed = () => failed;
export const isBlocked = () => blocked;
export const setStatus = (text) => (statusEl.textContent = text);

function reset() {
  if (hls) { hls.destroy(); hls = null; }
  video.removeAttribute("src");
  video.load();
  video.controls = false; // tela parada não mostra controles de um vídeo que não existe
}

/** entry: { kind: "live" | "movie" | "episode", url, title, ... } */
export function play(entry) {
  reset();
  current = entry;
  lastSave = 0;
  failed = false;
  blocked = false;
  video.controls = true;
  setStatus("Conectando…");
  const src = "/proxy?u=" + encodeURIComponent(entry.url);
  if (entry.kind === "live") playStream(src);
  else playFile(src, entry);
  emit("change", current);
}

// Na TV não há console: erros de rede e fatais vão para o log do servidor (sem a URL, que tem a senha)
function reportError(entry, startedAt, d) {
  const http = d.response && d.response.code ? ` HTTP ${d.response.code}` : "";
  const why = d.error && d.error.message ? ` (${d.error.message.replace(/https?:\S+/g, "<url>")})` : "";
  const minutes = ((Date.now() - startedAt) / 60000).toFixed(1);
  api.log(`${entry.num} ${entry.title}: ${d.fatal ? "FATAL " : ""}${d.type}/${d.details}${http}${why} depois de ${minutes} min`)
    .catch(() => {});
}

// Abrir a página já tocando o último canal esbarra na regra de autoplay de alguns navegadores: aí quem começa é o OK
function start() {
  video.play().catch((e) => {
    if (e.name !== "NotAllowedError") return; // AbortError: trocou de canal antes de começar
    blocked = true;
    setStatus("Aperte OK para assistir");
  });
}

export function resume() {
  blocked = false;
  setStatus("");
  start();
}

function playStream(src) {
  if (window.Hls && Hls.isSupported()) startHls(src);
  else {
    video.src = src;
    start();
  }
  showChannel();
}

function startHls(src) {
  const entry = current, startedAt = Date.now(), stream = new Hls({ manifestLoadingMaxRetry: 2 });
  let opened = false, tries = 0, failedSn = null;
  hls = stream;

  // O servidor da emissora às vezes some com um pedaço do vídeo (na TV, as tentativas do hls.js se esgotam
  // num segundo). Em vez de desistir, espera e retoma; se o mesmo pedaço falhar de novo, pula para depois dele.
  function recover(d) {
    if (hls !== stream) return; // trocou de canal enquanto esperava
    if (d.type === Hls.ErrorTypes.MEDIA_ERROR) return stream.recoverMediaError();
    const frag = d.frag;
    const skip = frag && frag.sn === failedSn;
    failedSn = frag ? frag.sn : null;
    if (!skip) return stream.startLoad();
    const after = frag.start + frag.duration;
    video.currentTime = after;
    stream.startLoad(after);
  }

  function giveUp() {
    failed = true;
    setStatus(opened ? "O canal parou de responder. Aperte OK nele para tentar de novo." : "Este canal está fora do ar ou bloqueado. Tente outro.");
    stream.destroy();
    hls = null;
    emit("failed", { entry, opened });
  }

  stream.loadSource(src);
  stream.attachMedia(video);
  stream.on(Hls.Events.MANIFEST_PARSED, () => {
    opened = true;
    start();
  });
  stream.on(Hls.Events.FRAG_BUFFERED, () => {
    if (!tries) return;
    api.log(`${entry.num} ${entry.title}: voltou depois de ${tries} tentativa(s)`).catch(() => {});
    tries = 0;
    setStatus("");
  });
  stream.on(Hls.Events.ERROR, (_, d) => {
    if (d.fatal || d.type === Hls.ErrorTypes.NETWORK_ERROR) reportError(entry, startedAt, d);
    if (!d.fatal) return;
    if (!opened || tries >= RETRY_WAIT_MS.length) return giveUp();
    setStatus("Reconectando…");
    setTimeout(() => recover(d), RETRY_WAIT_MS[tries++]);
  });
}

// Arquivo comum (filme/episódio): o navegador toca direto e pede pedaços para avançar/voltar
function playFile(src, entry) {
  const saved = progress.get(entry.url);
  video.src = src;
  if (canResume(saved)) {
    video.addEventListener("loadedmetadata", () => {
      if (current !== entry) return;
      video.currentTime = saved.t;
      flash(`Continuando de ${clock(saved.t)}`);
    }, { once: true });
  }
  start();
}

export function stop() {
  saveProgress();
  reset();
  current = null;
  setStatus("");
  osd.classList.remove("on");
  emit("change", null);
}

function showOsd(html) {
  osd.innerHTML = html;
  osd.classList.add("on");
  clearTimeout(osdTimer);
  osdTimer = setTimeout(() => osd.classList.remove("on"), OSD_MS);
}

/** entry: o canal que está passando ou, na troca rápida, o que vai entrar. Mostra quanto do programa
 *  já passou e o que vem depois dele. */
export function showChannel(entry = current) {
  if (!entry || entry.kind !== "live") return;
  const now = Date.now(), epg = entry.epg || [];
  const prog = nowProg(epg, now);
  const next = prog && epg.find((p) => p.start >= prog.stop);
  const stars = prog && prog.vod ? ratingHtml(prog.vod.rating) : "";
  const progHtml = prog ? `<small>${esc(prog.title)} até ${hhmm(prog.stop)}${stars}</small>${meter((now - prog.start) / (prog.stop - prog.start))}` : "";
  const nextHtml = next ? `<small class="osd-next">A seguir, ${hhmm(next.start)}: ${esc(next.title)}</small>` : "";
  showOsd(`<span class="osd-num">${entry.num}</span>
    <span class="osd-text"><b>${esc(entry.title)}</b>${progHtml}${nextHtml}</span>`);
}

export const showTuning = (digits) => showOsd(`<span class="osd-num">${esc(digits)}<i>_</i></span>`);
export const flash = (text) => showOsd(`<span class="osd-note">${esc(text)}</span>`);

// Tela cheia é a da moldura, não a do <video> (o botão nativo está desligado): assim o número do canal vai junto
export const isFullscreen = () => document.fullscreenElement === screen;

export function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  else if (current) screen.requestFullscreen().catch(() => flash("Não foi possível abrir em tela cheia"));
}

document.addEventListener("fullscreenchange", () => { if (isFullscreen()) showChannel(); });
video.addEventListener("dblclick", (e) => {
  e.preventDefault(); // o duplo clique nativo poria só o <video> em tela cheia
  toggleFullscreen();
});

function saveProgress() {
  if (!current || current.kind === "live" || !Number.isFinite(video.duration) || !video.duration) return;
  const t = video.currentTime, d = video.duration;
  progress.save(current.url, t, d);
  emit("progress", { entry: current, t, d });
}

video.addEventListener("playing", () => {
  blocked = false;
  setStatus("");
  if (current) emit("playing", current);
});
video.addEventListener("waiting", () => setStatus("Carregando…"));
video.addEventListener("pause", saveProgress);
video.addEventListener("timeupdate", () => {
  if (Date.now() - lastSave < SAVE_EVERY_MS) return;
  lastSave = Date.now();
  saveProgress();
});
video.addEventListener("ended", () => {
  saveProgress();
  if (current) emit("ended", current);
});
video.addEventListener("error", () => {
  if (!current || current.kind === "live") return; // erros do ao vivo ficam com o hls.js
  setStatus("O navegador não conseguiu tocar este vídeo (formato não suportado ou fora do ar). Use “Copiar link” e abra no VLC.");
});
