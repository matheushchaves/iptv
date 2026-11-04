# Vigia do Sofá Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O Sofá fica sempre no ar no Mac, sem Terminal, e o estado dele fica à vista no ícone da barra, numa janelinha e numa página no tablet.

**Architecture:** `vigia.py` (Python puro) é iniciado pelo launchd, roda `server.py` como filho e serve uma página de estado na porta 8010. `Sofá.app` é uma casca fina em Swift que mostra essa página e pinta o ícone da barra. O que depende do sistema operacional fica isolado em `vigia_system.py`, e a decisão de estado fica pura em `vigia_state.py`.

**Tech Stack:** Python 3.9+ só com biblioteca padrão, `unittest`, HTML/JS sem build, Swift com AppKit e WebKit compilado por `swiftc`, launchd.

**Spec:** `docs/superpowers/specs/2026-11-04-vigia-do-sofa-design.md`

## Global Constraints

- Python 3.9 ou mais novo, só biblioteca padrão. Rodar também em `/usr/bin/python3` (3.9.6): nada de `X | None` fora de `from __future__ import annotations`, nada de `match`.
- `python3 server.py` continua funcionando como hoje. A única mudança em `server.py` é a linha de log da lista (Task 2).
- `vigia*.py` nunca importam `server.py`: um erro lá não pode derrubar o vigia.
- Portas: Sofá **8000**, página do vigia **8010**.
- O vigia nunca faz pedidos ao painel Xtream.
- Nenhuma URL, usuário ou senha de lista sai na página ou no JSON.
- `vigia.html` segue o Chrome 79: sem `?.`, `??`, `||=`, `gap` em flex, `inset`.
- Código no estilo do repositório: identificadores em inglês, comentários e mensagens em português, poucos comentários.
- Mensagens de estado exatamente como na tabela do spec.
- Trabalhar no branch `feat/vigia`. Commits no formato `<tipo>: <descrição>` em português, sem linhas de atribuição, como o histórico do repositório. Usar `git add` nos arquivos nomeados: `.codegraph/` fica de fora.

## Review Focus

1. **`server.py` imprime bytes inválidos, ou uma linha enorme:** a leitura da saída não pode morrer. Se morrer, o pipe enche e o Sofá congela no próximo `print`. O mesmo vale para disco cheio ao gravar o log.
2. **Mac sem rede (Wi-Fi desligado, acabou de acordar):** a página diz "Sem rede no Mac", nunca mostra `127.0.0.1` como endereço da TV, e `sofa.local` deixa de ser publicado.
3. **Segundo vigia iniciado com o primeiro rodando:** sai com mensagem clara, sem subir um segundo `server.py`.
4. **Dois Religar ao mesmo tempo (dois aparelhos, duplo clique):** nunca ficam dois filhos vivos.
5. **Projeto movido ou `server.py` apagado depois de instalar:** o vigia não cai. Fica vermelho, com o motivo, e o README diz para rodar o instalador de novo.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `vigia_state.py` | puro: decide cor e mensagem, filtra linhas do log |
| `vigia_system.py` | tudo que conversa com o sistema: acordado, nome, bateria, IP, internet, plists |
| `vigia.py` | `ServerLog`, `Supervisor`, `Vigia`, HTTP e `main` |
| `vigia.html` | a página de estado, um arquivo só |
| `mac/Sofa.swift`, `mac/Info.plist` | a casca do app |
| `instalar-mac.sh`, `desinstalar-mac.sh` | instalação de uma vez |
| `test_vigia_state.py`, `test_vigia_system.py`, `test_vigia.py` | testes em `unittest`, descobertos por `python3 -m unittest -q` |

---

### Task 1: Estados e filtro do log

**Files:**
- Create: `vigia_state.py`, `test_vigia_state.py`

**Interfaces:**
- Produces:
  - `GREEN, YELLOW, RED, GRAY = "green", "yellow", "red", "gray"`
  - `Facts`, dataclass congelada: `stopped=False, own_child=False, responding=False, crashed=False, gave_up=False, reason="", on_battery=False, online=True`
  - `Verdict`, dataclass congelada: `color: str, title: str, detail: str = ""`
  - `decide(facts: Facts) -> Verdict`
  - `cut_urls(text: str) -> str`
  - `public_line(line: str) -> Optional[str]`
  - `failure_reason(lines: Sequence[str], port: int) -> str`

- [ ] **Step 1: Criar o branch e guardar spec e plano**

```bash
git switch -c feat/vigia
git add docs/superpowers/specs/2026-11-04-vigia-do-sofa-design.md docs/superpowers/plans/2026-11-04-vigia-do-sofa.md
git commit -m "docs: desenho e plano do vigia do Sofá"
```

- [ ] **Step 2: Escrever os testes**

