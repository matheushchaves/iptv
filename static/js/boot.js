// Entrada do Sofá: conta o que está carregando, com os números de verdade da lista (a espera pela lista e pelo tempo
// vira o show). Retrô: a tela de BIOS (memória contando, bipe, HD a cada linha) e o logo com o acorde. Moderno: a sala
// à noite vista do sofá; o abajur acende, a TV liga com o nome e os números do dia, e a câmera entra na TV, que vira o
// app. Qualquer tecla ou clique pula. Completa na primeira vez do dia em cada aparelho (e ao trocar de tema ou pedir
// para ver de novo).
import { $, esc } from "./util.js";
import { pixel } from "./pixel.js";
import { diskSeek, lampClick, postBeep, startupChime, tvOn, warmTone } from "./sound.js";

const LINE_MS = 220;
const STEP_MIN_MS = 420;     // cada item fica girando pelo menos isso, mesmo com o dado já guardado
const STEP_LIMIT_MS = 15000; // informação que demora mais que isso aparece como "sem resposta" (a página segue)
const MEMORY_MS = 1100;
const SPLASH_MS = 3200;      // o tempo do acorde inteiro
const DARK_MS = 600;     // a sala escura antes do clique do abajur
const LAMP_MS = 1500;    // a luz enchendo a sala
const TV_MS = 1000;      // a TV acendendo e o nome aparecendo
const CHIP_MIN_MS = 480;
const HOLD_MS = 1800;
const ZOOM_MS = 1150;    // a câmera entrando na TV
const TV_TEXT = 0.034;   // o tamanho do texto na tela da TV, em relação à largura dela
const FADE_MS = 500;
const SPIN = ["|", "/", "-", "\\"];
const DAY_KEY = "iptv.bootDay";
const today = () => new Date().toDateString();
const NO_ANSWER = "sem resposta";
// No celular não há tecla: tocar na tela pula do mesmo jeito (o toque chega como clique)
const SKIP = navigator.maxTouchPoints > 0 ? "Toque na tela para pular" : "Aperte qualquer tecla para pular";

export function shouldBoot() {
  try { return localStorage.getItem(DAY_KEY) !== today(); } catch { return true; }
}

function markBooted() {
  try { localStorage.setItem(DAY_KEY, today()); } catch { /* sem armazenamento: o boot volta amanhã do mesmo jeito */ }
}

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

/** O valor do passo, esperando pelo menos min (para dar tempo de ver) e no máximo STEP_LIMIT_MS. */
const settle = (value, min) => Promise.all([
  Promise.race([Promise.resolve(value).catch(() => NO_ANSWER), sleep(STEP_LIMIT_MS).then(() => NO_ANSWER)]),
  sleep(min),
]).then(([text]) => text);

// ---------- retrô: a BIOS ----------
async function retro(el, steps, alive) {
  el.innerHTML = `<pre class="post"></pre><p class="boot-skip">${SKIP}</p>`;
  const post = el.querySelector(".post");
  const print = (html) => post.insertAdjacentHTML("beforeend", `${html}\n`);
  postBeep();
  for (const line of ["Sofá BIOS v4.2.0, um sofá muito bem configurado", "Copyright (C) 1998-2026 Sofá Systems", ""]) {
    if (!alive()) return;
    print(esc(line));
    await sleep(LINE_MS);
  }
  // A memória contando, como nas BIOS de verdade
  post.insertAdjacentHTML("beforeend", `Memória: <span class="mem">0</span> KB`);
  const mem = post.lastElementChild;
  for (let kb = 64; kb <= 640; kb += 64) {
    if (!alive()) return;
    await sleep(MEMORY_MS / 10);
    mem.textContent = kb;
  }
  print(` ........................ <span class="ok">OK</span> (deve bastar para qualquer um)\n`);
  await sleep(LINE_MS);
  for (const { label, value } of steps) {
    if (!alive()) return;
    diskSeek();
    post.insertAdjacentHTML("beforeend", `${esc(label.padEnd(31, "."))} <span class="spin">|</span>`);
    const spin = post.lastElementChild;
    let k = 0;
    const turn = setInterval(() => { spin.textContent = SPIN[++k % SPIN.length]; }, 110);
    const text = await settle(value, STEP_MIN_MS);
    clearInterval(turn);
    spin.className = text === NO_ANSWER ? "bad" : "ok";
    spin.textContent = text;
    post.insertAdjacentHTML("beforeend", "\n");
    await sleep(LINE_MS);
  }
  if (!alive()) return;
  print("\nIniciando a área de trabalho...");
  await sleep(LINE_MS * 6);
  if (!alive()) return;
  el.innerHTML = `<div class="splash">${pixel("sofa", "Sofá")}
    <p class="splash-name">Sofá<sup>98</sup></p>
    <p class="splash-tag">Edição geek</p>
    <div class="splash-bar" aria-hidden="true"><i style="animation-duration:${SPLASH_MS}ms"></i></div>
  </div>`;
  startupChime();
  await sleep(SPLASH_MS + 300);
}

