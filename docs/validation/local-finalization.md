# Finalização local — editor de produtos e campos relacionais

> Registro da rodada local que originou o pacote aprovado funcionalmente com
> ressalvas. Os resultados e limites abaixo são históricos dessa fonte.
> A rodada posterior, com autorização de publicação para CI e de exceções
> pontuais de scanner, é acompanhada em [Encerramento das ressalvas](reservation-closure.md).

## Escopo e limite

Verificações locais da revisão posterior ao commit `d805ae54`, sem commit,
push, merge ou deploy. Os resultados abaixo não comprovam entrada em produção,
login real, aceite regulatório nem impressão física. As evidências detalhadas
estão no diretório local de artefatos `product-editor-simplification` do agente;
não incorporar fixtures, credenciais, bancos ou capturas privadas à publicação.

## Dependências e verificações concluídas

- `certifi==2026.10.19` e `Pillow==13.0.0` fixados em `requirements.in` e
  `requirements.txt`, protegidos pelo contrato de CI.
- Auditoria estrita das dependências locais: zero vulnerabilidades conhecidas
  no relatório `final-pip-audit-fixed.json`. O relatório anterior com oito
  vulnerabilidades do Pillow permanece separado.
- Compatibilidade de avatar/editor/contrato de CI: 53 testes aprovados.
- Ruff, formatação, Mypy global, Bandit, 18 testes JavaScript e higiene do diff
  aprovados nas execuções registradas. Novos arquivos posteriores exigem sua
  própria verificação; isto não declara CI remoto aprovado.
- Django `check` sem problemas e geração/validação de OpenAPI aprovada.
  A primeira tentativa de OpenAPI excedeu 120 segundos; a execução diagnóstica
  posterior concluiu, sem apagar o timeout anterior.
- `makemigrations --check --dry-run` sem alterações. Uma primeira sondagem
  apontava um banco-base sintético inexistente; o histórico foi conferido
  novamente no banco de testes efetivo, com sessão somente leitura e sem
  avisos. Não houve migração do banco operacional.

## Suíte global e cobertura

A execução `final-complete2` concluiu com **3.148 testes aprovados, quatro
skips e 42 subtestes aprovados**, sem falhas ou erros, em 4.345,63 segundos.
A cobertura foi **86,82%**, acima do mínimo preservado de 80%. Os números
foram reconciliados entre log, JUnit e JSON/XML de cobertura, com hashes dos
artefatos registrados em `final-complete2-parent-verification-*`.

O cenário de concorrência de alocações opostas passou nesta execução. Isso
não apaga o timeout histórico nem demonstra a causa daquela falha anterior.

Os quatro skips exigiam Linux e `SHELL_TEST_IMAGE`. Foram exercitados depois
na imagem local por identidade imutável, sem rede e com entrypoint Bash:
`tests/test_backup_scheduler_script.py` terminou com **cinco testes aprovados,
sem skips**, cobrindo todos os quatro cenários antes ignorados. O quinto
teste também pertence à suíte global: não somar os resultados sobrepostos.
São testes do agendador com comandos de backup sintéticos, não backups ou
restores operacionais.

Limite de fonte: a suíte começou após os upgrades e a correção de tipagem,
antes da rodada corretiva posterior de CSS e seus testes dedicados. Essa
rodada precisa de regressão própria; não se atribui à execução anterior um
snapshot idêntico ao CSS futuro nem aprovação de CI remoto.

## Build local

A imagem `rgnfarmasystem:local-final-20261021` foi construída com contexto
sanitizado, sem arquivos operacionais de ambiente, estado privado do agente ou
mídia. O teste da imagem por identidade imutável, com rede desativada,
filesystem somente leitura e entrypoint substituído por Python, confirmou:

- Python 3.14, Django 6 e as duas versões corrigidas das dependências;
- correspondência de doze arquivos relevantes por SHA-256 com a fonte local;
- codificação/decodificação PNG com Pillow;
- ausência dos caminhos privados explicitamente verificados.

