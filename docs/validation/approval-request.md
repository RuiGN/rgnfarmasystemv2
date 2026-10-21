# Solicitação de aprovação — produtos, fórmulas e formulários

## Decisão solicitada

**Status histórico do candidato: aceite funcional com ressalvas registrado em 21/10/2026. Não aprovado para merge ou deploy.**

Aprovar ou solicitar ajustes no fluxo integrado e na simplificação descritos abaixo, considerando expressamente as ressalvas. A preparação deste pacote não representa aceite funcional do usuário, CI remoto aprovado, homologação regulatória ou entrada em produção.

A revisão estática independente complementar concluiu **sem achados acionáveis no recorte inspecionado**, com confiança média. O parecer está anexado ao pacote; não substitui as verificações de execução nem a aprovação humana.

## Alterações entregues

- **Produtos → Novo/Editar:** abas **Produto**, **Fórmula mestra** e **Componentes**.
- **Fórmulas mestras:** abas **Fórmula mestra** e **Componentes**, sem aba Produto separada. O vínculo obrigatório com o produto permanece dentro da fórmula.
- **Componentes:** cadastro de material e categoria na própria aba, usando formulários compartilhados. O cadastro rápido de material apresenta quatro campos; QA, fiscal e demais classificações continuam disponíveis no cadastro completo.
- Seleção explícita de versão, validação no servidor, transação e rollback do produto/fórmula/componentes. Histórico, permissões, CSRF e auditoria preservados.
- Filtros relacionais dependentes, inclusive tipo/categoria superior, sem ampliar querysets autorizados. Verificação final de filhos persistidos e omitidos nos fluxos HTML corrigidos.
- Identificadores automáticos e controles internos deixam de ocupar a interface; campos de negócio não foram removidos somente por serem opcionais. Não há remoção de tabelas, colunas ou migrations nesta alteração.
- Ações dos formulários a 12 px e contenção do campo de data/hora em telas estreitas, preservando tipo nativo, calendário, segundos e valor ISO.
- Correções locais de dependências: certifi 2026.10.19 e Pillow 13.0.0.

**Atenção:** cadastrar material/categoria é uma gravação separada, anunciada na tela. Esses cadastros permanecem mesmo que o formulário principal seja cancelado; não há alegação de rollback conjunto dessas ações independentes.

## Evidências e respectivos limites

| Superfície | Resultado observado | Limite da evidência |
| --- | --- | --- |
| Fluxo e simplificação | 154 testes Python e oito Node aprovados; 59 templates compilados | Recorte específico, não somar aos demais |
| Suíte global | 3.148 testes e 42 subtestes aprovados; cobertura 86,82%; quatro skips | Executada antes das últimas correções CSS; não é o mesmo snapshot integral posterior |
| Cenários Linux ignorados | Cinco testes aprovados, sem skips, incluindo os quatro cenários anteriores | Recorte sobreposto à suíte global; não somar; não comprova restore operacional |
| Regressão após CSS | 303 testes Python e oito Node aprovados; seis testes temporais aprovados | Recortes sobrepostos; não é nova suíte global |
| Matriz de formulários | 48 formulários, 25 módulos, quatro larguras, 192 células efetivas; 800 cliques de abas e 192 de Cancelar | Revisão visual REVISE, 89/100; dois timeouts originais preservados com rechecagens exatas |
| Build local | Imagem reconstruída; teste offline confirmou 178 arquivos de runtime/dependências, versões e PNG | Sem entrypoint da aplicação, banco, broker ou rede; não é teste de implantação |
| Dependências e qualidade | Auditoria estrita sem vulnerabilidades conhecidas; Ruff, formato, Mypy, Bandit e Node aprovados nos registros | CI remoto da revisão atual não executado; não alegar ausência absoluta de vulnerabilidades |
| Segredos nas fontes para aprovação | 49 arquivos completos alterados/novos passaram com zero achados, sem alterar regras ou índice | Recibo final vincula o conteúdo exato fornecido; escopos amplos continuam FAIL; não é scanner de todo o histórico nem de metadados gerados |

A imagem local candidata é `rgnfarmasystem:local-final-ui-20261021`. Sua identidade imutável e os hashes da fonte constam dos recibos, não apenas da tag mutável.

## Revisão estática independente

O parecer `approval-independent-review-deleg_a9fa9aa8.json` revisou o delta da base indicada, incluindo adições não commitadas. O escopo inclui os editores integrados, cadastro relacionado, builders/persistência HTML, helper relacional, validações alteradas, scripts de abas/filtros e renderizadores pertinentes. A conclusão `ship` restringe-se a esse recorte estático; não é aprovação de implantação. A verificação sintática cobriu 29 arquivos Python e os dois assets JavaScript.

