# Vigia do Sofá: o serviço sempre no ar, e dá para ver que está

## Por que existe

Hoje, para ver TV, o dono do Sofá precisa ir até o escritório, pegar o notebook, abrir o Terminal, entrar na pasta e rodar `python3 server.py`. Quem está na sala não quer levantar. E quando a TV não abre, não dá para saber o motivo sem abrir o Terminal ou o Claude.

Um app para clicar no Mac sozinho não resolveria, porque ainda exigiria ir até o Mac. Um app Flutter no tablet também não: ele dependeria do mesmo servidor ligado. O que resolve é o serviço ficar sempre no ar sem ninguém pedir, e o estado dele ficar à vista.

## Situação do dono

- MacBook Air M4 no escritório, **na tomada e de tampa aberta**.
- macOS configurado para dormir depois de 1 minuto parado, na tomada.
- FileVault ligado e sem login automático.
- Firewall do macOS desligado.
- TV LG (webOS 6, Chrome 79) e tablet na sala.
- O Mac vai junto para a casa alugada (rede 192.168.1.x), onde não há como mexer no roteador.

## Teste feito em 2026-11-04

Com `dns-sd -P "Sofa" _http._tcp local 8000 sofa.local <ip>`:

| Aparelho | Endereço | Resultado |
|---|---|---|
| Mac | `sofa.local:8000` | abriu |
| TV LG | `sofa.local:8000` | **não abriu** (nada no log do servidor) |
| TV LG | `192.168.0.4:8000` | abriu |
| Tablet | `sofa.local:8000` | abriu |

Conclusão: **a TV usa IP**, e `sofa.local` fica para o tablet, onde o nome funcionou. Celular e computador não foram testados com o nome.

## Objetivos

1. O Sofá sobe sozinho quando o dono entra na conta do Mac e volta sozinho se cair.
2. Na tomada, o Mac não dorme enquanto o Sofá estiver ligado. A tela pode apagar.
3. Três formas de ver o estado, com a mesma informação (decisão do dono):
   - ícone na barra do Mac, que muda de cor;
   - janelinha de app, que abre como qualquer app;
   - página no celular ou tablet, de onde também dá para religar.
4. Quando algo dá errado, a mensagem diz o que houve em português claro, sem precisar de Terminal nem de Claude.
5. O endereço que a TV deve usar está sempre visível.
6. Quem baixar o projeto instala seguindo o README (decisão do dono).

## Fora do escopo agora

- **Windows e Linux:** vêm depois (decisão do dono). O desenho não pode impedir esse passo.
- App assinado ou distribuído pronto. Quem quiser usar compila na própria máquina.
- Acordar o Mac dormindo ou desligado à distância.
- Acesso de fora de casa, além do que o Sofá já aceita por VPN.
- Fazer o nome `sofa.local` funcionar na TV.

## O que tornaria isto um fracasso, mesmo funcionando

- Uma falha que fica escondida e só aparece investigando.
- O Sofá passar a depender de pacotes Python instalados à parte.
- `python3 server.py` deixar de funcionar como hoje.
- O vigia cair junto com o Sofá.
- Senha ou link de lista aparecer na página de estado.
- O vigia encher o painel Xtream de pedidos. Essa conta bloqueia depois de cerca de 6 pedidos por minuto na API e aceita uma conexão por vez.

## Como funciona

Uma peça central, o **vigia**, e duas caras para ele: a página e o app do Mac.

```
macOS (login)
  ├─ inicia e mantém vivo ─> vigia.py ─┬─ inicia e religa ─> server.py (porta 8000)
  │                                    ├─ mantém o Mac acordado
  │                                    ├─ publica sofa.local
  │                                    └─ serve a página de estado (porta 8010)
  └─ inicia ───────────────> Sofá.app (ícone + janela, mostra a página do vigia)
```

### vigia.py

Python puro, só biblioteca padrão, na raiz do projeto. Não importa `server.py`, para que um erro lá não derrube o vigia.

