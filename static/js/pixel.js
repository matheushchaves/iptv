// Ícones em pixel art, desenhados aqui como texto: cada letra é uma cor da paleta, "." é transparente.
// Viram SVG com um retângulo por trecho da mesma cor (nítidos em qualquer tamanho, sem imagem para baixar).

const PALETTE = {
  K: "#1b1206", A: "#f5a524", B: "#c97c0c", C: "#ffd27a", // sofá: contorno, encosto, braços, almofadas
  W: "#ffffff", L: "#d4d0c8", G: "#808080", D: "#404040", // cinzas de janela
  T: "#2ec4c4", N: "#0a246a", R: "#d1242f", O: "#f08c00", // tela, azul-marinho, vermelho, laranja
  Y: "#ffd500", U: "#3b8eea", P: "#6e2a8e",                // amarelo, azul de chuva, roxo
};

function svg(rows, label) {
  const h = rows.length, w = rows[0].length;
  let rects = "";
  rows.forEach((row, y) => {
    for (let x = 0; x < w;) {
      const c = row[x];
      let run = 1;
      while (x + run < w && row[x + run] === c) run++;
      if (c !== ".") rects += `<rect x="${x}" y="${y}" width="${run}" height="1" fill="${PALETTE[c]}"/>`;
      x += run;
    }
  });
  const a11y = label ? `role="img" aria-label="${label}"` : `aria-hidden="true"`;
  return `<svg class="px" viewBox="0 0 ${w} ${h}" shape-rendering="crispEdges" ${a11y}>${rects}</svg>`;
}

const ART = {
  sofa: [
    "..KKKKKKKKKKKK..",
    "..KAAAAAAAAAAK..",
    "..KAAAAAAAAAAK..",
    "KKKAAAAAAAAAAKKK",
    "KBBKKKKKKKKKKBBK",
    "KBBKCCCCCCCCKBBK",
    "KBBKCCCCCCCCKBBK",
    "KKKKKKKKKKKKKKKK",
    ".KK..........KK.",
  ],
  tv: [
    ".....K....K.....",
    "......K..K......",
    ".KKKKKKKKKKKKKK.",
    ".KLLLLLLLLLLLLK.",
    ".KLDDDDDDDDDLLK.",
    ".KLDTTTTTTTDLGK.",
    ".KLDTTTTTTTDLLK.",
    ".KLDTTTTTTTDLGK.",
    ".KLDDDDDDDDDLLK.",
    ".KLLLLLLLLLLLLK.",
    ".KKKKKKKKKKKKKK.",
    "...KK......KK...",
  ],
  film: [
    "KKKKKKKKKKKKKKKK",
    "KWKWKWKWKWKWKWKK",
    "KKKKKKKKKKKKKKKK",
    "KDDDDKDDDDKDDDDK",
    "KDTTDKDOODKDTTDK",
    "KDTTDKDOODKDTTDK",
    "KDDDDKDDDDKDDDDK",
    "KKKKKKKKKKKKKKKK",
    "KWKWKWKWKWKWKWKK",
    "KKKKKKKKKKKKKKKK",
  ],
  series: [
    "...KKKKKKKKKKKK.",
    "...KPPPPPPPPPPK.",
    ".KKKKKKKKKKKKPK.",
    ".KNNNNNNNNNNKPK.",
    "KKKKKKKKKKKKKPK.",
    "KTTTTTTTTTTKNKK.",
    "KTTTTWTTTTTKNK..",
    "KTTTTWWTTTTKKK..",
    "KTTTTWWWTTTK....",
    "KTTTTWWTTTTK....",
    "KTTTTWTTTTTK....",
    "KKKKKKKKKKKK....",
  ],
  star: [
    ".......KK.......",
    "......KYYK......",
    "......KYYK......",
    ".....KYYYYK.....",
    "KKKKKKYYYYKKKKKK",
    "KYYYYYYYYYYYYYYK",
    ".KYYYYYYYYYYYYK.",
    "..KYYYYYYYYYYK..",
    "...KYYYYYYYYK...",
    "..KYYYYKKYYYYK..",
    ".KYYYKK..KKYYYK.",
    "KYYKK......KKYYK",
    "KKK..........KKK",
  ],
  rocket: [
    ".....RR.....",
    "....RWWR....",
    "....WWWW....",
    "....WUUW....",
    "....WUUW....",
    "....WWWW....",
    "...RWWWWR...",
    "..RRWWWWRR..",
    "..R.WGGW.R..",
    ".....OO.....",
    "....OYYO....",
    ".....OO.....",
  ],
  chart: [
    "K..........",
    "K.......UU.",
    "K.......UU.",
    "K....UU.UU.",
    "K....UU.UU.",
    "K.UU.UU.UU.",
    "K.UU.UU.UU.",
    "K.UU.UU.UU.",
    "KKKKKKKKKKK",
  ],
  sun: [
    ".....Y.....",
    ".Y...Y...Y.",
    "..Y.....Y..",
    "....YYY....",
    "...YOOOY...",
    "YY.YOOOY.YY",
    "...YOOOY...",
    "....YYY....",
    "..Y.....Y..",
    ".Y...Y...Y.",
    ".....Y.....",
  ],
  moon: [
    "....YYY....",
    "..YYY......",
    ".YYY.......",
    ".YY........",
    "YYY........",
    "YYY........",
    "YYY.......Y",
    ".YYY.....YY",
    ".YYYY..YYY.",
    "..YYYYYYY..",
    "....YYY....",
  ],
  partly: [
    "..Y........",
    "Y.Y.Y......",
    ".YYY.......",
    "YYOYY.GGG..",
    ".YYY.GWWWG.",
    "Y.Y.GWWWWWG",
    "..GGWWWWWWG",
    ".GWWWWWWWWG",
    "GWWWWWWWWWG",
    ".GGGGGGGGG.",
    "...........",
  ],
  cloud: [
    "...........",
    "....GGG....",
    "...GWWWG...",
    "..GWWWWWGG.",
    ".GWWWWWWWWG",
    "GWWWWWWWWWG",
    "GWWWWWWWWWG",
    ".GGGGGGGGG.",
    "...........",
    "...........",
    "...........",
  ],
  rain: [
    "....GGG....",
    "...GWWWG...",
    "..GWWWWWGG.",
    ".GWWWWWWWWG",
    "GWWWWWWWWWG",
    ".GGGGGGGGG.",
    "..U...U...U",
    ".U...U...U.",
    "U...U...U..",
    "...U...U...",
    "..U...U....",
  ],
  storm: [
    "....GGG....",
    "...GDDDG...",
    "..GDDDDDGG.",
    ".GDDDDDDDDG",
    "GDDDDDDDDDG",
    ".GGGGYGGGG.",
    ".....YY....",
    "....YY.....",
    "...YYYYY...",
    ".....YY....",
    "....Y......",
  ],
  fog: [
    "...........",
    "...........",
    "GGGGGGG....",
    "...........",
    "..GGGGGGGGG",
    "...........",
    "GGGGGGGGG..",
    "...........",
    "...GGGGGGGG",
    "...........",
    "...........",
  ],
};

