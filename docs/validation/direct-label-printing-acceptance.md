# Aceite da impressão direta de etiquetas

## Objetivo e contrato operacional

Validar o envio direto de etiquetas TSPL2 do servidor Django, através da VPN,
para a impressora de rede configurada com porta TCP 9100 por padrão.

A etiqueta deve conter somente Produto, Lote, Validade e a assinatura
operacional formada pelo nome do usuário autenticado e pela data/hora do
servidor. Não deve conter código de barras, data de fabricação ou sublote.

O retorno de sucesso confirma o envio ao socket; não confirma a saída física
da etiqueta. A operação funciona sem repetição automática. Em qualquer
resultado incerto, verifique fisicamente a impressora antes de repetir a ação.

## Registro da execução

Preencher sem registrar senhas, tokens ou outros segredos:

| Campo | Registro |
|---|---|
| Executor | Pendente |
| Data e hora | Pendente |
| Ambiente | Pendente |
| Modelo da impressora | Pendente |
| IP/hostname da impressora | Pendente |
| Porta | 9100 |
| Versão/commit da aplicação | Pendente |
| Lote controlado | Pendente |
| Resultado geral | Pendente — exige VPN e equipamento físico |
| Referência da evidência | Pendente |

## Pré-condições

- [ ] O servidor da aplicação possui rota VPN para a rede local da impressora.
- [ ] O IP/hostname e a porta TCP estão autorizados pela infraestrutura.
- [ ] A impressora usa TSPL2 e possui mídia com as dimensões cadastradas.
- [ ] Existe exatamente uma configuração ativa em **Integrações → Impressora
  de etiquetas**.
- [ ] O lote de teste possui Produto, Lote e Validade conhecidos.
- [ ] O executor usa conta individual com `inventory.view_stocklot`.

## Casos de aceite físico e funcional

1. **Alcance pela VPN**
   - Verificar, a partir do servidor Django, a conectividade TCP com o host e a
     porta configurados.
   - Registrar comando, horário e evidência, sem expor credenciais.

2. **Permissão**
   - Confirmar que usuário sem `inventory.view_stocklot` não vê a ação e recebe
     acesso negado na API.
   - Confirmar que usuário autorizado vê **Etiqueta** em cada linha da listagem
     de lotes e **Imprimir etiqueta** no detalhe do lote.
   - Com pelo menos dois lotes controlados, selecionar a segunda linha e conferir
     que somente a etiqueta daquele lote é enviada, com confirmação explícita.
   - Cancelar a confirmação de outra linha e confirmar que nada é enviado.
   - Durante o envio, conferir que o botão selecionado fica desabilitado.

3. **Conteúdo impresso**
   - Enviar uma etiqueta do lote controlado.
   - Conferir Produto, Lote, Validade, nome do usuário e data/hora do servidor.
   - Confirmar ausência de código de barras, fabricação e sublote.

4. **Sanitização**
   - Usar produto com acentos e confirmar texto ASCII legível no equipamento,
     por exemplo `Solução Ácida` como `Solucao Acida`.

5. **Timeout e recusa de conexão**
   - Com mudança controlada e autorizada, indisponibilizar a impressora ou usar
     uma porta de teste fechada.
   - Confirmar mensagem segura de indisponibilidade após o timeout, sem revelar
     detalhes internos da rede.
   - Restaurar a configuração aprovada após o teste.

6. **Ausência de repetição automática**
   - Depois do timeout ou da recusa, restaurar a conectividade sem clicar
     novamente.
   - Confirmar que nenhuma etiqueta atrasada ou duplicada é impressa.
   - Antes de um reenvio manual, conferir se não houve saída física no resultado
     anterior.

## Critérios de aprovação

- Todos os casos acima possuem resultado e evidência rastreável.
- Nenhum segredo aparece nas evidências.
- A impressão física corresponde ao conteúdo aprovado.
- Não há reenvio automático nem etiqueta duplicada após falha incerta.
- Desvios encontrados são registrados no processo de qualidade aplicável.

Este documento permanece com aceite físico pendente até ser executado em um
ambiente com VPN e impressora disponíveis. Testes automatizados não substituem
essa evidência.