```python
class DecideTest(unittest.TestCase):
    def test_each_situation_has_the_spec_message(self):
        cases = [
            (Facts(own_child=True, responding=True), GREEN, "Sofá no ar"),
            (Facts(own_child=True, crashed=True), YELLOW, "Sofá caiu, religando"),
            (Facts(own_child=True), YELLOW, "Sofá ligando"),
            (Facts(own_child=True, responding=True, on_battery=True), YELLOW,
             "Mac na bateria: vai dormir quando ficar parado"),
            (Facts(own_child=True, responding=True, online=False), YELLOW,
             "Sem internet: os canais não vão tocar"),
            (Facts(responding=True), YELLOW, "Sofá aberto pelo Terminal: Religar não funciona"),
            (Facts(gave_up=True), RED, "Sofá não consegue ligar"),
            (Facts(stopped=True), GRAY, "Sofá desligado"),
        ]
        for facts, color, title in cases:
            with self.subTest(title=title):
                verdict = decide(facts)
                self.assertEqual((verdict.color, verdict.title), (color, title))

    def test_red_carries_the_reason(self):
        verdict = decide(Facts(gave_up=True, reason="Outro programa está usando a porta 8000"))
        self.assertEqual(verdict.detail, "Outro programa está usando a porta 8000")

    def test_owner_stop_wins_over_old_crash(self):
        self.assertEqual(decide(Facts(stopped=True, crashed=True, gave_up=True)).color, GRAY)

    def test_terminal_instance_wins_over_stopped(self):
        self.assertEqual(decide(Facts(stopped=True, responding=True)).title,
                         "Sofá aberto pelo Terminal: Religar não funciona")


class PublicLineTest(unittest.TestCase):
    def test_keeps_what_the_owner_should_see(self):
        cases = {
            "19:02:28 player 192.168.0.5: erro de script: x em a.js:1 | Mozilla/5.0": "player 192.168.0.5: erro de script: x em a.js:1",
            "painel ex.com: get_live_streams respondeu 403": "painel ex.com: get_live_streams respondeu 403",
            "12:00:00 lista Didugy: não abriu (403)": "lista Didugy: não abriu (403)",
            "12:00:00 recusado: 8.8.8.8 está fora da rede de casa": "recusado: 8.8.8.8 está fora da rede de casa",
        }
        for line, shown in cases.items():
            self.assertEqual(public_line(line), shown)

    def test_drops_everything_else(self):
        for line in ("Carregando EPG...", "12:00:00 proxy: a/…/b parou no meio (timeout)",
                     "Falha ao carregar EPG http://x/y: boom", "12:00:00 player 192.168.0.5: andou 30 s em 30 s"):
            self.assertIsNone(public_line(line))

    def test_cuts_urls_and_credentials(self):
        self.assertEqual(cut_urls("falhou http://p.com/get.php?username=u&password=s ok"), "falhou [link] ok")
        self.assertNotIn("segredo", cut_urls("username=eu&password=segredo"))
        self.assertNotIn("p.com", public_line("12:00:00 player 1.2.3.4: erro em http://p.com/live/u/s/1.ts"))

    def test_long_line_is_capped(self):
        self.assertLessEqual(len(public_line("player 1.2.3.4: erro " + "x" * 500)), 160)


class FailureReasonTest(unittest.TestCase):
    def test_busy_port_is_explained(self):
        self.assertEqual(failure_reason(["OSError: [Errno 48] Address already in use"], 8000),
                         "Outro programa está usando a porta 8000")

    def test_uses_last_line_without_urls(self):
        self.assertEqual(failure_reason(["boom em http://p.com/x", ""], 8000), "boom em [link]")

    def test_no_output(self):
        self.assertEqual(failure_reason([], 8000), "O Sofá fechou sem dizer o motivo")
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `python3 -m unittest -q test_vigia_state`
Expected: FAIL com `ModuleNotFoundError: No module named 'vigia_state'`

- [ ] **Step 4: Implementar `vigia_state.py`**

Ordem de `decide`: Terminal (`responding and not own_child`), desligado, `gave_up`, não respondendo (`crashed` escolhe entre "caiu" e "ligando"), sem internet, bateria, verde.

`public_line` tira o horário `HH:MM:SS `, aceita os prefixos `lista `, `painel `, `recusado:` e `player `. Linhas `player ` só passam com uma destas palavras: `erro`, `Error`, `caiu`, `travou`. Corta em ` | `, aplica `cut_urls` e limita a 160 caracteres.

`cut_urls` troca `esquema://…` até o próximo espaço por `[link]` e remove `username=…` e `password=…` soltos. `failure_reason` limita a 200 caracteres.

- [ ] **Step 5: Rodar e ver passar**

