# Integração das correções com main e deploy

## Escopo autorizado

Rui autorizou atualização do repositório e da VPS. O checkout corrigido anteriormente tinha HEAD `e29dbef`, enquanto GitHub e produção tinham `bee2e6a5fae8f9b6a7753110f95e526579811c61`, com 49 commits posteriores. O candidato v3 anterior comprova somente aquele snapshot, não valida essas funcionalidades adicionais.

A integração parte do main atual e aplica apenas o delta baseline→v3, usando os blobs reais de base e merge de três vias. Não substitui o main pela árvore antiga. As funcionalidades de NF-e, catálogos e cockpits das entregas posteriores devem permanecer preservadas.

## Gates necessários

A publicação/deploy exige resolução dos conflitos, revisão independente, novo congelamento, suíte completa sem skips/deselection, qualidade global, build limpo, OpenAPI e gates administrativos. O resultado v3 anterior não substitui esses gates. Evidências finais e SHA da implantação serão registrados separadamente após a execução.

Os 98 pins do runtime anteriormente validado são mantidos: a inspeção AST dos 72 arquivos Python adicionados/alterados no remoto não identificou novas dependências externas ausentes nesse runtime. As ferramentas de teste/qualidade permanecem em requirements-dev.txt. O build e a nova suíte devem confirmar essa compatibilidade.

## Evidências históricas

As tentativas rejeitadas ficam preservadas byte a byte. Dois JUnits com whitespace de traceback usam atributo Git `-diff` somente para esses arquivos gerados; fontes e testes continuam com diff e verificações normais. Um alerta gitleaks é um hash SHA-256 do OpenAPI histórico: a exceção exige simultaneamente o caminho exato do registro e a linha exata de chave/valor com 64 dígitos hexadecimais. A prosa NF-e já tinha exceção histórica específica em .gitleaksignore.

## Pré-deploy observado

Host atual conferido como `13.140.139.122`, checkout `/opt/rgnfarmasystem`, árvore limpa e SHA igual ao remoto. App responde internamente; perfil production existente passou em `check --deploy --fail-level WARNING`, sem migrations pendentes naquele momento. Isso não significa validação do novo candidato.

O cloudflared antigo está em restart por conflito de bind em `127.0.0.1:20243`, porta ocupada por outro processo. Não encerrar serviços de outros produtos. A integração conserva endereço configurável isolado `127.0.0.1:20249` e command/healthcheck coerentes; a porta precisa ser reconferida imediatamente antes do deploy.

Backup PostgreSQL/mídia e checksums são obrigatórios antes da promoção/migrations. Preservar o dotenv real sem imprimir/copiar seu conteúdo, HEAD anterior e imagem de rollback. A revisão de código não comprova durabilidade física nem conformidade regulatória humana.

## Integração dirigida antes do congelamento

Os 12 conflitos de três vias foram resolvidos preservando NF-e, cockpits, validações, backup e rollback. O primeiro gate dirigido registrou 151 aprovados e 11 falhas: nove no preparo do cockpit de fornecedor, por tentar criar recebimento já postado sem o método público, e duas por cardinalidade desatualizada do catálogo. Não foi aceito como aprovação.

A inspeção real do registry/discovery mostrou 234 ações: 227 de detalhe e sete de coleção. A importação NF-e é a coleção adicional e está preservada, com multipart, campos order_id/xml e permissão de criação de recebimento. As assertions de cardinalidade continuam exatas e há um controle explícito dessa importação. Foram executados 46 testes de IA, PostgreSQL nativo, catálogo e discovery antes da recaptura de três hashes correntes; a revisão de evidência/documentação passou 20 testes. O hash histórico permanece intacto. Uma tentativa intermediária de atualização foi bloqueada pelo guard de escrita de arquivo e produziu três falhas de evidência; a atualização correta e sua repetição passaram, sem remover asserts.

A inspeção de qualidade identificou 55 achados Ruff e 21 arquivos a formatar nos commits posteriores. A limpeza ficou restrita a imports não usados, bindings não usados preservando as chamadas, três annotations locais e formatação. Os preparos dos cockpits de fornecedor e vendas usam o domínio público, com preparador autorizado separado do usuário sob teste SoD.

