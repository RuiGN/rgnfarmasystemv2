# Identificadores automáticos

## ID e código são campos distintos

O ID continua sendo a chave primária numérica. As relações existentes continuam apontando para essa chave; nenhum modelo ou relacionamento é convertido para uma chave textual.

Nos modelos com `AutoCodeMixin` e `CODE_PREFIX`, o código vazio é preenchido como `CODE_PREFIX-ID`, usando o ID real e sem zeros adicionais. Por exemplo: `CAP-42` identifica o registro de ID42 com prefixoCAP. O formato não usa um contador independente de códigos.

Códigos já preenchidos não são renumerados automaticamente. Isso inclui códigos legados, descritivos das cargas e oficiais, como `BRL`. Modelos sem prefixo ou que usam somente ID mantêm seu contrato. Campos automáticos da API continuam somente leitura onde esse já era o comportamento; enviar um código nesse campo não substitui a geração do servidor.

## Persistência e limites

O gerador reserva um valor da sequência PostgreSQL da própria PK antes de inserir. O código definitivo fica disponível para os sinais de criação e a auditoria; não existe uma inserção intermediária com código provisório. Para um registro existente com código vazio, usa-se a PK já atribuída, sem alocar outra.

O save respeita transação, alias de banco e opções Django. Uma falha reverte a escrita e restaura a identidade/estado em memória para permitir nova tentativa. O avanço de uma sequência PostgreSQL não é transacional: erros, exclusões e rollbacks podem deixar lacunas, sem justificar a reutilização de IDs. Conflitos de unicidade não autorizam trocar o ID ou sobrescrever outro registro silenciosamente.

O prefixo não pode ser vazio/branco e o código deve caber em `code.max_length`. Ausência da sequência necessária falha antes de inserir. A operação depende do PostgreSQL exigido pelo projeto.

`bulk_create`, `QuerySet.update` e SQL direto não executam `Model.save`; não passam a gerar códigos automaticamente. Integrações que usam esses caminhos devem fornecer seus valores explicitamente e preservar as validações aplicáveis.

`IdentifierSpec`, `AUTOMATIC_IDENTIFIERS`, `sequence_code` e identificadores operacionais diários continuam separados desta regra. O helper legado `generate_code` permanece disponível para seus consumidores próprios, mas não é a fonte de `AutoCodeMixin.code`.

## Verificação

Os contratos estão em `tests/test_code_primary_key.py`, `tests/test_codegen.py` e `tests/test_automatic_fields.py`. A comparação das APIs usa o ID retornado, não um valor sequencial fixo. O inventário dos modelos e os resultados executados pertencem às evidências da rodada; esta documentação não substitui um resultado de teste ou aceite industrial.
