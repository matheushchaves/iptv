// O início: o bem-vindo, o tempo, o que vale assistir agora, o mercado e o próximo foguete; embaixo, manchetes de
// tecnologia em português (Tecnoblog, Canaltech, TecMundo, Meio Bit). No tema retrô é a área
// de trabalho do Sofá 98 (janelas, ícones, barra de tarefas com Iniciar); no moderno, os mesmos blocos em cartões.
// A barra de tarefas é uma só para todas as telas (no retrô ela fica em todas; no moderno, só no início).
// Feita para o controle da TV: no início as setas andam entre os botões pela posição na tela (moveFocus); nas outras
// telas a barra de tarefas fica fora do caminho das setas (é do ponteiro do Magic Remote).
import { esc, hhmm, plural, ratingHtml } from "./util.js";
import { icon, weatherLook } from "./pixel.js";
import { movieOnAir, onAirCount } from "./live.js";
import { otherThemeLabel } from "./theme.js";
import { soundLabel } from "./sound.js";

const WATCH_ROWS = 3;
const TICK_MS = 1000;
const STATUS = { Go: "confirmado", TBD: "data a confirmar", TBC: "a confirmar", Hold: "em espera", "In Flight": "voando agora" };
const DIRS = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] };
// "Você sabia?": uma por dia, como as dicas do Windows antigo, ensinando os atalhos do controle
const TIPS = [
  "Digite o número do canal no controle para ir direto a ele.",
  "O 0 sozinho volta para o canal anterior, como na TV a cabo.",
  "Em tela cheia, OK abre a lista rápida de canais por cima do vídeo.",
  "Em tela cheia, ← e → mostram o que está passando e o que vem depois.",
  "A estrela no canto das capas guarda o filme ou a série na Minha lista, que a TV, o computador e o celular dividem.",
  "Se uma versão do canal travar, o Sofá passa sozinho para outra (FHD, HD, SD…).",
  "“Filmes agora” mostra os filmes do catálogo passando na TV, do mais bem avaliado para o menos.",
  "Pegou o filme no meio? No guia do canal, “Assistir do começo” abre ele do início.",
];
const tipOfDay = (now) => TIPS[Math.floor(now / 86400000) % TIPS.length];
const SECTIONS = { live: ["tv", "Ao vivo"], movie: ["film", "Filmes"], series: ["series", "Séries"], show: ["series", "Séries"] };
const ICONS = [["#ao-vivo", "tv", "Ao vivo"], ["#filmes", "film", "Filmes"], ["#series", "series", "Séries"], ["#filmes?g=%40saved", "star", "Minha lista"]];