Run: `python3 -m unittest -q test_vigia_state`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add vigia_state.py test_vigia_state.py
git commit -m "feat: estados e filtro de log do vigia"
```

---

### Task 2: Lista que falha aparece no log

**Files:**
- Modify: `server.py:350-351` (dentro de `load_catalog`)
- Test: `test_server.py`

**Interfaces:**
- Produces: a linha `HH:MM:SS lista <nome>: não abriu (<código ou tipo do erro>)` no `server.log`, que `public_line` da Task 1 já aceita.

- [ ] **Step 1: Escrever o teste em `CatalogApiTest` ou classe nova em `test_server.py`**

```python
class ListFailureLogTest(unittest.TestCase):
    def test_failed_list_is_logged_without_its_url(self):
        url = "http://p.com/get.php?username=eu&password=segredo"
        playlist = {"id": "falha", "name": "Minha", "url": url}
        refused = urllib.error.HTTPError(url, 403, "Forbidden", None, None)
        out = io.StringIO()
        with mock.patch.object(server, "load_playlists", return_value=[playlist]), \
             mock.patch.object(server, "load_epg", return_value=server.EMPTY_GUIDE), \
             mock.patch.object(server, "read_playlist_source", side_effect=refused), \
             redirect_stdout(out):
            with self.assertRaises(urllib.error.HTTPError):
                server.load_catalog("falha")
        self.assertIn("lista Minha: não abriu (403)", out.getvalue())
        self.assertNotIn("segredo", out.getvalue())
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python3 -m unittest -q test_server.ListFailureLogTest`
Expected: FAIL em `assertIn`

- [ ] **Step 3: Implementar**

Em `load_catalog`, separar `read_playlist_source(playlist)` num `try`, registrar com `log(f"lista {playlist['name']}: não abriu ({getattr(exc, 'code', type(exc).__name__)})")` e relançar. Não usar `str(exc)`, que pode trazer a URL.

- [ ] **Step 4: Rodar e ver passar**

Run: `python3 -m unittest -q test_server`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add server.py test_server.py
git commit -m "feat: lista que falha ao baixar aparece no log"
```

---

### Task 3: Conversa com o sistema

**Files:**
- Create: `vigia_system.py`, `test_vigia_system.py`

**Interfaces:**
- Produces:
  - `NAME = "sofa.local"`, `IS_MAC = sys.platform == "darwin"`
  - `lan_ip() -> Optional[str]`: como `lan_ip` de `server.py` (`connect` UDP em `192.0.2.1:80`), mas `None` sem rede
  - `on_battery(run=subprocess.run) -> bool`: lê `pmset -g batt`; `False` fora do Mac ou se o comando falhar
  - `internet_ok(connect=socket.create_connection) -> bool`: tenta `1.1.1.1:443` e `8.8.8.8:443`, timeout 2 s
  - `KeepAwake(popen=subprocess.Popen, enabled=IS_MAC)` com `.set(on: bool) -> None`
  - `NamePublisher(port: int, popen=subprocess.Popen, enabled=IS_MAC)` com `.update(ip: Optional[str]) -> None`, `.stop() -> None` e a propriedade `.name -> Optional[str]`
  - `launch_agent_plist(label: str, args: Sequence[str], root: Path, keep_alive: bool, log_path: Optional[Path] = None) -> bytes`
  - Linha de comando: `python3 vigia_system.py vigia-plist <python>` e `python3 vigia_system.py app-plist <binário>`, que escrevem o plist na saída

- [ ] **Step 1: Escrever os testes**

```python
class FakeProc:
    def __init__(self):
        self.alive = True
    def poll(self):
        return None if self.alive else 0
    def terminate(self):
        self.alive = False
    def wait(self, timeout=None):
        return 0


class Recorder:
    def __init__(self):
        self.calls, self.procs = [], []
    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        self.procs.append(FakeProc())
        return self.procs[-1]


class KeepAwakeTest(unittest.TestCase):
    def test_holds_the_mac_only_while_on(self):
        popen = Recorder()
        awake = KeepAwake(popen=popen, enabled=True)
        awake.set(True)
        awake.set(True)
        self.assertEqual(popen.calls, [["caffeinate", "-s", "-w", str(os.getpid())]])
        awake.set(False)
        self.assertFalse(popen.procs[0].alive)

    def test_comes_back_if_caffeinate_died(self):
        popen = Recorder()
        awake = KeepAwake(popen=popen, enabled=True)
        awake.set(True)
        popen.procs[0].alive = False
        awake.set(True)
        self.assertEqual(len(popen.calls), 2)

    def test_does_nothing_outside_the_mac(self):
        popen = Recorder()
        KeepAwake(popen=popen, enabled=False).set(True)
        self.assertEqual(popen.calls, [])


class NamePublisherTest(unittest.TestCase):
    def test_publishes_and_republishes_when_ip_changes(self):
        popen = Recorder()
        names = NamePublisher(8000, popen=popen, enabled=True)
        names.update("192.168.0.4")
        names.update("192.168.0.4")
        names.update("192.168.0.10")
        self.assertEqual(popen.calls[-1], ["dns-sd", "-P", "Sofa", "_http._tcp", "local", "8000", "sofa.local", "192.168.0.10"])
        self.assertEqual(len(popen.calls), 2)
        self.assertFalse(popen.procs[0].alive)

    def test_no_network_stops_publishing(self):  # Review Focus 2
        popen = Recorder()
        names = NamePublisher(8000, popen=popen, enabled=True)
        names.update("192.168.0.4")
        names.update(None)
        self.assertFalse(popen.procs[0].alive)
        self.assertIsNone(names.name)

    def test_name_is_none_outside_the_mac(self):
        self.assertIsNone(NamePublisher(8000, popen=Recorder(), enabled=False).name)


class BatteryTest(unittest.TestCase):
    def batt(self, text):
        return on_battery(run=lambda *a, **k: mock.Mock(stdout=text, returncode=0))

    def test_reads_power_source(self):
        with mock.patch.object(vigia_system, "IS_MAC", True):
            self.assertTrue(self.batt("Now drawing from 'Battery Power'\n"))
            self.assertFalse(self.batt("Now drawing from 'AC Power'\n"))

    def test_failed_command_counts_as_plugged_in(self):
        def broken(*args, **kwargs):
            raise OSError("sem pmset")
        with mock.patch.object(vigia_system, "IS_MAC", True):
            self.assertFalse(on_battery(run=broken))


class PlistTest(unittest.TestCase):
    def test_vigia_stays_alive_and_runs_in_the_project(self):
        plist = plistlib.loads(launch_agent_plist("local.sofa.vigia", ["/py", "vigia.py"], Path("/a & b"),
                                                  True, Path("/a & b/vigia.log")))
        self.assertEqual(plist["ProgramArguments"], ["/py", "vigia.py"])
        self.assertEqual(plist["WorkingDirectory"], "/a & b")
        self.assertTrue(plist["RunAtLoad"])
        self.assertTrue(plist["KeepAlive"])
        self.assertEqual(plist["ProcessType"], "Interactive")  # Background limitaria o proxy de vídeo
        self.assertEqual(plist["StandardErrorPath"], "/a & b/vigia.log")

    def test_app_does_not_come_back_after_quitting(self):
        plist = plistlib.loads(launch_agent_plist("local.sofa.barra", ["/app", "--barra"], Path("/a"), False))
        self.assertFalse(plist["KeepAlive"])
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python3 -m unittest -q test_vigia_system`
Expected: FAIL com `ModuleNotFoundError: No module named 'vigia_system'`