O agente registrou RED de 10 falhas/72 aprovados e GREEN de 82 aprovados nos cockpits; os três arquivos somente formatados passaram 43 testes. A verificação AST preservou 118 nomes de testes e 628 assertions nos 12 arquivos, incluindo 82 testes e 459 assertions dos cockpits. Na fonte, AST normalizado preservou métodos, chamadas, bases e lógica dos 11 arquivos de qualidade.

O pai repetiu o gate ampliado de NF-e, estoque/compras, cockpits de fornecedor/vendas, rollback/readiness, evidência e documentação: **185 testes aprovados**, sem skip/deselection. Ruff global passou e todos os 563 arquivos estão formatados. Isso encerra os preparos/qualidade dirigidos, mas não substitui revisão independente nem suíte/gates do próximo snapshot congelado.

## Bloqueio estático do candidato integrado v2

O snapshot v2, com 2.151 fontes registradas, permanece preservado e reprovado: o pipeline de qualidade passou Ruff/formatação, mas MyPy encontrou dois erros no uso de `form_base` como base dinâmica em `base/ui/forms.py:485`, entre 397 fontes verificadas. Esse padrão veio do main atual; não será substituído em runtime pela base padrão, pois isso perderia os formulários personalizados. Bandit e auditoria de dependências não foram executados por aquele pipeline (`set -e`). A correção é restrita à expressão estática da base e à prova de equivalência dos métodos/MRO, em workspace separado do snapshot. Os outros resultados v2 serão preservados como evidência daquele candidato, não como aprovação de fonte posterior.

O diagnóstico separado de Bandit encontrou B405 na importação da classe de exceção `ParseError` do stdlib no importador NF-e; o parser já usa `defusedxml`. No workspace, a exceção passou a ser importada de `defusedxml.ElementTree`, com identidade de classe comprovadamente igual. O AST sem imports permaneceu idêntico; Ruff, formato, MyPy e Bandit desse arquivo passaram. Um probe sem SQL no runtime isolado confirmou NF-e válida aceita e XML malformado/DTD/XXE rejeitados. Não foi adicionado ignore nem alterada a validação. A auditoria de dependências executada separadamente não encontrou vulnerabilidades conhecidas. O snapshot v2 não foi editado; o reparo de tipagem e um novo congelamento/gate completo continuam obrigatórios.

## Correção de tipagem concluída no workspace

O alias explícito em `TYPE_CHECKING` resolveu os dois erros de base dinâmica sem mudar a base escolhida em runtime (`resource.form_base or forms.ModelForm`). O agente repetiu MyPy na lista completa de 397 fontes e o gate dirigido passou 263 testes/7 subtestes. O pai repetiu os 19 testes novos, Ruff e formato nos dois arquivos e comparou diretamente os ASTs do v2 e do workspace: equivalência integral após apagar somente as declarações de typing/grafia do alias. Também conferiu igualdade exata dos snapshots runtime nos 400 casos (200 resources, create/update). A nova fonte aguarda a conclusão do ownership de estoque antes de congelamento, revisão independente e gates completos; não herda aprovação global do v2.

## Correção dos entrypoints e compatibilidade histórica pendente

A frente de estoque alterou somente `inventory/models.py`, `procurement/models.py` e um novo arquivo de regressões. O gate dirigido registrou 178 aprovados, com 47 casos novos; o pai repetiu os 47 casos e confirmou a falha adicional de compatibilidade histórica (um teste falhou). Ruff/formato, MyPy 397 fontes e Bandit do escopo passaram, mas isso não aprovou a entrega.

