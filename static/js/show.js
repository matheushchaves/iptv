// Página da série: temporadas, episódios e onde parou.
import { esc, meter, plural, poster, prettyGroup, remaining, STAR } from "./util.js";
import { progress, isWatched } from "./store.js";

/** Onde está o episódio e qual vem depois (pulando para a próxima temporada no fim). */
export function locate(show, url) {
  for (const [si, season] of show.seasons.entries()) {
    const i = season.episodes.findIndex((e) => e.url === url);
    if (i < 0) continue;
    const following = season.episodes[i + 1]
      ? { season: season.number, episode: season.episodes[i + 1] }
      : show.seasons[si + 1] && { season: show.seasons[si + 1].number, episode: show.seasons[si + 1].episodes[0] };
    return { season: season.number, episode: season.episodes[i], next: following || null };
  }
  return null;
}

function episodeState(url) {
  const p = progress.get(url);
  if (isWatched(p)) return "Visto";
  return p && p.d ? remaining(p.t, p.d) : "";
}

export function episodeList(season, currentUrl) {
  return `<ol class="episodes">${season.episodes.map((e) => `<li>
    <button type="button" class="ep" data-ep="${esc(e.url)}" aria-current="${e.url === currentUrl}">
      <span class="ep-num">${e.num}</span>
      <span class="ep-title">${esc(e.title)}</span>
      <span class="ep-state">${esc(episodeState(e.url))}</span>
      ${isWatched(progress.get(e.url)) ? "" : meter(progress.ratio(e.url))}
    </button></li>`).join("")}</ol>`;
}

function startButton(show, resume) {
  if (resume) {
    return `<button type="button" class="btn primary" data-ep="${esc(resume.url)}">
      Continuar: temporada ${resume.season}, episódio ${resume.num}</button>`;
  }
  const first = show.seasons.length ? show.seasons[0].episodes[0] : null;
  return first ? `<button type="button" class="btn primary" data-ep="${esc(first.url)}">Assistir do começo</button>` : "";
}

export const saveShowHtml = (saved) => `<button type="button" class="btn save-btn" data-action="save-show" aria-pressed="${saved}">
  ${STAR}${saved ? "Na minha lista" : "Guardar na minha lista"}</button>`;

export function showHtml(show, { season, currentUrl, resume, saved }) {
  const current = show.seasons.find((s) => s.number === season) || show.seasons[0];
  const meta = show.seasonCount > 1
    ? `${plural(show.seasonCount, "temporada", "temporadas")}, ${plural(show.episodeCount, "episódio", "episódios")}`
    : plural(show.episodeCount, "episódio", "episódios");
  const tabs = show.seasons.length > 1
    ? `<nav class="seasons" aria-label="Temporadas">${show.seasons.map((s) =>
      `<button type="button" data-season="${s.number}" aria-current="${s.number === current.number}">Temporada ${s.number}</button>`).join("")}</nav>`
    : "";
  return `<article class="show">
    <header class="show-hero">
      ${poster(show.logo, show.name)}
      <div class="show-info">
        <a class="crumb" href="#series?g=${encodeURIComponent(show.group)}">${esc(prettyGroup(show.group))}</a>
        <h1>${esc(show.name)}</h1>
        <p class="show-meta">${meta}</p>
        <div class="show-actions">${startButton(show, resume)}${saveShowHtml(saved)}</div>
      </div>
    </header>
    ${tabs}
    ${current ? episodeList(current, currentUrl) : ""}
  </article>`;
}