const brl = (v, digits = 2) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
const pct = (v) => `${v > 0 ? "+" : ""}${v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
const longDate = (d) => d.toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
// Quando a manchete saiu: a hora, se foi hoje; senão, o dia
const published = (at) => {
  const d = new Date(at);
  return d.toDateString() === new Date().toDateString() ? hhmm(at) : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
};
const weekday = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString("pt-BR", { weekday: "short" }).replace(".", "");

function greeting(now) {
  const h = now.getHours();
  return h >= 5 && h < 12 ? "Bom dia" : h >= 12 && h < 18 ? "Boa tarde" : "Boa noite";
}

function win(cls, title, iconName, body) {
  return `<section class="win ${cls}" aria-label="${esc(title)}">
    <header class="win-title"><h2>${iconName ? icon(iconName) : ""}<span>${esc(title)}</span></h2>
      <span class="win-ctl" aria-hidden="true"><i>_</i><i>□</i><i>×</i></span></header>
    <div class="win-body">${body}</div>
  </section>`;
}

const empty = (text) => `<p class="win-empty">${esc(text)}</p>`;

function helloWin({ name, desk, channels, last }) {
  const now = new Date();
  const w = desk && desk.weather, place = desk && desk.place, acct = desk && desk.account;
  const lines = [];
  if (w) {
    const look = weatherLook(w.now.code, w.now.day);
    lines.push(`Lá fora: ${w.now.temp}°, ${look.text}${place ? ` em ${esc(place.city)}` : ""}.`);
  }
  if (channels.length) {
    const movies = channels.filter((c) => movieOnAir(c)).length;
    lines.push(`Na TV: ${plural(onAirCount(channels), "canal", "canais")} com programação${movies ? `, ${plural(movies, "filme passando", "filmes passando")}` : ""}.`);
  }
  if (acct && acct.expires) {
    const days = Math.ceil((acct.expires * 1000 - Date.now()) / 86400000);
    lines.push(`Lista: conta ${acct.status === "Active" ? "ativa" : esc(acct.status)} até ${new Date(acct.expires * 1000).toLocaleDateString("pt-BR")} (${plural(days, "dia", "dias")}); ${acct.active} de ${acct.max} ${acct.max === 1 ? "conexão" : "conexões"} em uso.`);
  }
  const go = last
    ? `<button type="button" class="btn98 primary" data-action="continue" data-autofocus>▶ Continuar: ${esc(last.name)}</button>`
    : `<a class="btn98 primary" href="#ao-vivo" data-autofocus>▶ Ver TV ao vivo</a>`;
  return win("win-hello", "Bem-vindo ao Sofá", "sofa", `
    <p class="hello-greet">${greeting(now)}${name ? `, ${esc(name)}` : ""}.</p>
    <p class="hello-clock"><span data-clock>${hhmm(now)}</span><small>${esc(longDate(now))}</small></p>
    <ul class="hello-lines">${lines.map((l) => `<li>${l}</li>`).join("")}</ul>
    <div class="win-actions">${go}<a class="btn98" href="#ao-vivo?g=%40now">Agora na TV</a></div>
    <p class="tip"><b>Você sabia?</b> ${esc(tipOfDay(now.getTime()))}</p>`);
}

function weatherWin(desk) {
  const w = desk && desk.weather, place = desk && desk.place;
  const title = place ? `Tempo em ${place.city}` : "Tempo";
  if (!w) return win("win-weather", title, "sun", empty(desk ? "A previsão não respondeu agora. Tento de novo daqui a pouco." : "Buscando a previsão…"));
  const look = weatherLook(w.now.code, w.now.day);
  const hours = w.hours.map((h) => `<li><span>${h.hour}</span>${icon(weatherLook(h.code, h.day).icon)}<b>${h.temp}°</b>
    <small>${h.rain ? `${h.rain}%` : ""}</small></li>`).join("");
  const days = w.days.map((d) => `<li><span>${esc(weekday(d.date))}</span>${icon(weatherLook(d.code).icon)}
    <b>${d.max}°</b><small>${d.min}°</small></li>`).join("");
  return win("win-weather", title, look.icon, `
    <div class="wx-now">${icon(look.icon, look.text)}<p><b>${w.now.temp}°</b><span>${esc(look.text)}</span></p></div>
    <p class="wx-more">Sensação de ${w.now.feels}°, umidade ${w.now.humidity}%, vento ${w.now.wind} km/h</p>
    <ul class="wx-row">${hours}</ul>
    <ul class="wx-row wx-days">${days}</ul>`);
}

/** O que vale assistir: o que ficou pela metade e os filmes passando agora (pela nota). */
function watchWin({ channels, recent }) {
  const now = Date.now();
  const movies = channels.filter((c) => movieOnAir(c, now))
    .sort((a, b) => (movieOnAir(b, now).vod.rating || 0) - (movieOnAir(a, now).vod.rating || 0)).slice(0, WATCH_ROWS);
  const rows = movies.map((c) => {
    const p = movieOnAir(c, now);
    return `<li><button type="button" class="watch-row" data-watch="${c.id}">
      <span class="watch-title">${esc(p.title)}${ratingHtml(p.vod.rating)}</span>
      <small>${esc(c.name)}, até ${hhmm(p.stop)}</small></button></li>`;
  });
  const resume = recent.slice(0, 1).map((r) => `<li><button type="button" class="watch-row" data-resume="${esc(r.kind)}">
      <span class="watch-title">${esc(r.showName || r.title)}</span>
      <small>Continuar ${r.kind === "series" ? `temporada ${r.season}, episódio ${r.num}` : "de onde parou"}</small></button></li>`);
  const all = [...resume, ...rows];
  return win("win-watch", "Para assistir agora", "film", all.length
    ? `<ul class="watch-list">${all.join("")}</ul>`
    : empty("Nenhum filme do catálogo passando agora. Dá uma olhada em “Agora na TV”."));
}

const trend = (change) => `<td class="${change > 0 ? "up" : change < 0 ? "down" : ""}">${change > 0 ? "▲" : change < 0 ? "▼" : "•"} ${pct(change)}</td>`;

/** A bolsa (Ibovespa em destaque e as ações mais negociadas, da B3) e o câmbio (dólar e bitcoin). */
function marketWin(desk) {
  const b3 = (desk && desk.b3) || [], fx = ((desk && desk.markets) || []).filter((q) => q.code === "USD" || q.code === "BTC");
  if (!b3.length && !fx.length) return win("win-market", "Mercado", "chart", empty(desk ? "As cotações não responderam agora." : "Buscando as cotações…"));
  const ibov = b3.find((q) => q.symbol === "IBOV");
  const head = ibov ? `<p class="ibov"><span>Ibovespa</span><b>${Math.round(ibov.value).toLocaleString("pt-BR")} pts</b>
    <em class="${ibov.change > 0 ? "up" : ibov.change < 0 ? "down" : ""}">${ibov.change > 0 ? "▲" : ibov.change < 0 ? "▼" : "•"} ${pct(ibov.change)}</em></p>` : "";
  const stocks = b3.filter((q) => q.symbol !== "IBOV").map((q) => `<tr><th scope="row">${esc(q.name)} <small>${esc(q.symbol)}</small></th>
    <td>${brl(q.value)}</td>${trend(q.change)}</tr>`);
  const money = fx.map((q) => `<tr><th scope="row">${esc(q.name)}</th><td>${q.value >= 1000 ? brl(q.value, 0) : brl(q.value)}</td>${trend(q.change)}</tr>`);
  const note = ibov ? `B3 às ${esc(ibov.at)} (com atraso); variação do dia` : "Variação do dia, em reais";
  return win("win-market", "Mercado", "chart", `${head}<table class="quotes">${[...stocks, ...money].join("")}</table><p class="win-note">${note}</p>`);
}

function launchWin(desk) {
  const l = desk && desk.launch;
  if (!l) return win("win-launch", "Próximo lançamento", "rocket", empty(desk ? "A agenda de foguetes não respondeu agora." : "Buscando a agenda de foguetes…"));
  return win("win-launch", "Próximo lançamento", "rocket", `
    <p class="launch-mission">${esc(l.mission)}</p>
    <p class="launch-rocket">${esc(l.rocket)}</p>
    <p class="launch-count" data-countdown="${l.net}">${countdown(l.net)}</p>
    <p class="win-note">${esc(l.location)}${STATUS[l.status] ? `, ${STATUS[l.status]}` : ""}</p>`);
}

function countdown(net) {
  const s = Math.max(0, Math.floor((net - Date.now()) / 1000));
  const pad = (n) => String(n).padStart(2, "0");
  const d = Math.floor(s / 86400);
  return `T− ${d ? `${d}d ` : ""}${pad(Math.floor(s / 3600) % 24)}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}`;
}

// Redesenhar (chegou o tempo, a lista terminou de carregar) não pode tirar o foco do controle do lugar
// (o mesmo link aparece no ícone, na janela e no menu: a chave inclui onde ele está)
function focusKey(node) {
  if (node.hasAttribute("data-autofocus")) return "[data-autofocus]";
  const box = node.closest(".desk-icons, .win, .task-main, #startMenu");
  const scope = !box ? "" : box.id ? `#${box.id} ` : `.${Array.from(box.classList).join(".")} `;
  for (const attr of ["data-action", "data-watch", "data-resume", "href"]) {
    if (node.hasAttribute(attr)) return `${scope}[${attr}="${CSS.escape(node.getAttribute(attr))}"]`;
  }
  return null;
}

