// Ninguém assistindo: a conta da lista Xtream só tem uma conexão, e um canal esquecido tocando (o Mac com a aba
// aberta, a TV ligada na sala vazia) impede o outro aparelho de assistir.
// Página escondida por uns minutos para o vídeo; horas sem mexer em nada, pergunta se ainda tem alguém vendo.
import { $, clock } from "./util.js";
import { api } from "./api.js";
import * as player from "./player.js";

const HIDDEN_STOP_MS = 10 * 60 * 1000;
const IDLE_ASK_MS = 3 * 60 * 60 * 1000;
const ANSWER_MS = 2 * 60 * 1000;
const CHECK_MS = 30 * 1000;
const ACTIVITY = ["keydown", "pointerdown", "mousemove", "wheel", "touchstart"];

const el = $("#idle");
let lastActivity = Date.now();
let hiddenTimer = null;
let deadline = 0;
let countdown = null;

const asking = () => !el.hidden;

function stopFor(reason, message) {
  const p = player.nowPlaying();
  if (!p) return;
  dismiss();
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  player.stop();
  player.setStatus(message);
  api.log(`${p.num ? `${p.num} ` : ""}${p.title}: parado (${reason})`).catch(() => {});
}

function render() {
  const left = Math.max(0, deadline - Date.now());
  el.innerHTML = `<p class="idle-title">Ainda está assistindo?</p>
    <p>Aperte qualquer botão para continuar. Sem resposta, o vídeo para em <b>${clock(left / 1000)}</b>.</p>`;
  if (left) return;
  stopFor("ninguém mexeu em 3 horas", "O vídeo parou porque ninguém mexeu no controle por 3 horas. Escolha de novo para voltar.");
}

function ask() {
  deadline = Date.now() + ANSWER_MS;
  el.hidden = false;
  render();
  countdown = setInterval(render, 1000);
}

function dismiss() {
  el.hidden = true;
  clearInterval(countdown);
}

// Responder à pergunta não pode também trocar de canal ou abrir a lista: a tecla só diz "estou aqui"
function onActivity(e) {
  lastActivity = Date.now();
  if (!asking()) return;
  dismiss();
  if (e.type === "keydown" || e.type === "pointerdown") {
    e.preventDefault();
    e.stopImmediatePropagation();
  }
}

// Rádio (só áudio) com a página escondida é alguém ouvindo enquanto faz outra coisa: esse continua
function onVisibility() {
  clearTimeout(hiddenTimer);
  if (!document.hidden) return;
  hiddenTimer = setTimeout(() => {
    if (!document.hidden || !$("#video").videoWidth) return;
    stopFor("página escondida por 10 min",
      "O vídeo parou porque a página ficou escondida por 10 minutos, para não ocupar a conexão da lista. Escolha de novo para voltar.");
  }, HIDDEN_STOP_MS);
}

ACTIVITY.forEach((type) => window.addEventListener(type, onActivity, { capture: true, passive: type !== "keydown" && type !== "pointerdown" }));
document.addEventListener("visibilitychange", onVisibility);
setInterval(() => {
  if (!asking() && player.nowPlaying() && !document.hidden && Date.now() - lastActivity > IDLE_ASK_MS) ask();
}, CHECK_MS);
player.on("change", (p) => { if (!p) dismiss(); });