A questão aberta do revisor é a serialização concorrente entre o editor integrado e escritores independentes de fórmulas/componentes: o protocolo compartilhado entre todos os escritores não foi estabelecido nesta revisão. Não se certificam API, Admin, bulk ou SQL direto. As equivalências de regras de todos os domínios e todos os testes secundários também não receberam revisão funcional integral. Essas lacunas não foram convertidas em defeitos demonstrados nem em garantias de cobertura universal.

Após o parecer, somente documentos de encaminhamento foram atualizados. A integridade dos arquivos de implementação revisados e a correspondência do runtime com a imagem foram reconferidas. Os recibos de Ruff, formato, 18 testes Node, higiene do diff e teste offline da imagem foram renovados nesta preparação; a suíte global e os recortes Python acima não foram reexecutados nesta etapa.

## Ressalvas que exigem decisão ou validação posterior

1. **Popup nativo a 320 px:** o controle fechado foi corrigido; o popup aberto do Chromium 153 ainda recorta a seleção de hora. A aprovação visual irrestrita continua pendente. Validar em navegador/dispositivo representativo ou decidir por ajuste separado; não considerar a ressalva automaticamente aceita.
2. **Scanner amplo:** diretório completo retornou 120 achados reproduzidos na baseline pública de HEAD; todas as refs históricas retornaram quatro. O PASS das alterações e do intervalo publicado não apaga esses FAILs. A classificação e os escopos estão documentados em `local-finalization.md`; nenhuma exceção foi acrescentada.
3. **Publicação e CI:** código atual não commitado/publicado; CI remoto dessa revisão não executado. Aprovação deste pacote não autoriza commit, push, merge ou deploy por si só. Qualquer publicação exige autorização específica e a verificação do commit exato.
4. **Validação na indústria:** impressão física, login com perfis reais, treinamento e aceite operacional/regulatório não são comprovados pelos testes locais. A impressora não está disponível localmente.
5. **Outros limites:** não houve auditoria formal WCAG/leitor de tela, revisão visual independente dupla, comprovação de isolamento absoluto de tráfego do navegador no SO ou demonstração de restore/offsite/atomicidade banco+mídia.

## Checklist para o aprovador

Os itens abaixo são a pauta de aceite humano, não afirmações de execução adicional nesta etapa.

- [ ] Conferir as três abas na criação e edição de Produto e as duas abas em Fórmulas mestras.
- [ ] Conferir o cadastro de material e categoria em Componentes e compreender suas gravações separadas.
- [ ] Conferir seleção explícita de versão e preservação do histórico.
- [ ] Conferir comportamento de filtros dependentes, mensagens de erro e perfis sem permissão.
- [ ] Revalidar o popup de data/hora no navegador/dispositivo de uso ou solicitar ajuste antes do aceite visual.
- [ ] Registrar a decisão sobre as ressalvas de scanner sem alterar automaticamente as regras.
- [ ] Registrar aprovação funcional ou ajustes solicitados, nome do responsável e data.
- [ ] Se desejar publicação para revisão/CI ou homologação, autorizá-la separadamente, com escopo e commit definidos. Produção não está incluída.

**Decisão humana registrada:** o usuário respondeu “aprovo” ao aceite funcional com as ressalvas apresentadas. O registro separado `functional-approval-20261021T114405-0300.json`, no diretório de evidências abaixo, vincula o aceite ao ZIP original por hash. O ZIP e seus registros históricos não foram sobrescritos. Isso não certifica execução do checklist manual; nenhum desses cenários foi marcado como executado pelo usuário.

Posteriormente, o usuário solicitou fechar as ressalvas e autorizou, por decisões explícitas separadas, commit/push dos arquivos públicos revisados para atualizar o PR draft e executar CI, sem merge/deploy, e exceções pontuais de scanner com prova e testes negativos. O estado dessa nova rodada consta de [Encerramento das ressalvas](reservation-closure.md), não do resultado histórico do candidato original.

## Fonte, reprodução e documentos de apoio

- Base Git publicada: `d805ae54cf0bb985389d22c3d0c71f355a93cd21`. O candidato inclui alterações não commitadas e arquivos novos; `git diff` sozinho não contém estes últimos.
- [Fluxo funcional e controles](../ui/product-formula-workflow.md).
- [Inventário e regras relacionais](related-resource-fields.md).
- [Simplificação de templates](../ui/template-simplification.md).
- [Relatório técnico e limites completos](local-finalization.md).
- Evidências locais imutáveis: `/Users/rgnsystems/.hermes/artifacts/rgnfarmasystemv2/product-editor-simplification/`. O pacote inclui um índice de evidências, manifesto dos arquivos fornecidos e suas verificações de integridade; não inclui dotenv, credenciais, mídia, banco, estado privado do agente ou o documento privado de carga/treinamento.

O pacote de fontes é um **delta para revisão sobre a base indicada**, não uma distribuição completa nem um instalador. Não executar scripts operacionais a partir dele para aplicar alterações sem revisão e autorização.
