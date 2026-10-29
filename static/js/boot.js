// Entrada do Sofá: conta o que está carregando, com os números de verdade da lista (a espera pela lista e pelo tempo
// vira o show). Retrô: a tela de BIOS (memória contando, bipe, HD a cada linha) e o logo com o acorde. Moderno: a sala
// escura, o abajur acende, o nome aparece e os números do dia chegam um a um em cartões. Qualquer tecla ou clique pula.
// Completa na primeira vez do dia em cada aparelho (e ao trocar de tema ou pedir para ver de novo).
import { $, esc } from "./util.js";
import { pixel } from "./pixel.js";
import { diskSeek, lampClick, postBeep, startupChime, warmTone } from "./sound.js";

const LINE_MS = 220;
const STEP_MIN_MS = 420;     // cada item fica girando pelo menos isso, mesmo com o dado já guardado
const STEP_LIMIT_MS = 15000; // informação que demora mais que isso aparece como "sem resposta" (a página segue)
const MEMORY_MS = 1100;
const SPLASH_MS = 3200;      // o tempo do acorde inteiro
const LAMP_MS = 1500;
const CHIP_MIN_MS = 480;
const HOLD_MS = 1800;
const FADE_MS = 500;
const SPIN = ["|", "/", "-", "\\"];
const DAY_KEY = "iptv.bootDay";
const today = () => new Date().toDateString();
const NO_ANSWER = "sem resposta";

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
  el.innerHTML = `<pre class="post"></pre><p class="boot-skip">Aperte qualquer tecla para pular</p>`;
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

// ---------- moderno: o abajur acende ----------
async function modern(el, steps, alive) {
  el.innerHTML = `<div class="lamp" aria-hidden="true"></div>
    <div class="m-boot"><p class="m-name">Sofá</p><ul class="m-chips" aria-live="polite"></ul></div>
    <p class="boot-skip">Aperte qualquer tecla para pular</p>`;
  await sleep(400);
  if (!alive()) return;
  lampClick();
  warmTone();
  el.classList.add("on");
  await sleep(LAMP_MS * 0.6);
  if (!alive()) return;
  el.querySelector(".m-name").classList.add("in");
  await sleep(LAMP_MS * 0.6);
  const chips = el.querySelector(".m-chips");
  for (const { label, value } of steps) {
    if (!alive()) return;
    const text = await settle(value, CHIP_MIN_MS);
    if (!alive()) return;
    if (text !== NO_ANSWER) chips.insertAdjacentHTML("beforeend", `<li><small>${esc(label)}</small>${esc(text)}</li>`);
  }
  await sleep(HOLD_MS);
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
