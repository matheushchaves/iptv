"""Favoritos, ponto dos vídeos e "continuar assistindo", guardados no servidor: a TV e o Mac veem os mesmos.

O navegador manda operações pequenas ("favoritou X") em vez da lista inteira, para um aparelho não apagar
o que o outro acabou de salvar.
"""
import json
import math
import threading
import time
from pathlib import Path

MAX_FAVS = 2000
MAX_PROGRESS = 400
MAX_RECENT = 30
MAX_SAVED = 500
MAX_URL = 4096
MAX_ITEM = 4000  # um item do "continuar assistindo", em JSON
RECENT_KINDS = ("movie", "series")
MAX_PLAYLIST_ID = 100


def empty():
    return {"favs": [], "progress": {}, "recent": [], "saved": []}


def recent_key(item):
    """Um item por filme e um por série (o episódio da vez)."""
    return item.get("showId") or item.get("url")


def saved_key(entry):
    """'Minha lista': o filme pelo link, a série pelo id; a lista entra na chave (cada uma tem seus ids)."""
    item = entry["item"]
    return f"{entry['playlist']}|{item.get('url') if entry['section'] == 'movie' else item.get('id')}"


def url_arg(value):
    if not isinstance(value, str) or not value or len(value) > MAX_URL:
        raise ValueError("Link inválido")
    return value


def seconds_arg(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("Tempo inválido")
    return value


def item_arg(value):
    if not isinstance(value, dict) or value.get("kind") not in RECENT_KINDS:
        raise ValueError("Item inválido")
    url_arg(recent_key(value))
    if len(json.dumps(value)) > MAX_ITEM:
        raise ValueError("Item grande demais")
    return value


def saved_arg(value):
    if not isinstance(value, dict) or value.get("section") not in RECENT_KINDS or not isinstance(value.get("item"), dict):
        raise ValueError("Item inválido")
    playlist = value.get("playlist")
    if not isinstance(playlist, str) or not playlist or len(playlist) > MAX_PLAYLIST_ID:
        raise ValueError("Lista inválida")
    item = value["item"]
    url_arg(item.get("url") if value["section"] == "movie" else item.get("id"))
    if len(json.dumps(item)) > MAX_ITEM:
        raise ValueError("Item grande demais")
    return {"playlist": playlist, "section": value["section"], "item": item}


def progress_arg(value):
    if not isinstance(value, dict):
        raise ValueError("Tempo inválido")
    return {"t": seconds_arg(value.get("t")), "d": seconds_arg(value.get("d")), "at": seconds_arg(value.get("at"))}


def set_fav(data, url, on):
    favs = [u for u in data["favs"] if u != url]
    return {**data, "favs": [*favs, url][-MAX_FAVS:] if on else favs}


def newest_progress(progress):
    return dict(sorted(progress.items(), key=lambda kv: kv[1]["at"], reverse=True)[:MAX_PROGRESS])


def save_progress(data, url, t, d, at):
    return {**data, "progress": newest_progress({**data["progress"], url: {"t": t, "d": d, "at": at}})}


def newest_recent(items):
    seen, out = set(), []
    for item in sorted(items, key=lambda r: r.get("at", 0), reverse=True):
        if recent_key(item) not in seen:
            seen.add(recent_key(item))
            out.append(item)
    return out[:MAX_RECENT]


def touch_recent(data, item, at):
    return {**data, "recent": newest_recent([{**item, "at": at}, *data["recent"]])}


def forget_recent(data, key):
    return {**data, "recent": [r for r in data["recent"] if recent_key(r) != key]}


def save_entry(data, entry, at):
    others = [s for s in data["saved"] if saved_key(s) != saved_key(entry)]
    return {**data, "saved": [{**entry, "at": at}, *others][:MAX_SAVED]}


def unsave_entry(data, key):
    return {**data, "saved": [s for s in data["saved"] if saved_key(s) != key]}


def valid(check, value):
    try:
        check(value)
        return True
    except ValueError:
        return False


def clean(raw):
    """O que um navegador tinha guardado só para ele: o que não tem o formato esperado fica de fora."""
    raw = raw if isinstance(raw, dict) else {}
    favs, progress, recent = raw.get("favs"), raw.get("progress"), raw.get("recent")
    return {
        "favs": [u for u in favs if valid(url_arg, u)] if isinstance(favs, list) else [],
        "progress": {u: progress_arg(p) for u, p in progress.items() if valid(url_arg, u) and valid(progress_arg, p)}
        if isinstance(progress, dict) else {},
        "recent": [r for r in recent if valid(item_arg, r) and valid(seconds_arg, r.get("at", 0))]
        if isinstance(recent, list) else [],
    }


def merge(data, other):
    """Nada some na junção, e entre duas versões do mesmo vídeo vence a mais recente."""
    favs = [*data["favs"], *(u for u in other["favs"] if u not in data["favs"])][-MAX_FAVS:]
    mine = data["progress"]
    newer = {u: p for u, p in other["progress"].items() if u not in mine or p["at"] > mine[u]["at"]}
    progress = {**mine, **newer}
    return {**data, "favs": favs, "progress": newest_progress(progress),
            "recent": newest_recent([*data["recent"], *other["recent"]])}


def apply_op(data, op, at):
    """Aplica uma operação do navegador. at: agora, em ms (o relógio do servidor vale para os dois aparelhos)."""
    kind = op.get("op") if isinstance(op, dict) else None
    if kind == "fav":
        return set_fav(data, url_arg(op.get("url")), bool(op.get("on")))
    if kind == "progress":
        return save_progress(data, url_arg(op.get("url")), seconds_arg(op.get("t")), seconds_arg(op.get("d")), at)
    if kind == "touch":
        return touch_recent(data, item_arg(op.get("item")), at)
    if kind == "forget":
        return forget_recent(data, url_arg(op.get("key")))
    if kind == "save":
        return save_entry(data, saved_arg(op.get("entry")), at)
    if kind == "unsave":
        return unsave_entry(data, url_arg(op.get("key")))
    if kind == "import":
        return merge(data, clean(op.get("data")))
    raise ValueError("Operação desconhecida")


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def read(self):
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return empty()
        except (OSError, ValueError) as exc:
            # Guarda o arquivo estragado ao lado em vez de gravar por cima: dá para recuperar à mão
            print(f"{self.path.name} ilegível ({exc}); guardado como .bad e começando vazio", flush=True)
            self.path.replace(self.path.with_suffix(".json.bad"))
            return empty()
        return {**empty(), **{k: data[k] for k in empty() if k in data}}

    def apply(self, op):
        with self.lock:
            data = apply_op(self.read(), op, at=int(time.time() * 1000))
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False))
            tmp.replace(self.path)
            return data