- Roda `server.py` como processo filho, com a saída indo para `server.log`, como hoje.
- Religa quando o processo termina, com espera crescente entre as tentativas.
- Confere a saúde com `GET /api/version`. Se o processo está vivo mas parou de responder por algumas checagens seguidas, ele é encerrado e religado.
- Se a porta 8000 já está respondendo e o processo não é filho do vigia, o vigia não encerra nada. Ele avisa, e "Religar" fica indisponível.
- Mantém o Mac acordado enquanto o Sofá está ligado, com `caffeinate -s` amarrado ao processo do vigia. Sem precisar de senha de administrador e sem mudar ajustes do sistema.
- Publica `sofa.local` com `dns-sd -P` e publica de novo quando o IP muda.
- Limita o tamanho de `server.log`, já que agora o serviço fica ligado por semanas.
- O que depende do sistema operacional (acordado, nome na rede, tomada ou bateria) fica isolado em poucas funções. Fora do Mac elas não fazem nada e não dão erro, então `python vigia.py` já roda em Windows e Linux à mão.

### Página de estado

Um único arquivo HTML, servido pelo vigia na porta **8010**, que continua abrindo com o Sofá fora do ar. Mostra o estado com a cor, desde quando, o endereço da TV, as checagens (Mac, Serviço, Internet), "O que aconteceu" e os botões Abrir o Sofá e Religar. Ligar aparece quando o Sofá está desligado. Desligar só aparece no próprio Mac.

- O visual segue o tema moderno do Sofá (fundo ameixa, âmbar de abajur).
- O JavaScript segue as regras do projeto para a TV LG (Chrome 79): nada de `?.`, `??`, `gap` em flex ou `inset`.
- As mesmas informações saem em JSON para o app do Mac.

### Sofá.app

Casca fina em Swift, sem Dock, que mostra a página do vigia:

- ícone colorido na barra do Mac, atualizado pelo JSON do vigia;
- clique no ícone abre o painel com a página;
- abrir o app pelo Launchpad ou Spotlight abre a janela com a página;
- se o vigia não responde, o ícone fica vermelho e diz "Vigia fora do ar".

Sair do app pelo próprio ícone não o traz de volta até o próximo login, e não afeta o Sofá.

### Instalação

`instalar-mac.sh` roda uma vez no Terminal, compila o app com `swiftc`, coloca em `~/Applications` e registra o vigia e o app no login, sempre pelo mecanismo próprio do macOS. `desinstalar-mac.sh` desfaz tudo e não toca nas listas nem nos favoritos.

O instalador avisa e para se o projeto estiver em Mesa, Documentos ou Downloads. Programas iniciados pelo macOS em segundo plano não têm acesso a essas pastas sem permissão, e baixar o ZIP costuma deixar o projeto em Downloads.

## Estados

| Cor | Quando | Mensagem |
|---|---|---|
| Verde | Sofá responde | Sofá no ar |
| Amarelo | Sofá caiu e está voltando | Sofá caiu, religando |
| Amarelo | Sofá responde, mas o Mac está na bateria | Mac na bateria: vai dormir quando ficar parado |
| Amarelo | Sofá responde, mas não há internet | Sem internet: os canais não vão tocar |
| Amarelo | Sofá responde, mas foi aberto fora do vigia | Sofá aberto pelo Terminal: Religar não funciona |
| Vermelho | Não voltou depois das tentativas | Sofá não consegue ligar, com o motivo (porta ocupada, ou a última linha do erro) |
| Cinza | Dono desligou | Sofá desligado, com o botão Ligar |

Desligado fica desligado até alguém ligar de novo, mesmo depois de reiniciar o Mac. Enquanto estiver desligado, o Mac volta a dormir normalmente.

Por isso Desligar só vale no próprio Mac, e o vigia recusa esse pedido vindo de outro aparelho. Desligar do sofá deixaria o Mac dormir em cerca de um minuto, a página pararia de abrir, e ligar de novo exigiria ir ao escritório, que é a viagem que este projeto elimina.

"O que aconteceu" mostra os eventos do próprio vigia (ligou, caiu, religou, IP mudou) e linhas escolhidas do `server.log` por uma lista do que pode aparecer, nunca o log inteiro. Qualquer URL é cortada antes de sair, para nunca expor usuário e senha de lista.