- [ ] **Step 3: Implementar `vigia_system.py`**

`vigia-plist` monta `[<python>, "vigia.py"]` com a raiz do projeto e `vigia.log`. O caminho do Python vem do argumento: `sys.executable` aponta para a versão exata e sumiria num `brew upgrade`.

- [ ] **Step 4: Rodar e ver passar**

Run: `python3 -m unittest -q test_vigia_system`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add vigia_system.py test_vigia_system.py
git commit -m "feat: camada do vigia que conversa com o macOS"
```

---

### Task 4: O vigia cuida do `server.py`

**Files:**
- Create: `vigia.py`, `test_vigia.py`

**Interfaces:**
- Consumes: `Facts`, `failure_reason`, `public_line` (Task 1)
- Produces:
  - Constantes: `SERVER_PORT = 8000`, `STATUS_PORT = 8010`, `TICK_S = 2`, `PROBE_TIMEOUT_S = 2`, `HUNG_PROBES = 3`, `STARTUP_GRACE_S = 30`, `RESTART_DELAYS = (1, 2, 5, 10, 30)`, `RETRY_AFTER_GIVING_UP_S = 60`, `STABLE_S = 60`, `STOP_GRACE_S = 3`, `MAX_LOG_BYTES = 5 * 1024 * 1024`
  - `probe_server(port: int) -> bool`: `GET /api/version` em `127.0.0.1` devolve 200 com a chave `version`. Outro programa na porta não conta como Sofá.
  - `ServerLog(path: Path, max_bytes=MAX_LOG_BYTES)` com `.write(line: bytes) -> None`. Passando do limite, renomeia para `server.1.log`: esse nome cai no `*.log` do `.gitignore`, e `server.log.1` não cairia.
  - `Supervisor(root, port, *, spawn=None, probe=None, clock=time.monotonic, on_event=None, stop_flag=None, delays=RESTART_DELAYS, retry_s=RETRY_AFTER_GIVING_UP_S, hung_probes=HUNG_PROBES, startup_grace_s=STARTUP_GRACE_S, stable_s=STABLE_S, stop_grace_s=STOP_GRACE_S)`
  - Métodos: `.tick() -> None`, `.restart() -> bool` (`False` se o Sofá foi aberto fora do vigia), `.stop() -> None`, `.start() -> None`, `.shutdown() -> None`, `.facts(on_battery: bool, online: bool) -> Facts`, `.stopped -> bool`, `.external -> bool`
  - `stop_flag` padrão: `root / "cache" / "vigia-desligado"`, um arquivo vazio. `cache/` já está no `.gitignore`.
  - `on_event(text: str)` recebe "Sofá ligou", "Sofá caiu", "Sofá voltou", "Sofá travou, religando", "Sofá desligado" e as linhas de `public_line`.

- [ ] **Step 1: Escrever os testes com relógio e processo falsos**

`FakeChild` tem `poll/terminate/kill/wait` e `stdout = None`. O teste controla `clock` por uma lista, `probe` por um atributo e `spawn` por uma fábrica que guarda os filhos. Nos blocos desta task e da próxima, cada linha é um teste: o nome e, no comentário, o que ele afirma.

```python
class SupervisorTest(unittest.TestCase):
    def test_starts_once_and_goes_green(self):  # um tick sobe, o seguinte vê responder
    def test_restart_waits_the_growing_delays(self):
        # filho morre a cada vez: novo spawn em t+1, t+2, t+5, t+10, t+30
    def test_gives_up_after_all_delays_but_keeps_trying(self):
        # facts.gave_up True depois de len(delays) quedas; novo spawn a cada retry_s
    def test_stable_run_clears_the_failures(self):
        # responde por stable_s: attempts volta a 0 e gave_up a False
    def test_hung_child_is_killed_and_restarted(self):
        # vivo, já respondeu, probe False por hung_probes ticks: terminate e novo spawn
    def test_slow_start_is_not_hung(self):
        # vivo, nunca respondeu, probe False por menos que startup_grace_s: nada acontece
    def test_terminal_instance_is_left_alone(self):
        # probe True sem filho: nenhum spawn, external True, restart() devolve False
    def test_spawns_when_terminal_instance_goes_away(self):
    def test_stop_persists_and_start_clears(self):
        # stop(): filho encerrado, arquivo criado; novo Supervisor com o mesmo root nasce stopped e não sobe filho
    def test_child_ignoring_terminate_is_killed(self):
        # wait levanta TimeoutExpired: kill é chamado
    def test_spawn_error_does_not_kill_the_vigia(self):  # Review Focus 5
        # spawn levanta OSError: tick não propaga, conta como queda, reason = "Não consegui abrir o server.py"
    def test_two_restarts_at_once_leave_one_child(self):  # Review Focus 4
        # duas threads chamam restart(): só um filho com poll() is None no fim