function keepingFocus(container, draw) {
  const active = document.activeElement;
  const keep = container.contains(active) ? focusKey(active) : null;
  draw();
  const again = keep && container.querySelector(keep);
  if (again) again.focus({ preventScroll: true });
}

/** data: { name, desk, channels, recent, last: canal para continuar } */
export function render(el, data) {
  keepingFocus(el, () => {
    el.innerHTML = `<div class="desk" id="desk">
      <nav class="desk-icons" aria-label="Atalhos">${ICONS.map(([href, name, text]) =>
        `<a class="desk-icon" href="${href}">${icon(name)}<span>${esc(text)}</span></a>`).join("")}</nav>
      <div class="desk-windows">${helloWin(data)}${weatherWin(data.desk)}${watchWin(data)}${marketWin(data.desk)}${launchWin(data.desk)}</div>
    </div>`;
  });
}

function startMenu() {
  const items = [
    ["#inicio", "sofa", "Área de trabalho"], ["#ao-vivo", "tv", "Ao vivo"], ["#ao-vivo?g=%40now", "", "Agora na TV"],
    ["#ao-vivo?g=%40movies", "", "Filmes agora"], ["#filmes", "film", "Filmes"], ["#series", "series", "Séries"],
    ["#filmes?g=%40saved", "star", "Minha lista"],
  ];
  return `<div class="start-menu" id="startMenu" hidden>
    <p class="start-band" aria-hidden="true">Sofá<b>98</b></p>
    <ul>${items.map(([href, name, text]) => `<li><a href="${href}">${name ? icon(name) : "<i></i>"}${esc(text)}</a></li>`).join("")}
      <li class="sep" aria-hidden="true"></li>
      <li><button type="button" data-action="theme"><i></i>${otherThemeLabel()}</button></li>
      <li><button type="button" data-action="sound"><i></i>${soundLabel()}</button></li>
      <li><button type="button" data-action="lists"><i></i>Listas…</button></li>
      <li><button type="button" data-action="reboot"><i></i>Reiniciar o Sofá</button></li>
    </ul>
  </div>`;
}