Hoje uma lista que falha ao baixar não escreve nada em `server.log`: `handle_errors` só devolve 502 ao navegador. Sem isso, uma lista vencida ficaria verde e sem nenhum aviso. Este trabalho acrescenta uma linha de log nesse caminho em `server.py`, sem URL, e ela entra na lista do que pode aparecer. É a única mudança prevista em `server.py`.

O vigia não consulta o painel Xtream em nenhuma checagem.

## Segurança

Mesma regra do Sofá: só atende a rede de casa, e pedidos da internet são recusados. Qualquer pessoa no Wi-Fi pode religar ou desligar, como já pode mexer nas listas. Os botões exigem POST e recusam pedidos vindos de outros sites, para que uma página qualquer aberta num navegador da casa não consiga desligar o Sofá.

## Limites que continuam existindo

- **Mac reiniciou:** com FileVault, o Sofá só volta depois que alguém digitar a senha no Mac.
- **Mac dormindo ou desligado:** nada responde. A página não abrir já é o sinal.
- **Fora da tomada ou de tampa fechada:** o Mac dorme.

Os três entram no README.

Religar também zera a pausa que o Sofá faz depois de uma recusa do painel Xtream, porque ela fica só na memória de `server.py` (`blocked_until` em `xtream.py`). Fica assim: subir o servidor não chama o painel, e a espera entre tentativas limita as voltas automáticas.

## Endereço da TV: passos do dono

O código não resolve isto, porque o IP vem do roteador:

1. Em Ajustes do Sistema, no Wi-Fi de casa, deixar **Endereço Wi-Fi privado** como **Fixo**. Hoje o Mac entra na rede com endereço privado, e se ele for rotativo a reserva não segura.
2. No roteador, reservar um IP para o endereço que aparece nesse ajuste.
3. Atualizar o favorito na TV.

Até lá, e na casa alugada, o IP atual aparece no ícone e na página. Do sofá, o tablet abre `sofa.local:8010` e lê o IP que a TV deve usar.

## README

- Nova seção para deixar sempre ligado no Mac, para qualquer pessoa, com instalar, desinstalar e os limites acima.
- "Quando algo não funciona" passa a começar pelo ícone e pela página de estado.
- Os passos do endereço da TV, incluindo o Fixo.
- `python3 server.py` continua documentado como o jeito simples, e o único por enquanto em Windows e Linux.

## Testes

`test_vigia.py`, em `unittest` como os demais: decisão de estado, espera entre tentativas, filtro de "O que aconteceu", corte de URLs, recusa de POST de outros sites, de pedidos da internet e de Desligar vindo de outro aparelho, e o vigia com um `server.py` falso que cai, trava e ocupa a porta. A nova linha de log da lista ganha teste em `test_server.py`.

O app do Mac é verificado à mão: as cores, o painel, a janela e sair do app.

## Decisões minhas, não do dono

- O nome **vigia** e a porta **8010** (a 8001 já é usada em testes locais).
- Manter `sofa.local` mesmo sem funcionar na TV, porque é o jeito de achar o IP do sofá quando ele muda.
- **Cortar "Agora"** (quem está assistindo a quê), que aparecia nos desenhos. O Sofá não guarda essa informação, e obtê-la exigiria mudar `server.py` e a página. Fica para depois.
- **Cortar a checagem "Lista de canais"**, que aparecia no desenho do celular, porque consultaria o painel Xtream. Problemas de lista aparecem em "O que aconteceu".
- Janela e página serem o mesmo HTML, com o app sendo só uma casca.
- Desligar valer até alguém ligar de novo, e só no próprio Mac. Nos desenhos que o dono viu, o celular já não tinha esse botão.
- Mexer em `server.py` para registrar a falha de lista, e não guardar a pausa do painel entre reinícios.

## Fica a cargo de quem construir

- Quantidade de tentativas, tempos das checagens e tamanho do log.
- Lista exata de linhas do log que aparecem em "O que aconteceu".
- Como guardar o estado "desligado".
- Divisão em arquivos, desde que o projeto continue sem dependências e sem passo de build fora do app do Mac.
- Como o app sobe no login, desde que sair pelo ícone funcione como descrito.
