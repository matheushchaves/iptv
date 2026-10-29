// Lista rápida da tela cheia: aparece por cima do vídeo com os canais da categoria e o que passa agora.
// Só desenha as linhas à vista (a categoria "Todos" tem quase 2 mil canais e a TV é fraca).
import { $, esc, groupNote, hhmm, meter, nowProg, ratingHtml } from "./util.js";
import { downSince } from "./live.js";

const el = $("#zapper");
const ROWS = 7; // ímpar: o canal marcado fica no meio
const HIDE_MS = 8000;

let list = [];
let index = 0;
let title = "";
let isPlaying = () => false;
let downNow = () => new Map();
let hideTimer = null;

export const isOpen = () => !el.hidden;
export const selected = () => list[index];
export const pick = (i) => list[i];

/** channels: a lista em que ↑↓ andam; at: índice marcado; playing(c): se é o canal que está passando;
 *  down(): Map link -> quando a versão não abriu. */
export function open(channels, { at, heading, playing, down }) {
  list = channels;
  title = heading;
  isPlaying = playing;
  downNow = down;
  select(at);
}

export function select(i) {
  if (!list.length) return;
  index = (i + list.length) % list.length;
  el.hidden = false;
  render();
  clearTimeout(hideTimer);
  hideTimer = setTimeout(close, HIDE_MS);
}

export const move = (step) => select(index + step);

export function close() {
  el.hidden = true;
  clearTimeout(hideTimer);
}

/** O canal que está passando mudou: remarca, se a lista estiver aberta. */
export function refresh() {
  if (isOpen()) render();
}

// Com mais canais que linhas, o marcado fica no meio e a lista dá a volta, como o ↑↓
function visible() {
  if (list.length <= ROWS) return list.map((_, i) => i);
  const half = (ROWS - 1) / 2;
  return Array.from({ length: ROWS }, (_, k) => (index - half + k + list.length) % list.length);
}

function row(i, now, down) {
  const c = list[i];
  const p = nowProg(c.epg || [], now);
  const downAt = downSince(c, down);
  const sub = downAt ? `Não abriu às ${hhmm(downAt)}` : p ? p.title : groupNote(c.group);
  return `<li class="zap-row${downAt ? " down" : ""}" aria-selected="${i === index}" aria-current="${isPlaying(c)}">
    <button type="button" data-zap="${i}" tabindex="-1">
      <span class="zap-num">${c.num}</span>
      <span class="zap-name">${esc(c.name)}</span>
      <span class="zap-line"><span class="zap-now">${esc(sub)}</span>${p && p.vod && !downAt ? ratingHtml(p.vod.rating) : ""}</span>
      ${p && !downAt ? meter((now - p.start) / (p.stop - p.start)) : ""}
    </button>
  </li>`;
}

function render() {
  const now = Date.now(), down = downNow();
  el.innerHTML = `<p class="zap-head"><b>${esc(title)}</b><span>${index + 1} de ${list.length}</span></p>
    <ol>${visible().map((i) => row(i, now, down)).join("")}</ol>`;
}
