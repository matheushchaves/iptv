// Entrada do Sofá: conta o que está carregando, com os números de verdade da lista (a espera pela lista e pelo tempo
// vira o show), e depois mostra o logo. No tema retrô é a tela de BIOS, com bipe, HD e acorde; no moderno, uma lista
// discreta e o nome que acende. Qualquer tecla ou clique pula. Completa na primeira vez do dia em cada aparelho.
import { $, esc } from "./util.js";
import { pixel } from "./pixel.js";
import { diskSeek, postBeep, startupChime } from "./sound.js";

const LINE_MS = 120;
const STEP_LIMIT_MS = 15000; // informação que demora mais que isso aparece como "sem resposta" (a página segue)
const SPLASH_MS = 1600;
const FADE_MS = 350;
const SPIN = ["|", "/", "-", "\\"];
const DAY_KEY = "iptv.bootDay";
const today = () => new Date().toDateString();

export function shouldBoot() {
  try { return localStorage.getItem(DAY_KEY) !== today(); } catch { return true; }
}

function markBooted() {
  try { localStorage.setItem(DAY_KEY, today()); } catch { /* sem armazenamento: o boot volta amanhã do mesmo jeito */ }
}

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const HEADER = [
  "Sofá BIOS v4.2.0, um sofá muito bem configurado",
  "Copyright (C) 1998-2026 Sofá Systems",
  "",
  "Memória: 640 KB .............................. OK (deve bastar para qualquer um)",
  "",
];

const SPLASH = {
  retro: () => `${pixel("sofa", "Sofá")}
    <p class="splash-name">Sofá<sup>98</sup></p>
    <p class="splash-tag">Edição geek</p>`,
  modern: () => `<p class="splash-name">Sofá</p><p class="splash-tag">Pronto para assistir</p>`,
};

/** steps: [{ label, value: texto ou Promise<texto> }]. Resolve quando termina ou quando alguém aperta algo. */
export function runBoot(steps, { retro = true } = {}) {
  const el = $("#boot");
  el.innerHTML = `${retro ? "" : `<p class="boot-title">Preparando o Sofá</p>`}<pre class="post"></pre>
    <p class="boot-skip">Aperte qualquer tecla para pular</p>`;
  el.hidden = false;
  el.classList.remove("out");
  const post = el.querySelector(".post");
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
  const print = (html) => post.insertAdjacentHTML("beforeend", `${html}\n`);

  async function show() {
    if (retro) postBeep();
    for (const line of retro ? HEADER : []) {
      if (skipped) return;
      print(esc(line));
      await sleep(LINE_MS);
    }
    for (const { label, value } of steps) {
      if (skipped) return;
      if (retro) diskSeek();
      post.insertAdjacentHTML("beforeend", retro ? `${esc(label.padEnd(31, "."))} <span class="spin">|</span>`
        : `<span class="step">${esc(label)}</span> <span class="spin">|</span>`);
      const spin = post.lastElementChild;
      let k = 0;
      const turn = setInterval(() => { spin.textContent = SPIN[++k % SPIN.length]; }, 110);
      const text = await Promise.race([
        Promise.resolve(value).catch(() => "sem resposta"),
        sleep(STEP_LIMIT_MS).then(() => "sem resposta"),
      ]);
      clearInterval(turn);
      spin.className = text === "sem resposta" ? "bad" : "ok";
      spin.textContent = text;
      post.insertAdjacentHTML("beforeend", "\n");
      await sleep(LINE_MS);
    }
    if (skipped) return;
    if (retro) print("\nIniciando a área de trabalho...");
    await sleep(LINE_MS * 4);
    if (skipped) return;
    el.innerHTML = `<div class="splash">${SPLASH[retro ? "retro" : "modern"]()}
      <div class="splash-bar" aria-hidden="true"><i style="animation-duration:${SPLASH_MS}ms"></i></div>
    </div>`;
    if (retro) startupChime();
    await sleep(SPLASH_MS + 200);
    finish();
  }

  show();
  return done.then(async () => {
    window.removeEventListener("keydown", skip, true);
    markBooted();
    el.classList.add("out");
    await sleep(skipped ? 0 : FADE_MS);
    el.hidden = true;
    el.innerHTML = "";
  });
}
