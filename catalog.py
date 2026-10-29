"""Organiza uma playlist M3U em ao vivo, filmes e séries (episódios agrupados por temporada)."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

VOD_EXT = re.compile(r"\.(mp4|m4v|mov|mkv|webm|avi)$", re.I)
# Padrão Xtream: "Elite S01 Elite - S01E01 - Bem-vindos" ou "Elite S08 Episódio 1"
SERIES_NAME = re.compile(r"^(?P<show>.+?)\s+S(?P<season>\d{1,3})(?:\s+(?P<rest>.*))?$")
EPISODE_CODE = re.compile(r"^\s*[-–:]?\s*S\d{1,3}\s*E(?P<num>\d{1,4})\s*[-–:]?\s*", re.I)
TRAILING_YEAR = re.compile(r"\s*(?:\((?P<a>(?:19|20)\d{2})\)|[-–]\s*(?P<b>(?:19|20)\d{2}))\s*$")
SUBTITLED = re.compile(r"\s*[\[(]L[\])]\s*", re.I)  # "[L]" ou "(L)" = legendado
MAX_PAGE = 200
# Ao vivo: marcações que não são o nome do canal. "[Cam 01]" e afins ficam: aí são canais diferentes.
CHANNEL_NOTES = re.compile(r"[\[(](?:not 24/7|geo-blocked|24h)[\])]", re.I)
ALT_VERSION = re.compile(r"\[alt\]", re.I)
QUALITY = re.compile(r"\((?P<res>\d{3,4})[pi]\)|\b(?P<word>FHD|UHD|4K|HD|SD)\b", re.I)
QUALITY_RANK = {"fhd": 0, "hd": 1, "": 1, "sd": 2, "uhd": 3, "4k": 3}
# O hls.js 1.5 não lê H265 dentro de .ts (testado em 29/10/2026): essas versões nunca tocam
HEVC = re.compile(r"h\.?265|hevc", re.I)


@dataclass(frozen=True)
class Catalog:
    live: list[dict]
    movies: list[dict]
    shows: list[dict]
    seasons: dict[str, list[dict]]  # id da série -> temporadas com episódios


def fold(text: str) -> str:
    """Minúsculas sem acento, para a busca casar 'vinganca' com 'Vingança'."""
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def kind_of(url: str) -> str:
    path = urlparse(url).path
    if "/series/" in path:
        return "series"
    if "/movie/" in path or VOD_EXT.search(path):
        return "movie"
    return "live"


def split_title(name: str) -> tuple[str, int | None, bool]:
    """'Die in a Gunfight - 2021 [L]' -> ('Die in a Gunfight', 2021, True)."""
    subtitled = bool(SUBTITLED.search(name))
    clean = SUBTITLED.sub(" ", name).strip()
    m = TRAILING_YEAR.search(clean)
    if not m or m.start() == 0:
        return clean, None, subtitled
    return clean[:m.start()].strip(), int(m["a"] or m["b"]), subtitled


def _public(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k != "key"}


def _movie(index: int, ch: dict) -> dict:
    title, year, subtitled = split_title(ch["name"])
    return {"id": index, "title": title, "year": year, "subtitled": subtitled, "logo": ch["logo"],
            "group": ch["group"], "url": ch["url"], "key": fold(ch["name"])}


def _show_id(group: str, name: str) -> str:
    return hashlib.sha1(f"{group}\0{name}".encode()).hexdigest()[:12]


def _episode_title(label: str, show: str) -> tuple[str, int | None]:
    rest = label[len(show):] if label.lower().startswith(show.lower()) else label
    m = EPISODE_CODE.match(rest)
    if m:
        rest = rest[m.end():]
    return rest.strip(" -–:"), int(m["num"]) if m else None


def _locate_episode(it: dict, previous: tuple | None) -> tuple[tuple[str, str], int, str]:
    """Descobre (série, temporada, rótulo) de um item da categoria de séries."""
    m = SERIES_NAME.match(it["name"])
    if m:
        return (it["group"], " ".join(m["show"].split())), int(m["season"]), m["rest"] or ""
    # Itens só com o título ("Parte 2") vêm logo depois dos outros episódios da mesma série
    if previous and previous[0][0] == it["group"]:
        return previous[0], previous[1], it["name"]
    return (it["group"], " ".join(it["name"].split())), 1, ""


def _group_series(items: list[dict]) -> tuple[list[dict], dict[str, list[dict]]]:
    seasons: dict[tuple[str, str], dict[int, list[dict]]] = {}
    logos: dict[tuple[str, str], Counter] = {}
    previous = None
    for it in items:
        key, season, label = _locate_episode(it, previous)
        previous = (key, season)
        title, num = _episode_title(label, key[1])
        bucket = seasons.setdefault(key, {}).setdefault(season, [])
        num = num or len(bucket) + 1
        bucket.append({"num": num, "title": title or f"Episódio {num}", "url": it["url"]})
        if it["logo"]:
            logos.setdefault(key, Counter())[it["logo"]] += 1

    shows, by_id = [], {}
    for key, by_season in seasons.items():
        sid = _show_id(*key)
        ordered = [{"number": n, "episodes": sorted(eps, key=lambda e: e["num"])}
                   for n, eps in sorted(by_season.items())]
        poster = logos.get(key, Counter()).most_common(1)
        shows.append({"id": sid, "name": key[1], "group": key[0], "logo": poster[0][0] if poster else "",
                      "seasonCount": len(ordered), "episodeCount": sum(len(s["episodes"]) for s in ordered),
                      "key": fold(key[1])})
        by_id[sid] = ordered
    return shows, by_id


def channel_version(name: str) -> tuple[str, str, tuple[int, bool]]:
    """'A&E FHD [Alt]' -> ('A&E', 'FHD Alt', ordem); 'Band (720p) [Not 24/7]' -> ('Band', '720p', ordem)."""
    rest = CHANNEL_NOTES.sub(" ", name)
    alt = bool(ALT_VERSION.search(rest))
    rest = ALT_VERSION.sub(" ", rest)
    m = QUALITY.search(rest)
    if m and m["res"]:
        quality, rank = m[0].strip("()"), 0 if int(m["res"]) >= 1000 else 1 if int(m["res"]) >= 700 else 2
    else:
        quality = m["word"].upper() if m else ""
        rank = QUALITY_RANK[quality.lower()]
    base = " ".join(QUALITY.sub(" ", rest).split()) or name.strip()
    return base, " ".join(filter(None, [quality, "Alt" if alt else ""])), (rank, alt)


def _version_labels(labels: list[str]) -> list[str]:
    """Rótulo vazio vira 'Versão N'; rótulo repetido ganha número ('HD', 'HD 2')."""
    out, seen = [], Counter()
    for i, label in enumerate(labels):
        label = label or f"Versão {i + 1}"
        seen[label] += 1
        out.append(label if seen[label] == 1 else f"{label} {seen[label]}")
    return out


def _live(channels: list[dict], epg_for: Callable[[str], list]) -> list[dict]:
    """Uma linha por canal: as versões (FHD, HD, SD, reserva) ficam juntas, da melhor para a pior."""
    by_key: dict[str, list[tuple]] = {}
    for ch in channels:
        if HEVC.search(f"{ch['name']} {ch['group']}"):
            continue
        base, label, rank = channel_version(ch["name"])
        by_key.setdefault(fold(base), []).append((rank, base, label, ch))
    live = []
    for versions in by_key.values():
        best = sorted(versions, key=lambda v: v[0])  # estável: no empate vale a ordem da lista
        labels = _version_labels([label for _, _, label, _ in best])
        groups = list(dict.fromkeys(ch["group"] for *_, ch in best))
        i = len(live)
        live.append({
            "id": i, "num": i + 1, "name": best[0][1], "group": groups[0], "groups": groups,
            "logo": next((ch["logo"] for *_, ch in best if ch["logo"]), ""),
            "url": best[0][3]["url"],
            "variants": [{"label": label, "url": ch["url"]} for label, (*_, ch) in zip(labels, best)],
            "epg": next((g for g in (epg_for(ch["name"]) for *_, ch in best) if g), []),
        })
    return live


def build_catalog(channels: list[dict], epg_for: Callable[[str], list] = lambda name: []) -> Catalog:
    by_kind: dict[str, list[dict]] = {"live": [], "movie": [], "series": []}
    for ch in channels:
        by_kind[kind_of(ch["url"])].append(ch)
    live = _live(by_kind["live"], epg_for)
    movies = [_movie(i, ch) for i, ch in enumerate(by_kind["movie"])]
    shows, seasons = _group_series(by_kind["series"])
    return Catalog(live, movies, shows, seasons)


def _groups(entries: list[dict]) -> list[dict]:
    """Canal com versões em categorias diferentes conta em cada uma delas."""
    counts = Counter(g for e in entries for g in e.get("groups", [e["group"]]))
    return [{"name": g, "count": n} for g, n in counts.items()]


def summary(cat: Catalog) -> dict:
    return {
        "live": {"count": len(cat.live), "groups": _groups(cat.live)},
        "movie": {"count": len(cat.movies), "groups": _groups(cat.movies)},
        "series": {"count": len(cat.shows), "episodes": sum(s["episodeCount"] for s in cat.shows),
                   "groups": _groups(cat.shows)},
    }


def browse(entries: list[dict], group: str = "", query: str = "", offset: int = 0, limit: int = 60) -> dict:
    words = fold(query).split()
    hits = [e for e in entries if (not group or e["group"] == group) and all(w in e["key"] for w in words)]
    if words:
        phrase = " ".join(words)
        hits.sort(key=lambda e: not e["key"].startswith(phrase))  # estável: mantém a ordem da lista
    offset, limit = max(0, offset), max(1, min(limit, MAX_PAGE))
    return {"total": len(hits), "items": [_public(e) for e in hits[offset:offset + limit]]}


def show_detail(cat: Catalog, show_id: str) -> dict:
    show = next((s for s in cat.shows if s["id"] == show_id), None)
    if show is None:
        raise KeyError("Série não encontrada")
    return {**_public(show), "seasons": cat.seasons[show_id]}
