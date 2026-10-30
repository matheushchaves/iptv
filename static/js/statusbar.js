// Barra de status do retrô, como a dos programas dos anos 90: à esquerda, o que o OK faz no que está marcado (a ajuda
// de rodapé da época, útil no controle); à direita, o que está tocando. No tema moderno ela fica escondida.
import { $, esc, hhmm, nowProg } from "./util.js";

const bar = $("#statusbar");
const DEFAULT_HELP = {
  live: "Escolha um canal e aperte OK",
  movie: "Escolha um filme e aperte OK",
  series: "Escolha uma série e aperte OK",
  show: "Escolha um episódio e aperte OK",
};
// O primeiro que servir no elemento marcado (o canal tocando vem antes do canal qualquer)
const HELP = [
  [".ch[aria-current='true']", "OK de novo abre a tela cheia; CH+ e CH− trocam de canal"],
  [".ch", "OK assiste; CH+ e CH− trocam de canal; 0 volta ao anterior"],
  [".fav", "OK põe ou tira dos favoritos"],
  [".rail a", "OK abre a categoria"],
  [".version", "OK troca para esta versão do canal"],
  [".save", "OK põe ou tira da Minha lista"],
  [".card", "OK abre"],
  [".ep", "OK assiste o episódio"],
];

let help = "";
let playing = "Nada tocando";

const draw = () => {
  bar.innerHTML = `<span class="sb-help">${esc(help)}</span><span class="sb-playing">${esc(playing)}</span>`;
};

/** el: o que tem o foco agora; view: a seção aberta (para a ajuda de quando nada está marcado). */
export function showHelp(el, view) {
  const hit = el && el.matches ? HELP.find(([selector]) => el.matches(selector)) : null;
  help = hit ? hit[1] : DEFAULT_HELP[view] || "";
  draw();
}

/** entry: o que o player está tocando (canal, filme ou episódio), ou nada. */
export function showPlaying(entry, now = Date.now()) {
  if (!entry) playing = "Nada tocando";
  else if (entry.kind === "live") {
    const p = nowProg(entry.epg || [], now);
    playing = `No ar: ${entry.num} ${entry.title}${p ? ` (${p.title}, até ${hhmm(p.stop)})` : ""}`;
  } else playing = `No ar: ${entry.title}`;
  draw();
}