A confirmação histórica adicionada passou a comparar a fabricação do lote, campo que o fluxo anterior não armazenava. Uma NF-e antiga com fabricação no recebimento e data ausente no lote falha no retry. O agente parou no limite de dois ciclos do terceiro bloqueador. Rui autorizou **um único ciclo adicional, restrito à compatibilidade desse retry histórico**, sem migrations, backfill real ou expansão para outros fluxos. As demais conferências do lançamento e validações de primeira entrada devem permanecer; eventual ausência de proveniência que diferencie NULL legado de apagamento direto deve ser declarada, não escondida por marcador inventado. Depois seguem congelamento novo, revisão fresh e todos os gates, sem herdar os resultados v2.

## Ciclo adicional e correção restrita do teste HTTP

O ciclo adicional alterou somente a confirmação de retry: a ausência de fabricação no lote recebe compatibilidade apenas com vínculos NF-e/XML/hash, origem no próprio item, sem origem de produção nem sublote. Datas presentes continuam estritas e nenhum dado é preenchido durante o retry. Esses vínculos não provam se NULL veio de omissão histórica ou apagamento posterior; um teste documenta esse limite, sem alegar proteção de proveniência inexistente.

A primeira tentativa dirigida registrou 134 aprovados e 30 falhas no teste novo: o helper e os snapshots completos passaram, mas a assertion de ausência de qualquer escrita SQL incluía o INSERT legítimo de `integrations_apicalllog`. O pai reproduziu esse diagnóstico (um teste falhou e um passou), releu o middleware e corrigiu somente o teste novo, sem outro ciclo funcional de produção. A assertion original de zero escritas inesperadas e os snapshots dos sete modelos foram mantidos; somente o INSERT na tabela exata de auditoria é permitido, exigindo exatamente um registro HTTP, usuário, rota, método, status e resultado corretos. Updates/deletes da auditoria e escritas de estoque continuam proibidos; seis casos negativos verificam essa classificação.

O gate completo dessa frente passou **170 testes**, incluindo a compatibilidade NF-e e os 47 casos de entrypoint intactos. Ruff global passou e os 566 arquivos estão formatados. Toda essa evidência ainda exige novo congelamento, revisão independente e repetição completa; não é aprovação de release.

## Revisão independente e extensão autorizada de estoque

A revisão independente do v2 reprovou três caminhos: bypass das validações pelo método público `receive_purchase_receipt_item` ao contabilizar como aprovado; destino persistido inativo aceito após a validação do serializer; e retry que falha após redução permitida da quantidade do pedido, pois compara a quantidade histórica recebida à quantidade atual do pedido. O revisor registrou sondas sintéticas sob rollback; o pai releu os entrypoints e confirmou os pontos de validação ausente, dados de destino em memória e `full_clean()` indevido no retry. Os gates dirigidos da revisão passaram, sem anular essas provas negativas.

O revisor operacional não encontrou novos bloqueadores de segurança/lógica em seu escopo, mas não aprovou o release por causa das falhas globais. Classificou os três achados históricos de Gitleaks: uma frase de planejamento e dois PEMs fictícios estruturalmente inválidos, ausentes da fonte atual. O diff passou; scans de diretório/histórico continuam com exit 1 documentado, não serão apresentados como verdes.

Rui autorizou expressamente pelo formulário: **corrigir somente os três bloqueadores e repetir todos os gates antes de publicar e atualizar a VPS**. A correção de estoque tem ownership separado da tipagem, banco isolado `inventory`, TDD e máximo de dois ciclos. Deve preservar entrada legítima em quarentena, NF-e, cockpits, restrições da primeira contabilização e idempotência sem duplicar ledger. O snapshot v2 e seus resultados permanecem preservados. Sua suíte completa terminou com **2.418 testes e 42 subtestes aprovados**, zero falhas/erros/skips e **86,30% de cobertura (26.442/30.639 linhas)**. O pai reconciliou JUnit (2.460 testes declarados, 2.418 elementos serializados mais 42 subtestes), cobertura e hashes dos artefatos e confirmou as 2.151 fontes sem divergência. Os oito gates administrativos e o build sem cache/pip check também passaram. Esses resultados não eliminam a reprovação do MyPy nem as três provas negativas da revisão; as correções posteriores exigem novo snapshot e repetição completa. Publicação, backup/promoção e deploy continuam pendentes; nenhuma alteração foi feita na produção.