/** Ícone em pixel art; label: texto para leitor de tela (sem label, é só enfeite). */
export const pixel = (name, label = "") => svg(ART[name], label);

// Tema moderno: os mesmos ícones em traço fino (24x24), no lugar da pixel art
const LINES = {
  sofa: "M5 11V8a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v3M3 13a2 2 0 0 1 4 0v2h10v-2a2 2 0 0 1 4 0v4H3zM5 17v2M19 17v2",
  tv: "M3 7h18v11H3zM8 21h8M9 3l3 4 3-4",
  film: "M3 5h18v14H3zM7 5v14M17 5v14M3 9h4M3 15h4M17 9h4M17 15h4",
  series: "M4 8h13v11H4zM7 5h13v11M10 11l4 2.5-4 2.5z",
  star: "M12 3.6l2.6 5.3 5.8.8-4.2 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z",
  rocket: "M12 2.5c2.6 2.2 3.8 5.6 3.4 10.5H8.6C8.2 8.1 9.4 4.7 12 2.5zM12 8a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3zM8.6 13L6 16.5h3M15.4 13l2.6 3.5h-3M10.5 16.5L12 21l1.5-4.5",
  chart: "M4 4v16h16M8 16v-4M12 16V8M16 16v-6",
  sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  moon: "M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z",
  partly: "M8 3v1.5M3.5 8H2M4.8 4.8l1 1M12.2 4.8l-1 1M5.5 10.5A3.5 3.5 0 1 1 11 6.6M9 20h9a3.5 3.5 0 0 0 0-7 5 5 0 0 0-9.6 1.2A3 3 0 0 0 9 20z",
  cloud: "M7 19h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.6A3.3 3.3 0 0 0 7 19z",
  rain: "M7 15h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.6A3.3 3.3 0 0 0 7 15zM8 18l-1 2.5M12 18l-1 2.5M16 18l-1 2.5",
  storm: "M7 15h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.6A3.3 3.3 0 0 0 7 15zM12.5 15l-2 3.5h3l-2 3.5",
  fog: "M4 9h12M6 13h14M4 17h12",
};

/** O ícone do tema da página: pixel art no retrô, traço no moderno. */
export function icon(name, label = "") {
  if (document.documentElement.getAttribute("data-theme") !== "modern") return pixel(name, label);
  const a11y = label ? `role="img" aria-label="${label}"` : `aria-hidden="true"`;
  return `<svg class="ln" viewBox="0 0 24 24" ${a11y}><path d="${LINES[name]}"/></svg>`;
}

// Códigos de tempo da Open-Meteo (WMO) -> ícone e descrição
const WEATHER = [
  [[0], "sun", "céu limpo"], [[1], "partly", "quase limpo"], [[2], "partly", "parcialmente nublado"],
  [[3], "cloud", "nublado"], [[45, 48], "fog", "neblina"], [[51, 53, 55, 56, 57], "rain", "garoa"],
  [[61, 63, 65, 66, 67, 80, 81, 82], "rain", "chuva"], [[71, 73, 75, 77, 85, 86], "cloud", "neve"],
  [[95, 96, 99], "storm", "trovoada"],
];

/** { icon, text } para o código do tempo; à noite o céu limpo vira lua. */
export function weatherLook(code, day = true) {
  const [, icon, text] = WEATHER.find(([codes]) => codes.includes(code)) || [[], "cloud", "tempo instável"];
  return { icon: !day && (icon === "sun" || icon === "partly") ? "moon" : icon, text };
}