```

Com o `server.py` falso de verdade, em `class RealChildTest`: uma pasta temporária com um `server.py` que lê o arquivo `mode` e obedece, numa porta livre, com `delays=(0.05,)` e `tick()` chamado em laço por `wait_until(cond, timeout=5)`.

```python
class RealChildTest(unittest.TestCase):
    def test_crash_shows_the_error_as_reason(self):       # mode=crash: imprime "boom" e sai
    def test_busy_port_is_reported_in_plain_words(self):  # mode=busy: imprime "Address already in use"
    def test_hang_is_restarted(self):                     # mode=hang: responde uma vez e para
    def test_missing_server_goes_red(self):               # sem server.py na pasta: gave_up, vigia vivo
    def test_invalid_bytes_do_not_stop_the_reader(self):  # Review Focus 1
        # filho escreve b"\xff\xfe\n", uma linha de 1 MB e depois "12:00:00 painel x: respondeu 403";
        # a última chega a on_event e server.log tem as três
    def test_full_disk_does_not_stop_the_reader(self):    # Review Focus 1
        # ServerLog.write levanta OSError: a leitura continua e a próxima linha chega a on_event


class ServerLogTest(unittest.TestCase):
    def test_rotates_past_the_limit(self):
        # max_bytes=10: depois de duas linhas de 8 bytes existem server.log e server.1.log
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python3 -m unittest -q test_vigia`
Expected: FAIL com `ModuleNotFoundError: No module named 'vigia'`

- [ ] **Step 3: Implementar `ServerLog`, `probe_server` e `Supervisor` em `vigia.py`**

O `spawn` padrão é `Popen([sys.executable, "-u", "server.py", str(port)], cwd=root, stdout=PIPE, stderr=STDOUT, env={**os.environ, "PYTHONUTF8": "1"})`.

Uma thread por filho lê `child.stdout` em bytes. Para cada linha: limita a 4096 bytes, grava em `ServerLog` num `try` que engole `OSError`, decodifica com `errors="replace"`, guarda em `deque(maxlen=20)` para `failure_reason` e passa por `public_line`. Ela nunca para antes de o pipe fechar.

`tick` chama `probe` **fora** do lock e faz o resto dentro, para Religar não esperar a sonda. Todas as ações usam o mesmo lock.

- [ ] **Step 4: Rodar e ver passar**

Run: `python3 -m unittest -q test_vigia`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add vigia.py test_vigia.py
git commit -m "feat: vigia sobe, religa e registra o server.py"
```

---

### Task 5: Página de estado

**Files:**
- Modify: `vigia.py`, `test_vigia.py`
- Create: `vigia.html`

**Interfaces:**
- Consumes: `Supervisor` (Task 4), `decide` (Task 1), `KeepAwake`, `NamePublisher`, `lan_ip`, `on_battery`, `internet_ok`, `NAME` (Task 3)
- Produces:
  - `Vigia(supervisor, awake, names, *, ip=lan_ip, battery=on_battery, online=internet_ok, status_port=STATUS_PORT)` com `.step() -> None`, `.status(local: bool) -> dict`, `.run(httpd) -> None`, `.shutdown() -> None`
  - `bind_status(vigia, port) -> ThreadingHTTPServer`: liga a porta em `0.0.0.0`, sem atender ainda
  - `main(argv) -> int`, com `python3 vigia.py [porta do Sofá] [porta da página]`
  - `GET /api/status`:

```json
{"color": "green", "title": "Sofá no ar", "detail": "", "since": 1793830000,
 "address": {"ip": "192.168.0.4", "port": 8000, "name": "sofa.local", "status_port": 8010},
 "checks": [{"label": "Mac", "value": "na tomada", "ok": true},
            {"label": "Serviço", "value": "respondendo", "ok": true},
            {"label": "Internet", "value": "ok", "ok": true}],
 "events": [{"at": 1793830000, "text": "Sofá ligou"}],
 "can_restart": true, "can_start": false, "can_stop": false}
```

  - `POST /api/restart`, `/api/start`, `/api/stop`: `200 {"ok": true}`, ou `{"error": "..."}` com 403 ou 409

- [ ] **Step 1: Escrever os testes**

Com `Supervisor` falso e `ThreadingHTTPServer` em `127.0.0.1:0`, no molde de `CatalogApiTest`:

```python
class StatusApiTest(unittest.TestCase):
    def test_status_has_tv_address_and_message(self):
        # color, title e address.ip == "192.168.0.4", address.port == 8000
    def test_no_network_never_shows_loopback(self):  # Review Focus 2
        # ip=lambda: None: address.ip é None; a página mostra "Sem rede no Mac"
    def test_since_only_moves_when_the_title_changes(self):
    def test_refuses_the_internet(self):
        # mock.patch.object(vigia, "from_home", return_value=False): 403 em GET e POST
    def test_page_opens_while_sofa_is_down(self):
        # GET / devolve vigia.html com title vermelho no status

class ActionsTest(unittest.TestCase):
    def test_restart_works_from_the_tablet(self):
        # mock.patch.object(vigia, "is_loopback", return_value=False): POST /api/restart é 200
    def test_stop_is_refused_from_another_device(self):
        # is_loopback False: POST /api/stop é 403 e supervisor.stop não é chamado
    def test_stop_works_on_the_mac(self):
    def test_stop_button_only_on_the_mac(self):
        # can_stop False com is_loopback False; True no Mac
    def test_restart_on_terminal_instance_is_409(self):
    def test_post_from_another_site_is_refused(self):
        # Origin: http://evil.example, Host: 127.0.0.1:porta: 403
    def test_rebinding_host_is_refused(self):
        # Origin e Host iguais em evil.example: 403
    def test_post_without_origin_is_accepted(self):

class StepTest(unittest.TestCase):
    def test_keeps_mac_awake_only_while_on(self):
        # supervisor.stopped False: awake.set(True); True: awake.set(False)
    def test_ip_change_republishes_and_logs(self):
        # ip muda: names.update(novo) e evento "IP mudou para 192.168.0.10"
    def test_slow_internet_check_does_not_hold_step(self):
        # internet_ok bloqueado num threading.Event: step() volta na hora

class SecondVigiaTest(unittest.TestCase):
    def test_exits_without_starting_a_server(self):  # Review Focus 3
        # socket ouvindo em P; python vigia.py 18999 P: saída 1, "já está rodando" na saída,
        # e nada ouvindo em 18999

class PageTest(unittest.TestCase):
    def test_follows_chrome_79(self):
        # reutiliza test_compat.JS_SYNTAX no vigia.html; sem "gap:" e sem "inset"
    def test_never_writes_html_from_data(self):
        # sem "innerHTML" no vigia.html: linhas do log vêm de qualquer aparelho da casa
    def test_has_the_no_network_message(self):  # Review Focus 2
        # "Sem rede no Mac" no vigia.html
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python3 -m unittest -q test_vigia`
Expected: FAIL nas classes novas

- [ ] **Step 3: Implementar em `vigia.py`**

`from_home` repete a regra de `server.py` (`not ipaddress.ip_address(addr).is_global`), porque o vigia não importa o servidor. `is_loopback(addr)` decide o Desligar.

Para POST, o `Host` precisa ser um IP, `localhost` ou terminar em `.local`, e o `Origin`, se existir, precisa ter o mesmo host do `Host`.

`step` roda `supervisor.tick()`, `awake.set(not stopped)`, `names.update(ip)`, a bateria a cada 30 s e a internet a cada 60 s numa thread própria. `main` faz `bind_status` **antes** de criar o `Supervisor`. Se a porta estiver ocupada, imprime `O vigia já está rodando (porta 8010 ocupada)` e devolve 1. SIGTERM e Ctrl+C chamam `shutdown`, que encerra filho, caffeinate e nome. `vigia.html` é lido a cada pedido.

- [ ] **Step 4: Escrever `vigia.html`**

Atualiza a cada 3 s com `fetch("/api/status")`. Se a resposta falhar, mostra "Vigia fora do ar".

Cores do tema moderno: `--night #17121c`, `--sofa #201927`, `--cushion #2c2335`, `--seam #3a2f45`, `--text #f3ece4`, `--muted #a99cb5`, `--lamp #f5a524`, `--lamp-ink #2a1800`. Estados: verde `#57d68d`, amarelo `#f5a524`, vermelho `#ff6b5e`, cinza `#a99cb5`. Fonte `system-ui`, largura máxima de 420px, sem rolagem lateral a 320px.

