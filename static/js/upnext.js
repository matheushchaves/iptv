// "Próximo episódio" nos créditos: quando faltam uns 40 s do episódio, um aviso por cima do vídeo (também na tela
// cheia) conta 10 s e passa para o próximo. OK vai na hora; "Ver os créditos" fica, e no fim do arquivo o próximo
// entra do mesmo jeito. A contagem anda com o vídeo: pausou, ela para. As teclas vêm do main.js, como na lista
// rápida: o foco fica onde está, e na tela cheia da TV o Voltar nem chega à página (← → e OK chegam).
import { $, esc } from "./util.js";
import * as player from "./player.js";

const LEAD_S = 40;        // quanto antes do fim o aviso aparece: o tamanho dos créditos na maioria das séries
const COUNT_S = 10;       // quanto ele conta antes de passar sozinho
const MIN_LENGTH_S = 300; // vídeo curto (ou sem duração conhecida) não ganha aviso
const BACK_KEY = 461;     // botão Voltar do controle da LG (webOS)

const el = $("#upnext");
const video = $("#video");
let findNext = () => null;
let playNext = () => {};
let shownFor = null; // o episódio com o aviso aberto
let stayedOn = null; // o episódio em que a pessoa escolheu ver os créditos
let startedAt = 0;   // o ponto do vídeo em que a contagem começou
let next = null;
let choice = 0;      // 0: assistir agora; 1: ver os créditos

export const isOpen = () => !el.hidden;

/** next(entry): o episódio seguinte de uma entrada, ou nada; play(entry, next): toca o seguinte. */
export function init({ next: nextFn, play }) {
  findNext = nextFn;
  playNext = play;
}

export function close() {
  el.hidden = true;
  shownFor = null;
}

const label = (n) => `T${n.season} E${n.episode.num}${/^epis[óo]dio \d+$/i.test(n.episode.title) ? "" : `: ${n.episode.title}`}`;

function choose(i) {
  choice = i;
  el.querySelectorAll("[data-up]").forEach((b, k) => b.setAttribute("aria-selected", String(k === choice)));
}

function open(entry, t) {
  shownFor = entry.url;
  startedAt = t;
  el.innerHTML = `<p class="up-title">Próximo episódio em <b class="up-count">${COUNT_S}</b> s</p>
    <p class="up-what">${esc(label(next))}</p>
    <div class="up-actions">
      <button type="button" class="btn primary" data-up="go">Assistir agora</button>
      <button type="button" class="btn" data-up="stay">Ver os créditos</button>
    </div>`;
  choose(0);
  el.hidden = false;
}

function go() {
  const entry = player.nowPlaying(), n = next;
  close();
  if (entry && n) playNext(entry, n);
}

function stay() {
  stayedOn = shownFor;
  close();
}

function tick() {
  const entry = player.nowPlaying();
  const d = video.duration, t = video.currentTime;
  if (!entry || entry.kind !== "episode" || !Number.isFinite(d) || d < MIN_LENGTH_S || stayedOn === entry.url) {
    if (isOpen()) close();
    return;
  }
  if (d - t > LEAD_S) { // ainda não chegou nos créditos, ou voltou para antes deles
    if (isOpen()) close();
    return;
  }
  if (shownFor !== entry.url) {
    next = findNext(entry);
    if (!next) return; // último episódio: o vídeo só acaba
    open(entry, t);
  }
  if (t < startedAt) startedAt = t; // voltou um pouco dentro dos créditos: a contagem recomeça dali
  const left = Math.ceil(COUNT_S - (t - startedAt));
  if (left <= 0) return go();
  el.querySelector(".up-count").textContent = left;
}

/** Teclas com o aviso aberto: ← → escolhem, OK confirma, Voltar e Esc ficam nos créditos. Devolve se usou a tecla. */
export function key(e) {
  if (e.key === "ArrowLeft" || e.key === "ArrowRight") choose(e.key === "ArrowLeft" ? 0 : 1);
  else if (e.key === "Enter") (choice === 0 ? go : stay)();
  else if (e.key === "Escape" || e.keyCode === BACK_KEY) stay();
  else return false;
  return true;
}

video.addEventListener("timeupdate", tick);
el.addEventListener("click", (e) => {
  const b = e.target.closest("[data-up]");
  if (b) (b.dataset.up === "go" ? go : stay)();
});