/** A barra de tarefas: Iniciar, o programa aberto (fora do início) ou as manchetes (no início), tempo e relógio. */
export function renderTaskbar({ desk, view }) {
  const el = document.getElementById("taskbar");
  const news = (desk && desk.news) || [];
  const w = desk && desk.weather;
  // Campo que faltar (dado guardado de outra versão) some em vez de virar "undefined" na tela
  const headlines = news.filter((n) => n && n.title).map((n) => `<span>${esc(n.title)}
    <small>${[esc(n.source || ""), n.at ? published(n.at) : ""].filter(Boolean).join(", ")}</small></span>`).join("");
  const section = SECTIONS[view];
  // Fora do início, a barra é do ponteiro: as setas do controle continuam só na lista
  const tab = view === "home" ? "" : ' tabindex="-1"';
  const wasOpen = startOpen();
  keepingFocus(el, () => {
    el.innerHTML = `<div class="task-main">
      <button type="button" class="start" data-action="start" aria-expanded="false" aria-controls="startMenu"${tab}>${icon("sofa")}<span>Iniciar</span></button>
      <span class="task-sep" aria-hidden="true"></span>
      ${section ? `<a class="task-app" href="#inicio"${tab} title="Voltar à área de trabalho">${icon(section[0])}<span>Sofá — ${section[1]}</span></a>` : ""}
      <button type="button" class="replay" data-action="reboot"${tab}>Ver a entrada</button>
      <div class="ticker" aria-label="Manchetes de tecnologia">${news.length && !section
        ? `<div class="ticker-run" style="animation-duration:${Math.max(40, news.reduce((n, x) => n + x.title.length, 0) / 3)}s">
            <b>Notícias</b>${headlines}<b aria-hidden="true">Notícias</b>${headlines.replace(/<span>/g, '<span aria-hidden="true">')}</div>`
        : ""}</div>
      <div class="tray">${w ? `${icon(weatherLook(w.now.code, w.now.day).icon)}<span>${w.now.temp}°</span>` : ""}<b data-clock>${hhmm(new Date())}</b></div>
    </div>${startMenu()}`;
  });
  if (wasOpen) toggleStart(true);
}