Ordem: ponto colorido e título, detalhe, "desde HH:MM"; **Endereço para a TV** com `IP:8000` em destaque e, menor, `No tablet: sofa.local:8000` e `Esta página: sofa.local:8010`; checagens; O que aconteceu; botões. Isso inverte o desenho, em que o nome vinha primeiro: a TV só entende o IP.

Com `address.ip` nulo, o lugar do endereço mostra "Sem rede no Mac".

Abrir o Sofá é um `<a target="_blank">` para `http://<location.hostname>:<address.port>/`. Tudo que vem do JSON entra por `textContent`.

- [ ] **Step 5: Rodar e ver passar**

Run: `python3 -m unittest -q test_vigia test_vigia_state test_vigia_system`
Expected: OK

- [ ] **Step 6: Olhar a página de verdade**

Run: `python3 vigia.py 18000 18010`, abrir `http://localhost:18010` e tirar capturas a 320 e 1440 com Playwright. Depois encerrar com Ctrl+C e conferir que nada ficou ouvindo em 18000.
Expected: verde, nada cortado. Encerrar o filho pelo `kill` mostra amarelo e volta sozinho.

- [ ] **Step 7: Commit**

```bash
git add vigia.py vigia.html test_vigia.py
git commit -m "feat: página de estado do vigia"
```

---

### Task 6: Sofá.app

**Files:**
- Create: `mac/Sofa.swift`, `mac/Info.plist`

**Interfaces:**
- Consumes: `GET http://127.0.0.1:8010/api/status` (só `color` e `title`) e `GET /` (Task 5)
- Produces: um binário que aceita `--barra` (só o ícone) e, sem argumento, também abre a janela.

- [ ] **Step 1: Escrever `mac/Info.plist`**

`CFBundleName` Sofá, `CFBundleIdentifier` `local.sofa.app`, `CFBundleExecutable` `Sofa`, `LSUIElement` true, `NSAppTransportSecurity.NSAllowsLocalNetworking` true.

- [ ] **Step 2: Escrever `mac/Sofa.swift`**

Um arquivo com AppKit e WebKit:

- `NSStatusItem` com o símbolo `sofa.fill`. `contentTintColor` por `color`: `systemGreen`, `systemYellow`, `systemRed`, e sem tinta em `gray`.
- `Timer` de 3 s com `URLSession` no status. Qualquer falha pinta de vermelho, e o `toolTip` vira "Vigia fora do ar". Com resposta, o `toolTip` é o `title`.
- Clique esquerdo alterna um `NSPopover` de 380×560 com `WKWebView`. Clique direito mostra o menu com "Abrir janela" e "Sair".
- A janela é um `NSWindow` com outro `WKWebView` na mesma URL. `applicationShouldHandleReopen` abre a janela. Sem `--barra`, ela abre ao iniciar.
- `WKUIDelegate.createWebViewWith` abre o link com `NSWorkspace.shared.open`. Sem isso, "Abrir o Sofá" não faz nada dentro do `WKWebView`.

- [ ] **Step 3: Compilar**

Run: `swiftc -O -o "$TMPDIR/Sofa" -framework AppKit -framework WebKit mac/Sofa.swift`
Expected: sem erros. Avisos do Swift 6 sobre concorrência são resolvidos com `@MainActor`, e não ignorados.

- [ ] **Step 4: Conferir à mão, com `python3 vigia.py` rodando**

Rodar o binário e conferir: ícone verde; clique abre o painel; "Abrir o Sofá" abre o navegador; encerrar o vigia pinta de vermelho com "Vigia fora do ar"; "Sair" fecha.

- [ ] **Step 5: Commit**

```bash
git add mac/Sofa.swift mac/Info.plist
git commit -m "feat: app do Mac com ícone na barra e janela"
```

---

### Task 7: Instalador e README

**Files:**
- Create: `instalar-mac.sh`, `desinstalar-mac.sh`
- Modify: `README.md`, `test_vigia_system.py`

**Interfaces:**
- Consumes: `python3 vigia_system.py vigia-plist|app-plist` (Task 3), `mac/` (Task 6)
- Produces: `~/Applications/Sofá.app`, `~/Library/LaunchAgents/local.sofa.vigia.plist`, `~/Library/LaunchAgents/local.sofa.barra.plist`

- [ ] **Step 1: Escrever o teste do bloqueio de pastas**

```python
class InstallerGuardTest(unittest.TestCase):
    def test_refuses_protected_folders(self):
        for folder in ("Downloads", "Documents", "Desktop"):
            with self.subTest(folder=folder), tempfile.TemporaryDirectory() as home:
                project = Path(home) / folder / "iptv"
                project.mkdir(parents=True)
                shutil.copy(ROOT / "instalar-mac.sh", project)
                done = subprocess.run(["sh", "instalar-mac.sh"], cwd=project, env={**os.environ, "HOME": home},
                                      capture_output=True, text=True)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn("mova a pasta", done.stdout + done.stderr)
                self.assertFalse((Path(home) / "Library" / "LaunchAgents").exists())
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python3 -m unittest -q test_vigia_system.InstallerGuardTest`
Expected: FAIL, o script não existe

