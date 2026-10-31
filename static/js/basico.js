// Sofá básico: o Sofá para navegador de TV antiga (uma Samsung de 2013 tem Chrome 25), que não roda o completo.
// Script comum em ES5 (sem let/const, =>, crase, Promise, fetch, closest nem forEach de NodeList), e o CSS sem
// flex, grid ou variáveis. O ao vivo vem do /aovivo/: o Mac junta o HLS num .ts contínuo, que essa TV toca (HLS
// ela não toca). Filmes e séries vêm pelo /proxy, como no completo; favoritos e o ponto de cada vídeo são os mesmos.
(function () {
  "use strict";

  var PAGE = 24; // por página: a TV de 2013 engasga desenhando centenas de botões
  var HIDE_MS = 5000; // a barra do player some depois disso sem mexer no controle
  var SLOW_MS = 15000; // ao vivo sem imagem depois disso: avisa que alguns canais não abrem nesta TV
  var SAVE_MS = 15000; // de quanto em quanto tempo guarda o ponto do filme
  var EDGE_S = 30; // perto disso do começo ou do fim não vale retomar
  var SEEK_S = 30;
  var STUCK_S = 20; // ao vivo com a imagem parada esse tempo: reabre o canal (a TV não avisa quando o fluxo acaba)
  var WATCH_MS = 5000;
  var CHECK_S = 30; // um aviso no log de quanto o vídeo andou nesse tempo, para saber se a TV conta o tempo do ao vivo
  var MAX_KEY_REPORTS = 15;
  var VERSION_MS = 60000;
  var KEYS = {
    37: "left", 38: "up", 39: "right", 40: "down",
    8: "back", 27: "back", 461: "back", 10009: "back",
    33: "chUp", 427: "chUp", 68: "chUp", 34: "chDown", 428: "chDown", 65: "chDown"
  };

  var $ = function (id) { return document.getElementById(id); };
  var main = $("main"), video = $("video"), player = $("player");
  var S = {
    playlist: "", playlists: [], summary: null, live: null, favs: [], progress: {},
    items: [], show: null, now: null, playing: false, focus: null, keysSeen: {}, keyReports: 0
  };
  var shown = "", renders = 0, loadedVersion = null, updateReady = false;

  /* ---------- servidor ---------- */

  function getJson(url, done, onFail) {
    var x = new XMLHttpRequest(), token = renders;
    x.open("GET", url);
    x.onreadystatechange = function () {
      if (x.readyState !== 4) return;
      var data = null;
      try { data = JSON.parse(x.responseText); } catch (e) {}
      if (token !== renders && !onFail) return; // a pessoa já foi para outra tela
      if (x.status === 200 && data !== null) done(data);
      else (onFail || fail)((data && data.error) || "o Sofá não respondeu (erro " + x.status + ")");
    };
    x.send();
  }

  function postJson(url, body) {
    var x = new XMLHttpRequest();
    x.open("POST", url);
    x.setRequestHeader("Content-Type", "application/json");
    x.send(JSON.stringify(body));
  }

  function report(msg) { postJson("/api/log", { msg: "básico: " + msg }); }

  function fail(msg) {
    main.innerHTML = '<p class="note">Não deu para carregar: ' + esc(msg) + '.</p>' +
      '<button class="btn" data-act="reload">Tentar de novo</button>';
    focusFirst();
  }

  function qs(params) {
    var out = [];
    for (var k in params) out.push(k + "=" + encodeURIComponent(params[k]));
    return out.join("&");
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function num(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, "."); }

  function b64url(s) {
    return btoa(unescape(encodeURIComponent(s))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  /* ---------- telas ---------- */

  function go(hash) {
    shown = hash;
    if (location.hash !== hash) location.hash = hash;
    route(hash);
  }

  window.addEventListener("hashchange", function () {
    if (location.hash === shown) return;
    shown = location.hash;
    route(shown);
  });

  function route(hash) {
    var parts = hash.replace(/^#/, "").split("/").map(decodeURIComponent), view = parts[0] || "inicio";
    if (view === "ver") {
      if (!S.now) go("#inicio"); // recarregou no player: o que tocava não ficou guardado
      return;
    }
    stop();
    if (updateReady) return location.reload(); // código novo no Mac: entra agora, que nada está tocando
    renders++;
    document.body.className = view === "inicio" ? "home" : "";
    crumb("");
    window.scrollTo(0, 0);
    if (view === "listas") lists();
    else if (view === "aovivo" && parts.length > 1) channels(parts[1], +parts[2] || 0);
    else if (view === "aovivo") liveGroups();
    else if ((view === "filmes" || view === "series") && parts.length > 1) vodPage(view, parts[1], parts[2], +parts[3] || 0);
    else if (view === "filmes" || view === "series") vodGroups(view);
    else if (view === "serie") showPage(parts[1], +parts[2] || 0);
    else home();
  }

  function crumb(text) { $("crumb").textContent = text; }

  function loading(text) { main.innerHTML = '<p class="note">' + esc(text) + '</p>'; }

  function home() {
    var s = S.summary, name = (S.playlists.filter(function (p) { return p.id === S.playlist; })[0] || {}).name;
    main.innerHTML = '<div class="tiles">' +
      tile("#aovivo", "Canais ao vivo", num(s.live.count) + " canais") +
      (s.movie.count ? tile("#filmes", "Filmes", num(s.movie.count) + " filmes") : "") +
      (s.series.count ? tile("#series", "Séries", num(s.series.count) + " séries") : "") +
      tile("#listas", "Trocar de lista", name || "") + '</div>' +
      '<p class="note">Esta TV tem um navegador antigo, então o Sofá abre nesta versão simples. ' +
      'Os canais ao vivo levam alguns segundos para aparecer.</p>';
    focusFirst();
  }

  function tile(href, label, sub) {
    return '<a class="tile" href="' + href + '"><b>' + esc(label) + '</b><span>' + esc(sub) + '</span></a>';
  }

  function group(href, name, count) {
    return '<a class="group" href="' + href + '">' + esc(name) + '<span class="count">' + num(count) + '</span></a>';
  }

  function lists() {
    crumb("Trocar de lista");
    main.innerHTML = '<div class="groups">' + S.playlists.map(function (p) {
      return '<button class="group' + (p.id === S.playlist ? " on" : "") + '" data-act="use" data-id="' + esc(p.id) + '">' +
        esc(p.name) + '</button>';
    }).join("") + '</div>';
    focusFirst();
  }

  function pager(base, page, total) {
    var pages = Math.ceil(total / PAGE);
    if (pages <= 1) return "";
    return '<div class="pager">' +
      (page > 0 ? '<a class="btn" href="' + base + (page - 1) + '">&#9664; Anterior</a>' : "") +
      '<span>Página ' + (page + 1) + ' de ' + pages + '</span>' +
      (page < pages - 1 ? '<a class="btn" href="' + base + (page + 1) + '">Próxima &#9654;</a>' : "") + '</div>';
  }

  /* ---------- ao vivo ---------- */

  function withLive(fn) {
    if (S.live) return fn();
    loading("Carregando os canais...");
    getJson("/api/live?" + qs({ playlist: S.playlist }), function (live) { S.live = live; fn(); });
  }

  function urlsOf(c) {
    return c.variants && c.variants.length ? c.variants.map(function (v) { return v.url; }) : [c.url];
  }

  function isFav(c) {
    return urlsOf(c).some(function (u) { return S.favs.indexOf(u) >= 0; });
  }

  function liveList(key) {
    if (key === "fav") return { name: "Favoritos", items: S.live.filter(isFav) };
    if (key === "todos") return { name: "Todos os canais", items: S.live };
    var g = S.summary.live.groups[+key] || { name: "" };
    return {
      name: g.name,
      items: S.live.filter(function (c) { return (c.groups || [c.group]).indexOf(g.name) >= 0; })
    };
  }

  function liveGroups() {
    crumb("Canais ao vivo");
    withLive(function () {
      var favs = S.live.filter(isFav).length;
      var html = (favs ? group("#aovivo/fav/0", "Favoritos", favs) : "") + group("#aovivo/todos/0", "Todos os canais", S.live.length);
      S.summary.live.groups.forEach(function (g, i) { html += group("#aovivo/" + i + "/0", g.name, g.count); });
      main.innerHTML = '<div class="groups">' + html + '</div>';
      focusFirst();
    });
  }

  function onAir(c, now) {
    var epg = c.epg || [];
    for (var i = 0; i < epg.length; i++) if (epg[i].start <= now && now < epg[i].stop) return epg[i];
    return null;
  }

  function logo(src) {
    return '<span class="logo">' + (src ? '<img src="' + esc(src) + '" alt="" onerror="this.style.visibility=\'hidden\'">' : "") + '</span>';
  }

  function channels(key, page) {
    withLive(function () {
      var list = liveList(key), now = new Date().getTime(), first = page * PAGE;
      crumb(list.name);
      main.innerHTML = '<div class="rows">' + list.items.slice(first, first + PAGE).map(function (c, i) {
        var show = onAir(c, now);
        return '<button class="row" data-act="channel" data-key="' + esc(key) + '" data-i="' + (first + i) + '">' + logo(c.logo) +
          '<span class="line"><span class="num">' + c.num + '</span>' + esc(c.name) + (isFav(c) ? '<i class="fav"></i>' : "") + '</span>' +
          '<span class="sub">' + esc(show ? "Agora: " + show.title : c.group || "") + '</span></button>';
      }).join("") + '</div>' + pager("#aovivo/" + key + "/", page, list.items.length);
      focusFirst();
    });
  }

  function playChannel(list, i, key) {
    var c = list[i];
    if (!c) return;
    var show = onAir(c, new Date().getTime());
    S.focus = { key: key, i: i };
    play({
      kind: "live", title: c.name, sub: "canal " + c.num + (show ? "   Agora: " + show.title : ""),
      urls: urlsOf(c).map(function (u) { return "/aovivo/" + b64url(u) + ".ts"; }), list: list, index: i, key: key, item: c
    });
  }

  function toggleFav() {
    var c = S.now.item, urls = urlsOf(c), on = !isFav(c);
    (on ? [urls[0]] : urls.filter(function (u) { return S.favs.indexOf(u) >= 0; })).forEach(function (u) {
      postJson("/api/prefs", { op: "fav", url: u, on: on });
      S.favs = on ? S.favs.concat([u]) : S.favs.filter(function (f) { return f !== u; });
    });
    setLabel("fav", on ? "Tirar dos favoritos" : "Favoritar");
  }

  /* ---------- filmes e séries ---------- */

  function section(view) { return view === "filmes" ? "movie" : "series"; }

  function vodGroups(view) {
    var kind = section(view), what = view === "filmes" ? "filmes" : "séries";
    crumb(view === "filmes" ? "Filmes" : "Séries");
    var html = group("#" + view + "/todos//0", "Todos os " + what, S.summary[kind].count);
    S.summary[kind].groups.forEach(function (g, i) { html += group("#" + view + "/g/" + i + "/0", g.name, g.count); });
    main.innerHTML = searchForm(view, "") + '<div class="groups">' + html + '</div>';
    focusFirst();
  }

  function searchForm(view, q) {
    return '<form class="search" data-view="' + view + '"><input name="q" value="' + esc(q) + '" placeholder="Buscar ' +
      (view === "filmes" ? "filme" : "série") + ' pelo nome"><button class="btn">Buscar</button></form>';
  }

  function vodPage(view, mode, arg, page) {
    var kind = section(view), params = { playlist: S.playlist, kind: kind, offset: page * PAGE, limit: PAGE }, title;
    if (mode === "g") {
      var g = S.summary[kind].groups[+arg] || { name: "" };
      params.group = title = g.name;
    } else if (mode === "busca") {
      params.q = arg;
      title = "Busca: " + arg;
    } else {
      title = view === "filmes" ? "Todos os filmes" : "Todas as séries";
    }
    crumb(title);
    loading("Carregando...");
    getJson("/api/browse?" + qs(params), function (data) {
      S.items = data.items;
      var base = "#" + view + "/" + mode + "/" + encodeURIComponent(arg || "") + "/";
      main.innerHTML = (mode === "busca" ? searchForm(view, arg) : "") +
        (data.items.length ? "" : '<p class="note">Nada encontrado.</p>') +
        '<div class="posters">' + data.items.map(function (it, i) {
          var name = it.title || it.name, extra = it.year ? " (" + it.year + ")" : it.seasonCount ? " · " + it.seasonCount + " temp." : "";
          return '<button class="poster" data-act="' + (kind === "movie" ? "movie" : "series") + '" data-i="' + i + '">' +
            '<span class="art"' + (it.logo ? ' style="background-image:url(\'' + esc(encodeURI(it.logo).replace(/'/g, "%27")) + '\')"' : "") + '></span>' +
            '<span class="title">' + esc(name) + esc(extra) + '</span></button>';
        }).join("") + '</div>' + pager(base, page, data.total);
      focusFirst();
    });
  }

  function showPage(id, season) {
    crumb("Série");
    loading("Carregando a série...");
    getJson("/api/show?" + qs({ playlist: S.playlist, id: id }), function (show) {
      S.show = show;
      var seasons = show.seasons || [], current = seasons[season] || { episodes: [] };
      crumb(show.name);
      main.innerHTML = '<div class="show"><h1>' + esc(show.name) + '</h1><div class="seasons">' + seasons.map(function (s, i) {
        return '<a class="btn' + (i === season ? " on" : "") + '" href="#serie/' + encodeURIComponent(id) + '/' + i + '">Temporada ' + s.number + '</a>';
      }).join("") + '</div><div class="rows">' + current.episodes.map(function (ep, i) {
        var p = S.progress[ep.url], seen = p && p.d ? Math.round(100 * p.t / p.d) : 0;
        return '<button class="row ep" data-act="episode" data-season="' + season + '" data-i="' + i + '">' +
          '<span class="line"><span class="num">E' + ep.num + '</span>' + esc(ep.title || "Episódio " + ep.num) + '</span>' +
          '<span class="sub">' + (seen >= 95 ? "Visto" : seen > 2 ? "Parou em " + seen + "%" : "") + '</span></button>';
      }).join("") + '</div></div>';
      S.focus = S.focus && S.focus.show === id ? S.focus : null;
      focusFirst();
    });
  }

  function episodeAfter(season, i) {
    var seasons = S.show.seasons, eps = seasons[season].episodes;
    if (i + 1 < eps.length) return { season: season, i: i + 1 };
    return season + 1 < seasons.length && seasons[season + 1].episodes.length ? { season: season + 1, i: 0 } : null;
  }

  function playEpisode(season, i) {
    var show = S.show, s = show.seasons[season], ep = s.episodes[i];
    S.focus = { show: show.id, season: season, i: i };
    play({
      kind: "vod", title: show.name, sub: "T" + s.number + " E" + ep.num + (ep.title ? "  " + ep.title : ""),
      urls: [proxied(ep.url)], url: ep.url, next: episodeAfter(season, i)
    });
  }

  function proxied(url) { return "/proxy?u=" + encodeURIComponent(url); }

  /* ---------- player ---------- */

  function play(now) {
    stop();
    S.now = now;
    now.at = 0;
    shown = "#ver";
    if (location.hash !== "#ver") location.hash = "#ver"; // o Voltar do controle fecha o player
    player.hidden = false;
    document.body.className = "watching";
    $("ptitle").textContent = now.title;
    $("psub").textContent = now.sub || "";
    buttons();
    load(0);
    if (now.kind === "vod") S.saveTimer = setInterval(saveProgress, SAVE_MS);
  }

  function load(n) {
    var now = S.now;
    now.at = n;
    now.asked = new Date().getTime();
    now.lastT = 0;
    now.stuck = 0;
    now.moved = false;
    S.playing = false;
    clearTimeout(S.slowTimer);
    message(now.kind === "live" ? "Abrindo o canal... a imagem leva alguns segundos para aparecer." : "Abrindo...");
    video.src = now.urls[n];
    video.load();
    try {
      var started = video.play();
      if (started && started.then) started.then(null, function () {}); // navegador novo devolve promessa
    } catch (e) {}
    showBar(true);
    S.slowTimer = setTimeout(function () {
      if (!S.playing && S.now === now) message("Está demorando. Alguns canais não abrem nesta TV: se não aparecer, tente outro.", true);
    }, SLOW_MS);
  }

  function stop() {
    if (!S.now) return;
    saveProgress();
    S.now = null;
    S.playing = false;
    clearTimeout(S.slowTimer);
    clearTimeout(S.hideTimer);
    clearInterval(S.saveTimer);
    video.pause();
    video.removeAttribute("src");
    video.load();
    player.hidden = true;
    document.body.className = "";
  }

  function message(text, bad) {
    var el = $("pmsg");
    el.hidden = !text;
    el.className = bad ? "pmsg bad" : "pmsg";
    el.textContent = text;
  }

  function buttons() {
    var now = S.now, list;
    if (now.kind === "live") {
      list = [["prev", "&#9664; Canal anterior"], ["next", "Próximo canal &#9654;"], ["fav", isFav(now.item) ? "Tirar dos favoritos" : "Favoritar"]];
    } else {
      list = [["back30", "&#9664;&#9664; 30 s"], ["pause", "Pausar"], ["fwd30", "30 s &#9654;&#9654;"]];
      if (now.next) list.push(["nextEpisode", "Próximo episódio"]);
    }
    list.push(["retry", "Recarregar"], ["full", "Tela cheia"], ["list", "Voltar à lista"]);
    $("pbtns").innerHTML = list.map(function (b) {
      return '<button class="pbtn" data-act="' + b[0] + '">' + b[1] + '</button>';
    }).join("");
    if (player.className.indexOf("bar-on") >= 0) defaultButton().focus();
  }

  // O OK logo depois de abrir o vídeo: no ao vivo, o próximo canal; no filme, pausar
  function defaultButton() {
    return $("pbtns").querySelector(S.now.kind === "live" ? '[data-act="next"]' : '[data-act="pause"]');
  }

  function setLabel(act, html) {
    var el = $("pbtns").querySelector('[data-act="' + act + '"]');
    if (el) el.innerHTML = html;
  }

  function showBar(stay) {
    var wasOff = player.className.indexOf("bar-on") < 0;
    player.className = "player bar-on";
    if (wasOff && S.now) {
      var active = document.activeElement;
      if (!active || active.className !== "pbtn") defaultButton().focus();
    }
    clearTimeout(S.hideTimer);
    if (!stay && S.playing) S.hideTimer = setTimeout(function () { player.className = "player"; }, HIDE_MS);
  }

  function failed() {
    var now = S.now;
    if (!now) return;
    S.playing = false;
    clearTimeout(S.slowTimer);
    if (now.at + 1 < now.urls.length) return load(now.at + 1); // outra versão do mesmo canal
    if (now.kind === "live" && now.played && !now.retried) { // caiu no meio: uma tentativa sozinho
      now.retried = true;
      return load(now.at);
    }
    report((now.played ? "caiu: " : "não abriu: ") + now.title + " (" + (video.error ? "erro " + video.error.code : "fim do fluxo") + ")");
    message(now.kind === "live" ? "Este canal não abriu nesta TV. Tente outro." :
      "Este vídeo não abriu nesta TV (o formato do arquivo pode não ser compatível).", true);
    showBar(true);
  }

  function zap(step) {
    var now = S.now;
    if (!now || now.kind !== "live") return;
    playChannel(now.list, (now.index + step + now.list.length) % now.list.length, now.key);
  }

  // A imagem parou? Só dá para saber se a TV conta o tempo do ao vivo (moved); se nunca andou, não mexe
  function watch() {
    var now = S.now;
    if (!now || now.kind !== "live" || !S.playing) return;
    var t = video.currentTime;
    if (t > now.lastT) {
      now.moved = now.lastT > 0 || now.moved;
      now.lastT = t;
      now.stuck = 0;
      return;
    }
    if (!now.moved) return;
    now.stuck += WATCH_MS / 1000;
    if (now.stuck < STUCK_S) return;
    report("travou: " + now.title + "; reabrindo");
    now.retried = false;
    load(now.at);
  }

  function seek(delta) {
    if (!video.duration) return;
    video.currentTime = Math.max(0, Math.min(video.duration - 5, video.currentTime + delta));
  }

  function clockTime(s) {
    s = Math.floor(s);
    var h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = s % 60;
    return (h ? h + ":" + (m < 10 ? "0" : "") : "") + m + ":" + (sec < 10 ? "0" : "") + sec;
  }

  function saveProgress() {
    var now = S.now;
    if (!now || now.kind !== "vod" || !video.duration || !video.currentTime) return;
    var p = { t: video.currentTime, d: video.duration };
    S.progress[now.url] = p;
    postJson("/api/prefs", { op: "progress", url: now.url, t: p.t, d: p.d });
  }

  function fullscreen() {
    var el = document.documentElement;
    try {
      if (document.webkitIsFullScreen) document.webkitCancelFullScreen();
      else if (el.webkitRequestFullScreen) el.webkitRequestFullScreen();
      else if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
    } catch (e) {}
  }

  video.addEventListener("playing", function () {
    var now = S.now;
    if (!now) return;
    S.playing = true;
    if (!now.played) {
      report("abriu " + now.title + " em " + Math.round((new Date().getTime() - now.asked) / 1000) + " s");
      var t0 = video.currentTime;
      setTimeout(function () {
        if (S.now === now) report(now.title + ": andou " + Math.round(video.currentTime - t0) + " s em " + CHECK_S + " s");
      }, CHECK_S * 1000);
    }
    now.played = true;
    clearTimeout(S.slowTimer);
    message("");
    setLabel("pause", "Pausar");
    showBar();
  });
  video.addEventListener("pause", function () {
    if (!S.now || S.now.kind !== "vod") return;
    setLabel("pause", "Continuar");
    showBar(true);
  });
  // Só o erro do vídeo da vez: o de um canal que já foi trocado chega atrasado e não conta
  video.addEventListener("error", function () { if (video.error) failed(); });
  video.addEventListener("ended", function () {
    var now = S.now;
    if (!now) return;
    if (now.kind === "live") return failed(); // o servidor fechou: o canal parou de mandar pedaços
    saveProgress();
    if (now.next) playEpisode(now.next.season, now.next.i);
    else history.back();
  });
  video.addEventListener("loadedmetadata", function () {
    var now = S.now, p = now && now.kind === "vod" && S.progress[now.url];
    if (p && p.t > EDGE_S && p.t < video.duration - EDGE_S) {
      video.currentTime = p.t;
      message("Continuando de " + clockTime(p.t));
      setTimeout(function () { if (S.now === now && S.playing) message(""); }, 3000);
    }
  });
  video.addEventListener("timeupdate", function () {
    var now = S.now;
    if (now && now.kind === "vod" && video.duration) $("psub").textContent = (now.sub ? now.sub + "   " : "") +
      clockTime(video.currentTime) + " / " + clockTime(video.duration);
  });

  /* ---------- controle e ponteiro ---------- */

  var ACTIONS = {
    reload: function () { location.reload(); },
    use: function (el) {
      S.playlist = el.getAttribute("data-id");
      try { localStorage.setItem("iptv.playlist", S.playlist); } catch (e) {}
      S.live = null;
      loading("Carregando a lista...");
      loadSummary(function () { go("#inicio"); });
    },
    channel: function (el) {
      var key = el.getAttribute("data-key");
      playChannel(liveList(key).items, +el.getAttribute("data-i"), key);
    },
    movie: function (el) {
      var it = S.items[+el.getAttribute("data-i")];
      S.focus = { i: +el.getAttribute("data-i"), hash: shown };
      play({ kind: "vod", title: it.title, sub: it.year ? String(it.year) : "", urls: [proxied(it.url)], url: it.url });
    },
    series: function (el) { go("#serie/" + encodeURIComponent(S.items[+el.getAttribute("data-i")].id) + "/0"); },
    episode: function (el) { playEpisode(+el.getAttribute("data-season"), +el.getAttribute("data-i")); },
    prev: function () { zap(-1); },
    next: function () { zap(1); },
    fav: toggleFav,
    back30: function () { seek(-SEEK_S); },
    fwd30: function () { seek(SEEK_S); },
    pause: function () { if (video.paused) video.play(); else video.pause(); },
    nextEpisode: function () { saveProgress(); playEpisode(S.now.next.season, S.now.next.i); },
    retry: function () { S.now.retried = false; load(0); },
    full: fullscreen,
    list: function () { history.back(); }
  };

  document.addEventListener("click", function (e) {
    for (var el = e.target; el && el !== document; el = el.parentNode) {
      var act = el.getAttribute && el.getAttribute("data-act");
      if (act && ACTIONS[act]) {
        e.preventDefault();
        return ACTIONS[act](el);
      }
    }
    if (S.now) showBar();
  });

  document.addEventListener("submit", function (e) {
    e.preventDefault();
    var form = e.target, q = form.q.value.replace(/^\s+|\s+$/g, "");
    if (q) go("#" + form.getAttribute("data-view") + "/busca/" + encodeURIComponent(q) + "/0");
  });

  player.addEventListener("mousemove", function () { showBar(); });

  document.addEventListener("keydown", function (e) {
    var key = KEYS[e.keyCode], typing = e.target && e.target.tagName === "INPUT";
    if (!S.keysSeen[e.keyCode] && S.keyReports < MAX_KEY_REPORTS && !typing) { // para conhecer o controle desta TV
      S.keysSeen[e.keyCode] = true;
      S.keyReports++;
      report("tecla " + e.keyCode);
    }
    if (typing && key !== "up" && key !== "down") return;
    if (S.now) {
      if (key === "chUp" || key === "chDown") {
        e.preventDefault();
        return zap(key === "chUp" ? 1 : -1);
      }
      if (player.className.indexOf("bar-on") < 0 && key !== "back") { // barra escondida: a tecla só mostra a barra
        e.preventDefault();
        return showBar();
      }
      showBar();
    }
    if (key === "back") {
      if (document.body.className === "home") return;
      e.preventDefault();
      return history.back();
    }
    if (key && key !== "chUp" && key !== "chDown" && move(key)) e.preventDefault();
  });

  function focusables() {
    var all = (S.now ? $("pbtns") : document.body).querySelectorAll("a[href], button, input"), out = [];
    for (var i = 0; i < all.length; i++) {
      var r = all[i].getBoundingClientRect();
      if (r.width && r.height) out.push(all[i]);
    }
    return out;
  }

  // Seta para um lado: o botão mais perto naquela direção, de preferência na mesma linha ou coluna
  function move(dir) {
    var list = focusables(), cur = document.activeElement;
    if (list.indexOf(cur) < 0) {
      if (list[0]) focusOn(list[0]);
      return !!list[0];
    }
    var a = cur.getBoundingClientRect(), ax = a.left + a.width / 2, ay = a.top + a.height / 2, best = null, bestScore = Infinity;
    for (var i = 0; i < list.length; i++) {
      if (list[i] === cur) continue;
      var r = list[i].getBoundingClientRect(), dx = r.left + r.width / 2 - ax, dy = r.top + r.height / 2 - ay;
      var ahead = dir === "left" ? -dx : dir === "right" ? dx : dir === "up" ? -dy : dy;
      var aside = dir === "left" || dir === "right" ? Math.abs(dy) : Math.abs(dx);
      if (ahead <= 1) continue;
      var score = ahead + aside * 2;
      if (score < bestScore) { bestScore = score; best = list[i]; }
    }
    if (best) focusOn(best);
    return !!best;
  }

  function focusOn(el) {
    el.focus();
    var r = el.getBoundingClientRect();
    if (r.bottom > window.innerHeight - 10) window.scrollBy(0, r.bottom - window.innerHeight + 40);
    else if (r.top < 10) window.scrollBy(0, r.top - 90);
  }

  // Ao voltar de um vídeo, o foco fica no que estava tocando; numa tela nova, no primeiro botão
  function focusFirst() {
    var f = S.focus, el = null;
    if (f) {
      var sel = f.key !== undefined ? '[data-key="' + f.key + '"][data-i="' + f.i + '"]' :
        f.season !== undefined ? '[data-season="' + f.season + '"][data-i="' + f.i + '"]' :
        f.hash === shown ? '.poster[data-i="' + f.i + '"]' : null;
      el = sel && main.querySelector(sel);
    }
    el = el || main.querySelector("a[href], button, input");
    if (el) focusOn(el);
    if (el) window.scrollTo(0, Math.max(0, el.getBoundingClientRect().top + window.pageYOffset - 200));
  }

  /* ---------- começo ---------- */

  function clock() {
    var d = new Date(), m = d.getMinutes();
    $("clock").textContent = d.getHours() + ":" + (m < 10 ? "0" : "") + m;
  }

  // A TV fica o fim de semana com o Sofá aberto: código novo no Mac recarrega a página, mas só com nada tocando
  function checkVersion() {
    getJson("/api/version", function (v) {
      if (!loadedVersion) loadedVersion = v.version;
      else if (v.version !== loadedVersion) {
        updateReady = true;
        if (!S.now) location.reload();
      }
    }, function () {});
  }

  function loadSummary(done) {
    getJson("/api/catalog?" + qs({ playlist: S.playlist }), function (summary) { S.summary = summary; done(); });
  }

  clock();
  setInterval(clock, 20000);
  setInterval(watch, WATCH_MS);
  checkVersion();
  setInterval(checkVersion, VERSION_MS);
  getJson("/api/playlists", function (playlists) {
    var saved = "";
    try { saved = localStorage.getItem("iptv.playlist") || ""; } catch (e) {}
    S.playlists = playlists;
    S.playlist = (playlists.filter(function (p) { return p.id === saved; })[0] || playlists[0] || {}).id;
    if (!S.playlist) return fail("nenhuma lista cadastrada; adicione uma pelo Sofá no computador");
    getJson("/api/prefs", function (p) { S.favs = p.favs || []; S.progress = p.progress || {}; }, function () {});
    loadSummary(function () {
      shown = location.hash;
      route(shown);
    });
  });
})();
