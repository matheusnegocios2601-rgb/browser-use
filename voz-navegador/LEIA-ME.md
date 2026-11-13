# Navegador por Voz

Fale em português, de qualquer programa do Windows, e o destino abre no seu navegador padrão, no perfil que você já usa.

## Começar

1. Coloque esta pasta onde quiser (por exemplo `Documentos\voz-navegador`).
2. Dê dois cliques em **`Iniciar Navegador por Voz.bat`**.
   - Na primeira vez ele instala o Python e as bibliotecas **dentro desta pasta** e cria o atalho **Navegador por Voz** na Área de Trabalho. Precisa de internet e leva alguns minutos.
   - Ao abrir, o app baixa o modelo de voz (`small`, ~463 MB, de `huggingface.co/Systran/faster-whisper-small`) e mostra o andamento. Depois disso o reconhecimento funciona sem internet.
3. Quando a barrinha na parte de baixo da tela mostrar **● Ouvindo** (verde), diga: **"abre o YouTube"**.

Das próximas vezes, use o atalho da Área de Trabalho.

## O que dizer

| Você diz | Acontece |
|---|---|
| "YouTube" · "vai pro YouTube aí" | Abre o YouTube |
| "YouTube Music" · "abre o YouTube… Music" | Abre só o YouTube Music |
| "procura análise do Galaxy S no YouTube" | Busca dentro do YouTube |
| "pesquisa por que o YouTube trava no Chrome" | Pesquisa a pergunta inteira no buscador geral |
| "abre github ponto com barra settings" | Abre `https://github.com/settings` |
| "meu painel" | Abre o atalho que você salvou com esse nome |
| "abre meu banco" (dois atalhos possíveis) | Mostra os dois; responda "o primeiro", "o segundo" ou "cancelar" |
| "abre o site da Loja Exemplo" (desconhecido) | Pesquisa o nome, sem inventar domínio |
| "cancelar" | Descarta a pergunta pendente |
| "pausar escuta" | Para de ouvir e libera o microfone |

## Cadastrar o primeiro atalho

Por voz:

1. Diga **"criar atalho painel de vendas"**.
2. Dite o endereço ("app ponto minhaempresa ponto com barra vendas") **ou cole** no campo "Digitar um comando ou colar um endereço" e aperte Enter.
3. Confira o nome e o endereço no quadro que aparece. Dá para corrigir digitando, ou dizendo "corrigir nome …" / "endereço errado".
4. Diga **"salvar"**.
5. Diga **"abre meu painel de vendas"**. Continua valendo depois de fechar e reabrir o app.

Pela janela: aba **Atalhos**. Cada atalho tem nome, endereço completo, outras formas de falar e uma descrição. A descrição permite pedidos como "aquela página que eu salvei pra acompanhar vendas".

Se o app não entender um nome e você corrigir do mesmo jeito duas vezes, ele oferece guardar aquela pronúncia como apelido. Só guarda se você disser "sim".

## Pausar e retomar

- Diga **"pausar escuta"** ou clique em **Pausar**. A barrinha fica cinza (**Pausado**) e o microfone é liberado.
- Clique em **Ouvir** para voltar.

## Dois modos

- **Mãos livres** (padrão): fica ouvindo; cada frase termina com ~0,5 s de silêncio.
- **Pressionar para falar**: segure a tecla (padrão: **Ctrl direito**), fale, solte. Soltar conclui o pedido na hora. Funciona com outro programa em primeiro plano. Para trocar a tecla: aba Início → botão "Tecla: … (trocar)".

Estados na barrinha: **Pausado** (cinza) · **Ouvindo** (verde) · **Pronto** (azul, aguardando a tecla) · **Interpretando** (amarelo) · **Aguardando escolha** (roxo) · **Problema no microfone** (vermelho, com a causa e o que fazer).

## Avisos honestos

- **Mãos livres ouve tudo.** Um vídeo tocando nas caixas de som pode ser entendido como comando. Com som ambiente, use fone de ouvido ou o modo pressionar para falar.
- **"YouTube" sozinho demora ~0,4 s a mais de propósito**: o app espera para ver se vem "Music". Ajuste em Opções → "Tolerância extra a pausa". No modo pressionar para falar essa espera não existe.
- O detector de fala é por volume. Em ambiente barulhento ele pode não perceber o fim da frase; nesse caso prefira pressionar para falar.

## Privacidade

- O áudio fica só na memória e é descartado depois de cada frase. Nenhuma transcrição é guardada.
- Reconhecimento e interpretação rodam no seu PC, sem conta.
- **Diagnóstico** (Opções) vem desligado. Ligado, grava em `%APPDATA%\VozNavegador\diagnostico.jsonl` a frase reconhecida, a decisão e o destino (nunca áudio). Há um botão para apagar.
- O app abre URLs pelo mecanismo padrão do Windows. Não usa depuração remota, não lê cookies nem senhas. Só abre `http://` e `https://`.
- Seus atalhos e preferências ficam em `%APPDATA%\VozNavegador\dados.json`.

## Jev (TypeSafe AI)

Está integrado como **opcional e desligado**. O Jev é um classificador em nuvem que responde em 70–500 ms; as regras locais deste app decidem em ~2 ms. Por isso ele **não acelera** os comandos comuns e não é chamado neles. Ele só entra quando o app ficaria em dúvida entre atalhos (em vez de perguntar "qual dos dois?"). Para usar: Opções → marque "Usar o Jev" e cole a chave da API (o acesso é por lista de espera em typesafe.ai). Ligado, ele recebe a frase dita e o nome/descrição/domínio dos atalhos em dúvida.

Não foi possível testar contra o serviço real (sem chave); foi testado contra um servidor local que imita o formato documentado da API.

## Medições

Veja `MEDICOES.md` para os números obtidos e como foram medidos. Para medir no **seu** PC, com a **sua** voz: aba **Medições → Calibração guiada** (8 frases, ~1 minuto, não abre nada).

## Para mexer no projeto

```
voznav/texto.py      normalização (chave para comando x texto original para conteúdo)
voznav/pedido.py     frase -> pedido (abrir, buscar, controle)
voznav/urls.py       endereço ditado, validação, montagem de busca
voznav/dados.py      atalhos, serviços e preferências (JSON local)
voznav/sessao.py     decisão: abrir, perguntar, repetir; diálogos pendentes
voznav/fala.py       reconhecimento local (faster-whisper)
voznav/captura.py    microfone e erros
voznav/motor.py      áudio -> fala -> transcrição -> decisão -> navegador; uma abertura por fala
voznav/jev.py        desempate opcional na nuvem
voznav/interface.py  janela e barrinha
tests/               testes de texto, do motor e do Jev
ferramentas/bancada_audio.py   teste com áudio sintetizado em tempo real
```

Testes: `.venv\Scripts\python -m pip install pytest` e depois `.venv\Scripts\python -m pytest`.
Testar uma frase sem microfone: `.venv\Scripts\python -m voznav --texto "procura C++ no YouTube"`.
Se o app não abrir, veja o arquivo `erro.log` nesta pasta.
