# Pendências conhecidas

## Itens externos

### INC-2026-001 — aprovação formal de encerramento

A contenção técnica do incidente de credenciais está implementada e o teste de
higiene de segredos passa. O encerramento formal continua bloqueado até que
Segurança/DPO e Qualidade registrem, fora do Git, os identificadores das
evidências de rotação, análise de logs, saneamento do histórico e aprovação
GxP/LGPD. O agente não pode simular essas aprovações.

Status: **aberto**. O deploy técnico e seus checks não substituem aprovação
formal de Segurança/DPO e Qualidade.

Referência: `docs/security/INC-2026-001-secrets-exposure.md`.

### Provisionamento do administrador local

O administrador aprovado é `Rui <ruign2015@gmail.com>`. A conta deve permanecer
ativa, staff e superusuária. Sua senha deve ser definida por canal operacional
fora do Git, sem aparecer no terminal, logs, tickets ou documentação, e validada
por `check_password()` após o provisionamento.

```bash
.venv/bin/python manage.py createsuperuser --username Rui --email ruign2015@gmail.com
```

## Pendências técnicas do escopo

A análise técnica de 2026-10-23 identificou pendências de código em
integridade de dados e BPF (segregação de funções, assinatura eletrônica,
guardas de transição, imutabilidade da trilha de auditoria e hash de
evidências). O acompanhamento está em `docs/validation/analysis-2026-10-23.md`.
A declaração de encerramento regulatório geral continua
condicionada aos dois itens operacionais externos acima e aos gates finais
documentados no catálogo de evidências.
