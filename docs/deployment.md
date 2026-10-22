# Deploy single-domain

O runbook canônico é [`docs/DEPLOY_VPS.md`](DEPLOY_VPS.md). A produção autorizada
usa Docker Compose na Contabo, Nginx publicado somente em `127.0.0.1:8081` e
Cloudflare Tunnel para `https://rgnfarmasystem.rgnsystems.com.br`.

## Ordem obrigatória

1. Validar o candidato local, o diff e as migrations pendentes.
2. Registrar o SHA remoto e criar backup PostgreSQL e de mídia.
3. Validar `gzip`, `tar` e SHA-256 dos artefatos.
4. Promover o SHA aprovado por fast-forward.
5. Executar `docker compose -f docker-compose.vps.yml up -d --build --remove-orphans`.
6. Confirmar migrate, saúde dos serviços, login e endpoints internos.
7. Validar o domínio público e preservar backup/revisão anterior até o aceite.

O backup sempre ocorre antes de qualquer `migrate`. Não use `git reset --hard`,
não remova volumes e não carregue `.env` como código shell.

## Execução local sem HTTPS

O servidor de desenvolvimento atende somente em HTTP. Copie
`.env.development.example` e mantenha estas sobreposições locais, nunca no
perfil de produção:

```dotenv
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
```

Depois execute `migrate`, `check` e `runserver 127.0.0.1:8000` com o ambiente
virtual. Os testes usam o PostgreSQL isolado de `docker-compose.test.yml` pelo
perfil `core.settings.test`.

## Catálogos no bootstrap de produção

Após `migrate` e antes de liberar o tráfego da nova instalação, carregue os
catálogos aprovados com:

```bash
.venv/bin/python manage.py load_cosmetics_auxiliary_data --production-catalogs
```

O comando opera somente sobre os snapshots versionados presentes no release e
mantém o lote oficial, auxiliar e mestre em uma transação global. Falhas de
manifesto, validação ou integridade provocam rollback completo. A saída registra
versões, hashes abreviados e contagens, sem expor variáveis de ambiente.

Não atualize fontes durante o deploy. A captura online de IBGE e SIX ISO 4217,
assim como mudanças no catálogo curado de SI/CFOP, deve ocorrer antes da janela,
em mudança separada, com revisão das fontes, exclusões operacionais, contagens e
SHA-256. A carga preserva registros fora dos namespaces gerenciados e não cria
produtos, parceiros, estoque, NCMs ou regras tributárias.

## Verificação da topologia

```bash
docker compose -f docker-compose.vps.yml config --quiet
docker compose -f docker-compose.vps.yml ps
curl -fsS -o /dev/null -w '%{http_code}\n' \
  -H 'Host: rgnfarmasystem.rgnsystems.com.br' \
  http://127.0.0.1:8081/health/
```

PostgreSQL, Redis e RabbitMQ permanecem apenas na rede `backend`. O container
`cloudflared` usa rede host e a origem gerenciada
`http://127.0.0.1:8081`.

## Backup, restauração e retenção

O Compose da Contabo faz o backup de release diretamente pelos serviços `db` e
pelo volume de mídia, como descrito no runbook canônico:

```bash
DB_DEPLOYMENT=container COMPOSE_PROJECT_NAME=rgnfarmasystem \
  BACKUP_DIR=/var/backups/rgnfarmasystem RETENTION_DAYS=14 \
  bash scripts/backup.sh
DB_DEPLOYMENT=container COMPOSE_PROJECT_NAME=rgnfarmasystem \
  BACKUP_DIR=/var/backups/rgnfarmasystem \
  bash scripts/restore.sh \
  --postgres /var/backups/rgnfarmasystem/postgres-AAAAmmdd-HHMMSS.sql.gz --dry-run
```

O restore real exige o mesmo artefato validado, um backup `pre-restore` e a
confirmação `--yes`. O serviço `backup_scheduler` mantém a rotina diária local,
usa `flock`, exige artefatos novos de PostgreSQL e mídia e só então atualiza os
marcadores de saúde.

Agendamento alternativo no host, quando o serviço Compose estiver desabilitado:

```cron
15 2 * * * cd /opt/rgnfarmasystem && DB_DEPLOYMENT=container COMPOSE_PROJECT_NAME=rgnfarmasystem BACKUP_DIR=/var/backups/rgnfarmasystem RETENTION_DAYS=14 bash scripts/backup.sh >> /var/log/rgnfarmasystem/backup.log 2>&1
```

Valide os contratos antes da promoção:

```bash
.venv/bin/python manage.py check_backup_restore_readiness --fail-on-error
.venv/bin/python manage.py check_operational_readiness --fail-on-error
.venv/bin/python manage.py check_product_acceptance --fail-on-error
.venv/bin/python manage.py check_release_readiness --fail-on-error
```

## Saúde e dependências do candidato

`/health/` é liveness: verifica somente que o processo HTTP responde. `/ready/`
verifica PostgreSQL (`SELECT 1`), leitura do cache e conexão com o broker Celery.
Retorna HTTP 503 se qualquer dependência falhar, sem mensagens ou credenciais;
a resposta não é cacheável. O healthcheck do app na VPS usa `/ready/`.

Cada probe executa em um subprocesso descartável com limite de **2 segundos**,
contando importação do driver, conexão, handshake, consulta/leitura e fechamento.
Os três probes sequenciais têm orçamento de espera de **6 segundos**, com margem
até 8 segundos para o handler, abaixo dos 10 segundos do healthcheck do app.
O supervisor mata e recolhe o filho ao vencer o prazo: não deixa threads de
rede bloqueadas. Isso cobre peers que aceitam TCP mas não respondem ao protocolo
ou à consulta; `connect_timeout` ou `statement_timeout` isolados não bastam.
Credenciais/configuração passam como JSON no stdin de código fixo, nunca em
argumentos, código interpolado ou logs; saída/erros dos filhos são descartados.
As conexões e configurações operacionais não são alteradas. O cache recebe apenas
leitura, sem criação de chave. `/health/` permanece leve e sem dependências.

O custo é iniciar três intérpretes e abrir conexões novas por chamada, em vez de
reusar pools operacionais; não use `/ready/` como polling de alta frequência.
Os prazos não são uma garantia de tempo real sob suspensão do processo, starvation
do host ou bloqueio do próprio sistema operacional na criação/recolhimento de
processos. Os testes isolados exercitam sockets silenciosos PostgreSQL (startup
e consulta), Redis e AMQP e exigem resposta em menos de 8 segundos com todos os
filhos recolhidos; sucesso e HTTP 503 preservam `Cache-Control: no-store`.

O healthcheck do túnel usa `cloudflared tunnel --metrics <endereço> ready`, não
apenas a versão do binário. `CLOUDFLARED_METRICS_ADDRESS` configura o mesmo
endereço no comando e no healthcheck; o padrão é `127.0.0.1:20249`. Na inspeção
do host, 20241 e 20243 estavam ocupadas. Como o túnel usa rede host, confirme que
a porta escolhida está livre imediatamente antes do deploy. Não promova um
candidato enquanto o túnel estiver reiniciando ou usando uma porta divergente.

As dependências diretas ficam em `requirements.in`; `requirements.txt` fixa o
runtime completo resolvido em Python 3.14. Ferramentas de teste e qualidade ficam
em `requirements-dev.txt`. Para validar em ambiente limpo:

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip check
.venv/bin/pip-audit -r requirements.txt
```

A versão de `pypdf` incorpora as correções de negação de serviço identificadas
na auditoria de dependências. O pin `6.21.1` também corrige a validação de imagens
JPEG com Pillow descrita na [CVE-2026-113786 / GHSA-5hx5-vpf9-5wcv](https://github.com/py-pdf/pypdf/security/advisories/GHSA-5hx5-vpf9-5wcv).
Após uma atualização autorizada, audite novamente o ambiente completo e execute
os testes de ingestão e relatórios PDF antes de reconstruir a imagem do release.
Um build de teste não reinicia nem promove produção.

## Rollback

O `scripts/deploy-vps.sh` retorna falha de implantação/verificação ao `main`,
que chama `rollback_release` e termina com código 1. Isso inclui Compose inválido,
falha no `up`, serviços/containers ausentes, erro de listagem ou `docker inspect`,
túnel unhealthy, falha de curl na origem/domínio e `check --deploy` malsucedido.
As funções usadas na condição do `main` verificam explicitamente o retorno de
cada comando: nesse contexto Bash não aplica `set -e` dentro das funções.
O helper de readiness apenas registra erro e retorna 1; não usa o `fail()` fatal
de preflight, pois um `exit` interno impediria o rollback. Falhas antes de promover
o candidato continuam interrompendo o preflight, sem rollback do candidato.

Reimplante o SHA e a imagem registrados antes da janela. Restaure banco ou
mídia somente quando uma migration incompatível tiver sido aplicada, depois de
validar os hashes. O rollback do script reimplanta a revisão anterior e não
restaura banco/mídia automaticamente; se a reimplantação falhar, a execução continua
malsucedida. Backups não são apagados no rollback.