Isto não iniciou a aplicação nem acessou banco, broker ou serviços externos.
A imagem posterior `rgnfarmasystem:local-final-ui-20261021` já contém a
correção final de CSS. A verificação offline da identidade imutável confirmou
**178 arquivos**: os 176 arquivos da fonte de runtime da rodada temporal e
os dois manifests de dependências. Pillow, certifi, Django e websockets
correspondem às versões instaladas esperadas; PNG e ausência dos caminhos
privados também passaram. Não é afirmação de igualdade com relatórios
documentais escritos depois do build.

A primeira tentativa desse rebuild com `--network=none` falhou ao resolver
os repositórios Debian após um cache miss. O log foi preservado. A receita
normal, com os caches existentes, concluiu com código 0; o teste da imagem
resultante foi executado com rede desativada e sem entrypoint da aplicação.

## Gitleaks: resultados distintos, sem suprimir falhas

As três verificações das 45 alterações/arquivos novos examinados retornaram
zero achados: arquivos completos, índice temporário com `protect --staged` e
`git --pre-commit --staged`. O índice real não foi modificado. Um documento
adicional examinado pelo scanner não se torna autorizado para publicação por
ter passado nessa verificação.

A varredura do diretório público completo continua **FAIL**, com os mesmos
120 achados reproduzidos na baseline pública de `HEAD`: 118 hashes públicos,
uma expressão JavaScript do Quill e um trecho textual do plano NF-e.
A atribuição foi conferida por conteúdo dos arquivos e metadados dos achados;
não se usou baseline para suprimir resultados. Configuração e exceções estão
idênticas a `HEAD`. A política atual observada possui 100 linhas úteis de
exceções; números históricos de outro checkpoint não substituem essa leitura.

Não foi demonstrada ausência absoluta de segredos nem CI remoto da revisão
não publicada. Evidências: `final-gitleaks-attribution-verification.json` e
recibo independente `gitleaks-parent-reconciliation-*`.

Uma verificação adicional do histórico de **todas as refs** terminou em FAIL
com quatro achados em commits anteriores à base local de `main`: a expressão
Quill, o texto NF-e e dois literais de fixtures de chave privada. A tentativa
de interpretar os dois literais como PEM falhou; nenhum valor foi divulgado.
A varredura separada do intervalo **main local → HEAD publicado** terminou
com zero achados. São escopos diferentes: esse PASS não apaga o FAIL de todas
as refs, o FAIL de diretório, nem substitui o scanner das alterações ainda
não commitadas ou CI remoto.

Na verificação posterior da fonte final, os **48 arquivos completos
alterados/novos** examinados passaram com zero achados. O recibo
`final-ui-changed-gitleaks-receipt-1792590253282738000.json` registra os
hashes, código de saída e confirmação de índice/configuração/exceções
inalterados. Esse resultado não inclui documentos de aprovação escritos
depois; sua rechecagem pertence ao recibo do pacote de aprovação.

## Matriz dos formulários: cobertura completa, revisão visual aberta

A rodada estável `browser-matrix192-20261021T111850888441Z` cobriu os 48
formulários de 25 módulos em 320/768/1024/1440 px: 192 combinações sem
faltantes ou duplicatas, 800 cliques reais de abas e 1.082 capturas com hashes
conferidos. Os 176 arquivos do manifesto de fonte foram reconciliados pelo
agente principal. A rodada interrompida por drift permanece histórica, sem
reaproveitamento como evidência atual.

Foi comprovada seleção por teclado nativo em categorias e recebimento, e
recapturado o caso exato de moeda inválida em 320/768 px após estabilização da
transição. As referências antigas divergentes continuam invalidadas. Os dois
POSTs inválidos retornaram 200 com erros e sem criação de pedidos.