// Relógios e a contagem do foguete andam sozinhos, em qualquer tela
export function startClock() {
  setInterval(() => {
    const now = new Date();
    document.querySelectorAll("[data-clock]").forEach((c) => { c.textContent = hhmm(now); });
    document.querySelectorAll("[data-countdown]").forEach((c) => { c.textContent = countdown(Number(c.dataset.countdown)); });
  }, TICK_MS);
}

export const startOpen = () => { const m = document.getElementById("startMenu"); return !!m && !m.hidden; };

export function toggleStart(open = !startOpen()) {
  const menu = document.getElementById("startMenu");
  const button = document.querySelector("#taskbar .start");
  if (!menu || !button) return;
  menu.hidden = !open;
  button.setAttribute("aria-expanded", String(open));
  if (open) menu.querySelector("a, button").focus();
  else if (menu.contains(document.activeElement)) button.focus();
}

/** Foca o botão principal (Continuar) quando nada do início está focado. */
export function focusFirst() {
  const desk = document.getElementById("desk");
  const bar = document.getElementById("taskbar");
  if (desk && !desk.contains(document.activeElement) && !bar.contains(document.activeElement)) {
    (desk.querySelector("[data-autofocus]") || desk.querySelector("a, button")).focus();
  }
}

/** Setas do controle no início: vai para o botão mais perto naquela direção, preferindo o que está alinhado (↓ do
 *  botão principal desce para a janela de baixo, não para o ícone da lateral). No menu Iniciar, só dentro dele. */
export function moveFocus(key) {
  const dir = DIRS[key];
  const roots = startOpen() ? [document.getElementById("startMenu")] : [document.getElementById("desk"), document.getElementById("taskbar")];
  if (!dir || !roots[0]) return false;
  const all = [].concat(...roots.map((r) => Array.from(r.querySelectorAll("a[href], button"))))
    .filter((b) => b.offsetParent !== null && !b.closest("[hidden]"));
  const cur = document.activeElement;
  if (!all.includes(cur)) {
    focusFirst();
    return true;
  }
  const r = cur.getBoundingClientRect(), across = dir[0] !== 0;
  const gap = (q) => (across ? (dir[0] > 0 ? q.left - r.right : r.left - q.right) : (dir[1] > 0 ? q.top - r.bottom : r.top - q.bottom));
  const overlap = (q) => (across ? Math.min(r.bottom, q.bottom) - Math.max(r.top, q.top) : Math.min(r.right, q.right) - Math.max(r.left, q.left));
  const offset = (q) => (across ? Math.abs((q.top + q.bottom - r.top - r.bottom) / 2) : Math.abs((q.left + q.right - r.left - r.right) / 2));
  const ahead = all.filter((b) => b !== cur).map((b) => ({ b, q: b.getBoundingClientRect() })).filter(({ q }) => gap(q) >= -1);
  const aligned = ahead.filter(({ q }) => overlap(q) > 0);
  const pool = aligned.length ? aligned : ahead;
  const score = ({ q }) => gap(q) + (aligned.length ? 0 : 2 * offset(q));
  const best = pool.sort((a, b) => score(a) - score(b))[0];
  if (best) best.b.focus();
  return true;
}