// ---------- moderno: a sala à noite, vista do sofá ----------
// Um desenho só (1600×900, sempre em 16:9): as luzes são camadas por cima que só mudam de opacidade, e a entrada na TV
// é um zoom do conjunto. As posições das camadas em % batem com as coordenadas do desenho.
const ROOM = `<svg class="mb-svg" viewBox="0 0 1600 900" preserveAspectRatio="none" aria-hidden="true">
  <rect width="1600" height="720" fill="#1d1524"/>
  <rect y="706" width="1600" height="14" fill="#2a2032"/>
  <rect y="720" width="1600" height="180" fill="#120d17"/>
  <rect x="1240" y="140" width="230" height="290" fill="#2a2032"/>
  <rect x="1252" y="152" width="206" height="266" fill="#0e1631"/>
  <circle cx="1405" cy="205" r="18" fill="#e9e3d0"/><circle cx="1397" cy="199" r="16" fill="#0e1631"/>
  <circle cx="1290" cy="190" r="2" fill="#c9c3e0"/><circle cx="1320" cy="250" r="1.5" fill="#c9c3e0"/>
  <circle cx="1425" cy="330" r="2" fill="#c9c3e0"/><circle cx="1280" cy="360" r="1.5" fill="#c9c3e0"/>
  <rect x="1351" y="152" width="8" height="266" fill="#2a2032"/><rect x="1252" y="281" width="206" height="8" fill="#2a2032"/>
  <ellipse cx="260" cy="712" rx="56" ry="9" fill="#0b080e"/>
  <rect x="256" y="300" width="8" height="412" fill="#0b080e"/>
  <path d="M215 215h90l25 85H190z" fill="#2e2337"/>
  <path d="M1202 640C1150 560 1120 520 1130 470c40 50 65 110 72 170zM1202 640c13-80 38-140 88-170-10 70-50 130-88 170zM1202 640c-12-60-2-120 13-190 20 70 7 140-13 190z" fill="#14201a"/>
  <rect x="1170" y="640" width="64" height="72" rx="6" fill="#120d17"/>
  <rect x="520" y="640" width="560" height="66" rx="6" fill="#120d17"/>
  <rect x="540" y="706" width="10" height="10" fill="#0b080e"/><rect x="1050" y="706" width="10" height="10" fill="#0b080e"/>
  <rect x="772" y="600" width="56" height="40" fill="#08060a"/>
  <rect x="470" y="210" width="660" height="390" rx="12" fill="#050307"/>
  <rect x="482" y="222" width="636" height="366" rx="4" fill="#0a0810"/>
  <rect x="30" y="760" width="170" height="200" rx="44" fill="#08060b"/>
  <rect x="1400" y="760" width="170" height="200" rx="44" fill="#08060b"/>
  <rect x="150" y="736" width="1300" height="230" rx="70" fill="#09060c"/>
  <path d="M800 752V900" stroke="#150f1a" stroke-width="4"/>
  <path class="mb-rim" d="M150 806a70 70 0 0 1 70-70h1160a70 70 0 0 1 70 70" fill="none" stroke="#f5a524" stroke-width="3"/>
</svg>
<i class="mb-dark"></i><i class="mb-light"></i><i class="mb-cone"></i><i class="mb-shade"></i><i class="mb-tvglow"></i>`;

/** A câmera entra na TV: o conjunto cresce em volta do centro da tela até ela cobrir a janela. */
function zoomIntoTv(el) {
  const room = el.querySelector(".mb-room");
  const r = el.querySelector(".mb-tv").getBoundingClientRect();
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  const scale = Math.max(innerWidth / r.width, innerHeight / r.height);
  room.style.transformOrigin = `${cx}px ${cy}px`;
  room.style.transform = `translate(${innerWidth / 2 - cx}px, ${innerHeight / 2 - cy}px) scale(${scale})`;
  el.classList.add("zoom");
}

async function modern(el, steps, alive) {
  el.innerHTML = `<div class="mb-room"><div class="mb-scene">${ROOM}
      <div class="mb-tv"><p class="mb-name">Sofá</p><ul class="mb-lines" aria-live="polite"></ul></div>
    </div></div>
    <p class="boot-skip">${SKIP}</p>`;
  const tv = el.querySelector(".mb-tv");
  tv.style.fontSize = `${tv.clientWidth * TV_TEXT}px`; // o texto acompanha o tamanho da TV (TV, Mac ou celular)
  await sleep(DARK_MS);
  if (!alive()) return;
  lampClick();
  warmTone();
  el.classList.add("lamp-on");
  await sleep(LAMP_MS);
  if (!alive()) return;
  tvOn();
  el.classList.add("tv-on");
  await sleep(TV_MS);
  const lines = el.querySelector(".mb-lines");
  for (const { label, value } of steps) {
    if (!alive()) return;
    const text = await settle(value, CHIP_MIN_MS);
    if (!alive()) return;
    if (text !== NO_ANSWER) lines.insertAdjacentHTML("beforeend", `<li><small>${esc(label)}</small><span>${esc(text)}</span></li>`);
  }
  await sleep(HOLD_MS);
  if (!alive()) return;
  zoomIntoTv(el);
  await sleep(ZOOM_MS);
}

/** steps: [{ label, value: texto ou Promise<texto>, retroOnly }]. Resolve quando termina ou quando alguém aperta algo. */
export function runBoot(steps, { retro: isRetro = true } = {}) {
  const el = $("#boot");
  el.hidden = false;
  el.className = "";
  let skipped = false;
  let finish;
  const done = new Promise((resolve) => { finish = resolve; });
  const skip = (e) => {
    e.preventDefault();
    e.stopImmediatePropagation();
    skipped = true;
    finish();
  };
  window.addEventListener("keydown", skip, true);
  el.addEventListener("click", skip);
  const alive = () => !skipped;
  const show = isRetro ? retro(el, steps, alive) : modern(el, steps.filter((s) => !s.retroOnly), alive);
  show.then(finish, finish);
  return done.then(async () => {
    window.removeEventListener("keydown", skip, true);
    el.removeEventListener("click", skip);
    markBooted();
    el.classList.add("out");
    await sleep(skipped ? 0 : FADE_MS);
    el.hidden = true;
    el.className = "";
    el.innerHTML = "";
  });
}
