# Cabeçalho compacto e navegação hierárquica

## Escopo

Ajuste solicitado para a homologação usada em treinamento da indústria de cosméticos.
A classe existente no projeto é `.page-header`.

- A trilha de navegação aparece antes do título no HTML e acima dele na tela.
- A ordem dos elos da trilha e seus destinos são preservados.
- O texto descritivo secundário foi removido do título do cabeçalho, incluindo
  páginas de módulos, listas, detalhes, espaços de trabalho e o componente compartilhado.
- O logotipo da aplicação mantém a imagem institucional configurada e a proporção,
  com limites de 120 × 40 px no menu expandido e 48 × 36 px no menu recolhido.
- Removidos os estilos inline das imagens, que sobrepunham o tamanho definido no CSS.
- A geometria do shell Duralux, as ações dos cabeçalhos, permissões, formulários
  e conteúdo operacional abaixo do cabeçalho não foram alterados por este ajuste.

## Implementação

A ordenação foi aplicada aos 30 templates que possuem `.page-header-title`,
sem usar `order` ou inversão visual que divergisse da leitura do DOM.
O CSS é restrito aos elementos internos do cabeçalho e ao logotipo da aplicação.
A trilha quebra linhas em telas estreitas e mantém leitura da esquerda para a direita.

Arquivos centrais: `templates/base.html`, `static/css/app.css`,
`templates/includes/page_header.html` e templates consumidores.

## Verificação observada

`tests/test_compact_page_header.py` verifica a ausência do subtítulo, a ordem
hierárquica no DOM em todos os templates, os limites de tamanho e a ausência de
estilo inline nas imagens. O desenvolvimento registrou RED antes de cada ajuste.

Conjunto executado com `tests/test_responsive_layout_css.py`: **94 testes aprovados**.
Ruff, verificação de formato e `git diff --check`: aprovados.
Os testes usam configuração isolada e bloqueiam a leitura do dotenv operacional.

### Navegador: rodada final observada

Foram renderizados os cabeçalhos reais de módulo, listagem, formulário e detalhe
de Compras nas larguras de 320, 768, 1024 e 1440 px: **16 capturas**, com as
dimensões efetivas conferidas. Também foram registrados **7 estados de interação**:
recolher/expandir o menu desktop, navegar pela trilha e abrir/fechar os painéis móveis.
Foram observadas cinco transições de foco por Tab, sem pretender uma auditoria
completa de acessibilidade.

A inspeção revelou um conflito em 768 px entre `flex: 1` e a largura de 100%
preexistente do cabeçalho de detalhes. A correção usa `flex: 1 1 auto` para respeitar
a base automática e a quebra de linha existente. O título e as ações foram
recapturados após a correção, em uma nova rodada com novo fingerprint.

Nas capturas finais: sem sobreposição identificada no cabeçalho, sem transbordamento
horizontal, sem subtítulo descritivo e sem erros ou avisos no coletor de console.
O contraste calculado da etapa atual da trilha sobre o branco observado foi 4,975:1.
O logo expandido foi medido em 120 × 25,703125 px, mantendo proporção.

Limite: esta rodada usou templates/CSS congelados e corpo fictício somente leitura,
com o backend de banco desabilitado. Não verifica autenticação, fluxos de gravação,
as novas abas por domínio ou o estado servido pela VPS. Ainda não houve segundo
parecer visual independente.

Evidências em `~/.hermes/artifacts/rgnfarmasystemv2/cosmetics-training-seed-2026-10-20/header-browser-round3/`.
Fingerprint da fonte renderizada: `4a6d31aacf03c728103594d8915542c1a5b4e7a177bca7a9e90e28de971f954f`.

## Estado de implantação

Implementação e verificação visual local preparadas. O usuário autorizou somente
commit/push do candidato e atualização da PR em rascunho para executar o CI Linux.
Essa autorização não inclui merge ou deploy. A publicação na VPS de teste,
a aprovação integrada com as abas por domínio e a checagem do estado efetivamente
servido permanecem pendentes. Os resultados locais acima não equivalem ao CI do
novo commit; identidade e resultado remoto devem ser conferidos na execução exata.