**Não é aprovação visual irrestrita:** a rodada recebeu **REVISE, 88/100**.
Na rodada corretiva `browser-readability-round5-20261021T121455560542Z`, uma
regra CSS de cinco linhas estabeleceu 12 px para as ações dos formulários,
sem mudar vendor, cores ou widgets. TDD: quatro RED → quatro GREEN;
regressões: 297 testes Python e oito Node aprovados, sem soma com a suíte
global. A nova matriz novamente cobriu 192 combinações e 800 cliques de abas,
agora com 192 cliques reais de Cancelar e 2.096 amostras de ações a 12 px.
Foram conferidos os hashes de 1.019 capturas e dos 1.090 arquivos do pacote.

O acesso aos dois campos LIMS em 320 px foi comprovado nessa fonte por Tab
nativo e wheel horizontal real, preservando foco e sem `.focus` ou `.value`.
As tentativas anteriores de sandbox continuam falhas históricas, não provas.

A rodada 5 ficou em **REVISE, 89/100**: o datetime da avaliação de risco em
320 px ultrapassava a coluna e recortava o controle. A captura e a geometria
foram conferidas pelo agente principal, sem reclassificar o resultado antigo.

Na rodada 6, `browser-temporal-round6-20261021T124056469551Z`, `min-width: 0`
nos controles e recuperação de padding apenas em inlines mobile com datetime
corrigiram a caixa, texto, segundos e indicador do campo. Tipo nativo, valor
ISO e regras de negócio foram preservados. A contraprova com o CSS anterior
falhou em dois casos; o CSS atual aprovou os seis testes temporais. O recorte
de regressão teve 303 testes Python e oito Node aprovados, sem soma com o full.

A matriz efetiva continua cobrindo 192 células, 800 cliques de abas e 192
cliques de Cancelar, com 2.096 amostras de ações a 12 px. Ela compõe 190 células
originais e duas rechecagens exatas na mesma fonte; os dois timeouts originais
permanecem registrados e sua causa não foi atribuída conclusivamente. A prova
nativa dos dois campos LIMS também foi repetida.

**Permanece REVISE, 89/100:** o popup nativo aberto do Chromium 153 em 320 px
recorta a lateral de seleção de hora. O campo fechado e seu indicador estão
contidos no card; esse sucesso não comprova o popup inteiro. Não se trocou o
widget nem se escondeu a ressalva para elevar a nota. Falta adjudicar ou
revalidar esse comportamento em navegador/dispositivo representativo.

Quatro tentativas de foco em campos dentro de `details` fechado foram
preservadas e diagnosticadas como erro do oráculo de visibilidade. Falhas do
coletor ligadas ao Google Fonts intencionalmente bloqueado não equivalem a
exceções JavaScript da aplicação. Não se removeu nenhum negativo original.

O Chrome terminou com watchdog/code 2; os processos/portas foram conferidos
encerrados. O subprocesso GoogleUpdater apareceu autonomamente: o bloqueio
CDP da página não comprova ausência absoluta de tráfego externo do processo.
Não foram executados auditoria formal WCAG, leitor de tela, contraste ou
revisão visual independente dupla.

## Pendências de encerramento

1. Adjudicar/revalidar o popup nativo aberto a 320 px, sem enfraquecer a
   contenção de rede nem converter evidência incompleta em aprovação visual.
2. Preservar os FAILs dos escopos amplos de scanner e não confundir o PASS
   das alterações ou de um intervalo de commits com aprovação global/CI.

A impressão física continua reservada à indústria; não é substituída por
PNG, testes de navegador ou build Docker.

## Encaminhamento para aprovação

A [solicitação de aprovação](approval-request.md) consolida escopo, limites,
checklist humano e decisões pendentes. Preparar esse encaminhamento não
resolve automaticamente as ressalvas, não equivale ao aceite do usuário
e não autoriza publicação, merge ou deploy.
