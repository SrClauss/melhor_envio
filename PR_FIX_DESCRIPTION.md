# fix: Correção do script de deploy automatizado

## 🐛 Problema

O script `deploy.sh` estava tentando executar a migração de dados (`migrate_existing_shipments.py`) diretamente no host, mas:

1. O Python e as dependências (como `rocksdbpy`) estão instalados **dentro do container Docker**
2. O script de migração não estava presente dentro do container antigo (antes do rebuild)

Isso causava erro: `ModuleNotFoundError: No module named 'rocksdbpy'`

## ✅ Solução

### Commit 1: `fix: executa migração dentro do container Docker`
- Modificado para executar o script de migração **dentro do container** usando `docker-compose exec`
- Garante que o Python e todas as dependências estejam disponíveis

### Commit 2: `fix: copia script de migração para container antes de executar`
- Adicionado step para copiar o script de migração para dentro do container usando `docker cp`
- Garante que o script esteja disponível dentro do container antes da execução

### Commit 3: `fix: script de deploy sempre puxa da branch master`
- Script de deploy agora sempre faz `git pull` da branch **master**
- Garante que está na branch master antes de fazer pull
- Usa estratégia `--no-rebase` para evitar conflitos de branches divergentes
- Simplifica processo de deploy (sempre pega código aprovado e mergeado)

### Commit 4: `fix: atualiza docker-compose para docker compose (V2)`
- Substitui todas as ocorrências de `docker-compose` por `docker compose`
- Compatível com Docker Compose V2 (comando moderno sem hífen)
- Corrige 15 ocorrências no script de deploy

### Commit 5: `fix: corrige verificação do arquivo docker-compose.yaml`
- Corrige verificação do nome do arquivo (mantém hífen no nome do arquivo)
- Apenas os comandos mudaram para `docker compose`, o arquivo continua sendo `docker-compose.yaml`

### Commit 6: `fix: para container antes de fazer backup para evitar lock do RocksDB`
- Scripts de backup agora param o container antes de copiar o banco
- Evita problemas com arquivo LOCK do RocksDB
- Reinicia container automaticamente após backup
- Aplica correção em `backup-db.sh` e `backup-cron-weekly.sh`
- Garante integridade do backup mesmo em caso de erro (sempre tenta reiniciar)

## 📝 Mudanças no `deploy.sh`

Variável `BRANCH`:
- Alterada de branch específica para `"master"`
- Garante que deploy sempre usa código aprovado

Função `update_code()` agora:
1. Garante que está na branch **master** (cria se não existir)
2. Faz `git pull --no-rebase origin master`
3. Evita erros de branches divergentes

Função `run_migration()` agora:
1. Verifica se container está rodando (inicia se necessário)
2. **Copia** `migrate_existing_shipments.py` para dentro do container
3. Executa dry-run **dentro do container**: `docker-compose exec -T fastapi_app python3 migrate_existing_shipments.py --dry-run`
4. Se aprovado, executa migração real **dentro do container**

Scripts de backup (`backup-db.sh` e `backup-cron-weekly.sh`) agora:
1. Param o container com `docker compose down`
2. Aguardam 2 segundos para garantir liberação do lock
3. Copiam o banco de dados com segurança
4. Reiniciam o container automaticamente
5. Em caso de erro, ainda tentam reiniciar o container

## 🧪 Testado

O script agora funciona corretamente e consegue:
- ✅ Sempre puxar código da branch **master**
- ✅ Evitar erros de branches divergentes
- ✅ Usar comandos `docker compose` (V2) corretamente
- ✅ Acessar o Python 3 dentro do container
- ✅ Importar o módulo `rocksdbpy` corretamente
- ✅ Executar a migração de dados com sucesso
- ✅ Fazer backup sem problemas de lock do RocksDB

## 📦 Arquivos Modificados

- `deploy.sh` - Atualizado para usar docker compose V2 e sempre puxar da master
- `backup-db.sh` - Atualizado para parar container antes de backup
- `backup-cron-weekly.sh` - Atualizado para parar container antes de backup

---

**Tipo**: Bugfix
**Prioridade**: Alta (bloqueia deploy automatizado)
**Impacto**: Script de deploy agora funciona corretamente
