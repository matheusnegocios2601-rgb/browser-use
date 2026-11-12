# garfada

> Aponte. Veja o que vai no garfo.

App de iPhone que reconhece comida **ao vivo pela câmera**, diz as **calorias** com base na tabela oficial **TACO**, sugere o **peso pela medida caseira do IBGE** e avalia se é **saudável** com critérios da Anvisa. Roda 100% no aparelho: grátis, ilimitado, sem internet, nenhuma foto salva ou enviada.

## O que ele faz (e o que não faz)

| Faz | Não faz (de propósito) |
|---|---|
| Reconhece ~110 alimentos ao vivo com o classificador da Apple (Vision), no iPhone | Medir peso pela câmera: o iPhone 14 Plus não tem LiDAR, qualquer número seria chute |
| Calorias, proteína, carboidrato, gordura, saturada, fibra e sódio da **TACO 4ª ed.** (597 alimentos) | Inventar valor: pizza, sushi, sanduíche etc. não estão na TACO, então o app avisa e manda buscar |
| Porção pela **medida caseira medida pelo IBGE** (ex.: escumadeira de arroz = 85 g) ou gramas digitados | Adivinhar o preparo (cru/cozido/frito): você confirma, porque muda tudo |
| "Saudável?" com regra explícita: lupa Anvisa (sódio/saturada), fibra (RDC 54/2012), Guia Alimentar | Dar orientação médica |
| Soma o prato inteiro | Mandar dados para servidor |

## Instalar no iPhone (sem Mac, com xtool)

Você precisa de: PC com **Linux** ou **Windows (WSL)**, cabo USB, um **Apple ID grátis**.

1. **Instale o xtool** seguindo o guia oficial: <https://xtool.sh/documentation/xtooldocs/installation-linux>
   - Swift 6.4 para Linux, `usbmuxd`, e o **Xcode 27.1 .xip** baixado em <https://developer.apple.com/download/all/?q=Xcode> (login com Apple ID; só o arquivo é usado, não precisa de Mac).
   - No Windows: WSL + USBIPD para passar o iPhone para o Linux.
2. Configure: `xtool setup` e escolha **Password** (funciona com Apple ID grátis; usa APIs privadas da Apple, então o próprio xtool sugere uma conta separada).
3. Ligue o iPhone no cabo, toque em **Confiar**.
4. Na pasta deste projeto:
   ```bash
   cd garfada
   xtool dev
   ```
   A primeira compilação demora alguns minutos.
5. No iPhone: ative o **Modo Desenvolvedor** (Ajustes > Privacidade e Segurança) se ele pedir, e em **Ajustes > Geral > VPN e Gerenciamento de Dispositivos** confie no seu Apple ID.

**Limite da conta grátis da Apple:** o app instalado assim expira em cerca de 7 dias; é só rodar `xtool dev` de novo. Isso é regra da Apple, não do app. Com o Apple Developer Program (pago) dura 1 ano.

## Estrutura

```
Sources/GarfadaCore/   lógica pura: TACO, IBGE, porção, avaliação de saúde (testada)
Sources/Garfada/       app iOS: SwiftUI, câmera (AVFoundation), Vision
Tests/                 testes da lógica (rodam no Linux: swift test)
Resources/             Info.plist e ícone
Design/logo.svg        logo vetorial
tools/                 scripts que geram os JSONs a partir das fontes
```

Testes da lógica (Linux/Docker): `docker run --rm -v "$PWD":/src -w /src swift:6.1 swift test`

## Fontes dos dados

- **TACO**: Tabela Brasileira de Composição de Alimentos, 4ª ed. revisada e ampliada, NEPA/UNICAMP, 2011. "É permitida a reprodução total ou parcial do material, desde que seja citada a fonte."
- **IBGE**: Pesquisa de Orçamentos Familiares 2008-2009, *Tabela de Medidas Referidas para os Alimentos Consumidos no Brasil* (2011).
- Processamento e conferência célula a célula: [brolesi/taco](https://github.com/brolesi/taco) e [taco-br-mcp](https://github.com/ianhudsonai/taco-br-mcp) (MIT). O mapeamento TACO↔IBGE é desse projeto.
- Rótulos de reconhecimento: identificadores do `VNClassifyImageRequest` da Apple (revisão 1, 1303 rótulos). O mapeamento rótulo→TACO está em `tools/build_data.py`.

Isto não é orientação médica nem nutricional.
