// Dois temas: "retro" (Sofá 98: área de trabalho, janelas, barra de tarefas) e "modern" (a sala com a luz apagada).
// Cada aparelho guarda o seu (a TV pode ficar no retrô e o Mac no moderno). O index.html liga a folha de estilo
// certa antes de desenhar a página, para o outro tema não piscar; aqui é só a troca com a página aberta.
const KEY = "iptv.theme";
const SHEETS = { modern: "themeModern", retro: "themeRetro" };
const watchers = [];

export const theme = () => document.documentElement.getAttribute("data-theme") || "retro";
export const isRetro = () => theme() === "retro";

/** fn(tema): a página troca o que não é só CSS (ícones, textos). */
export const onThemeChange = (fn) => watchers.push(fn);

export function setTheme(name) {
  if (!SHEETS[name] || name === theme()) return;
  document.documentElement.setAttribute("data-theme", name);
  Object.keys(SHEETS).forEach((t) => { document.getElementById(SHEETS[t]).media = t === name ? "all" : "not all"; });
  try { localStorage.setItem(KEY, name); } catch { /* sem armazenamento: vale até recarregar */ }
  watchers.forEach((fn) => fn(name));
}

export const toggleTheme = () => setTheme(isRetro() ? "modern" : "retro");
export const otherThemeLabel = () => (isRetro() ? "Tema moderno" : "Tema retrô");