- [ ] **Step 3: Escrever `instalar-mac.sh`**

Com `set -eu`, nesta ordem, parando com mensagem em português a cada problema:

1. Exigir macOS.
2. Recusar `$HOME/Desktop`, `Documents` e `Downloads`, com "mova a pasta" na mensagem.
3. `PY=$(command -v python3)` e exigir 3.9 ou mais novo.
4. Exigir `swiftc`, sugerindo `xcode-select --install`.
5. Montar `~/Applications/Sofá.app` (`Contents/MacOS/Sofa`, `Contents/Info.plist`) e assinar com `codesign -s - --force`.
6. Gerar os dois plists com `"$PY" vigia_system.py ...`.
7. `launchctl bootout "gui/$(id -u)/<label>" || true`, depois `launchctl bootstrap "gui/$(id -u)" <plist>`.
8. Esperar `http://127.0.0.1:8010/api/status` responder e imprimir o título e o endereço da TV.

- [ ] **Step 4: Escrever `desinstalar-mac.sh`**

`bootout` dos dois, remove os plists e o app. Não toca em `playlists.json`, `prefs.json`, `uploads/` nem `cache/`, mas remove `cache/vigia-desligado`.

- [ ] **Step 5: Atualizar o `README.md`**

- Nova seção **Deixar sempre ligado no Mac**, depois de "Instalar e ligar": rodar `sh instalar-mac.sh` uma vez, onde ver o estado, `sh desinstalar-mac.sh`, e que o macOS avisa sobre item em segundo plano.
- Os limites do spec: Mac reiniciado com FileVault, Mac dormindo ou desligado, fora da tomada ou de tampa fechada.
- Moveu a pasta ou trocou de Python: rodar o instalador de novo (Review Focus 5).
- Em "Abrir em cada aparelho": os três passos do endereço da TV, com o **Fixo** antes da reserva. Nomes `.local` não abrem na TV LG testada, e abriram no tablet.
- "Quando algo não funciona" passa a começar pelo ícone e pela página de estado.
- `python3 server.py` segue como o jeito simples, e o único por enquanto em Windows e Linux.
- Na tabela de arquivos: `vigia.py`, `vigia_state.py`, `vigia_system.py`, `vigia.html`, `mac/`. O texto "não tem build" passa a citar a exceção do app do Mac.

- [ ] **Step 6: Rodar e ver passar**

Run: `python3 -m unittest -q test_vigia_system`
Expected: OK

- [ ] **Step 7: Commit**

```bash
git add instalar-mac.sh desinstalar-mac.sh README.md test_vigia_system.py
git commit -m "feat: instalador do vigia no Mac e README"
```

---

### Task 8: Conferir no Mac de verdade

**Files:** nenhum, salvo correções.

- [ ] **Step 1: Rodar todos os testes nos dois Pythons**

Run: `python3 -m unittest -q && /usr/bin/python3 -m unittest -q test_vigia test_vigia_state test_vigia_system`
Expected: OK nos dois

- [ ] **Step 2: Encerrar o servidor aberto à mão e instalar**

Run: `kill $(lsof -tiTCP:8000 -sTCP:LISTEN); sh instalar-mac.sh`
Expected: imprime "Sofá no ar" e o IP. O ícone aparece verde.

- [ ] **Step 3: Provar que ele volta sozinho**

Run: `kill -9 $(lsof -tiTCP:8000 -sTCP:LISTEN)`, depois conferir `curl -s localhost:8010/api/status` até voltar a verde.
Expected: "Sofá caiu" em `events`, verde em poucos segundos, e `pmset -g assertions` mostra o `caffeinate` do vigia.

- [ ] **Step 4: Provar que o Terminal é respeitado**

Run: `curl -s -X POST localhost:8010/api/stop`, depois `python3 server.py` em outra aba, conferir `curl -s localhost:8010/api/status`, encerrar com Ctrl+C, conferir de novo e rodar `curl -s -X POST localhost:8010/api/start`.
Expected: amarelo "Sofá aberto pelo Terminal: Religar não funciona"; depois cinza "Sofá desligado"; depois verde.

- [ ] **Step 5: Conferir encerramento limpo**

Run: `launchctl bootout "gui/$(id -u)/local.sofa.vigia"; lsof -nP -iTCP:8000 -iTCP:8010 -sTCP:LISTEN; pgrep -f "caffeinate -s -w"; launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/local.sofa.vigia.plist`
Expected: nada ouvindo e nenhum `caffeinate` antes do `bootstrap`; depois verde de novo.

- [ ] **Step 6: Pedir o teste do dono**

Na TV, pelo IP. No tablet, `sofa.local:8010`, tocando em Religar. Sem Desligar no tablet. Deixar o Mac parado por 10 minutos e conferir que a TV ainda abre.

- [ ] **Step 7: Commit das correções, se houver**

```bash
git add <arquivos corrigidos>
git commit -m "fix: ajustes do vigia na conferência no Mac"
```
