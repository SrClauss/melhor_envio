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

### Commit 7: `fix: reorganiza fluxo de deploy para evitar lock do RocksDB durante migração`
- Deploy agora mantém container **parado** após backup
- Migração usa `docker compose run` (container temporário, sem FastAPI rodando)
- Banco permanece sem lock durante backup e migração
- Apenas após migração completa o container é rebuilded e iniciado
- Novo fluxo: backup (para) → update → migração (temp) → rebuild → start

### Commit 8: `fix: adiciona recuperação automática em caso de falha no deploy`
- Deploy agora usa `trap EXIT` para capturar erros
- Se qualquer passo falhar, automaticamente tenta reiniciar container
- Container reinicia com código ANTERIOR (sistema volta a funcionar)
- Mensagens claras sobre o que fazer em caso de falha
- Evita deixar sistema offline por erro no deploy

### Commit 9: `feat: adiciona script de restauração para recuperar sistema`
- Novo script `restore.sh` para recuperação manual
- 3 modos: interativo, rápido (último backup), apenas reiniciar
- Lista todos os backups disponíveis com data e tamanho
- Restaura banco de dados de qualquer backup
- Útil para recuperação após problemas no deploy

## 📝 Mudanças no `deploy.sh`

Variável `BRANCH`:
- Alterada de branch específica para `"master"`
- Garante que deploy sempre usa código aprovado

Função `update_code()` agora:
1. Garante que está na branch **master** (cria se não existir)
2. Faz `git pull --no-rebase origin master`
3. Evita erros de branches divergentes

Função `backup_database()` agora:
1. Para o container com `docker compose down`
2. Faz backup do banco (sem lock)
3. **NÃO reinicia** o container (fica parado para migração)
4. Limpeza automática de backups antigos

Função `run_migration()` agora:
1. Executa com container **parado** (banco sem lock)
2. Usa `docker compose run --rm` (container temporário)
3. Monta script de migração como volume read-only
4. Roda migração e remove container temporário automaticamente
5. FastAPI não inicia durante migração (apenas Python + dependências)

Scripts de backup (`backup-db.sh` e `backup-cron-weekly.sh`) agora:
1. Param o container com `docker compose down`
2. Aguardam 2 segundos para garantir liberação do lock
3. Copiam o banco de dados com segurança
4. Reiniciam o container automaticamente
5. Em caso de erro, ainda tentam reiniciar o container

Fluxo principal do deploy (`deploy.sh`):
1. `backup_database` - Para container e faz backup (sem reiniciar)
2. `update_code` - Pull da master
3. `run_migration` - Migração com container temporário (banco sem lock)
4. `start_containers` - Rebuild e inicia container novo
5. `check_health` + `check_cronjobs` - Validação
6. Se qualquer passo falhar: `trap EXIT` reinicia container com código anterior

Script de restauração (`restore.sh`):
- **Modo interativo**: Lista backups e permite escolher
- **Modo rápido**: `./restore.sh quick` - restaura último backup
- **Modo restart**: `./restore.sh restart` - apenas reinicia container
- Usado para recuperação manual após problemas

## 🧪 Testado

O script agora funciona corretamente e consegue:
- ✅ Sempre puxar código da branch **master**
- ✅ Evitar erros de branches divergentes
- ✅ Usar comandos `docker compose` (V2) corretamente
- ✅ Parar container para backup sem lock
- ✅ Executar migração sem conflito de lock do RocksDB
- ✅ Usar `docker compose run` para container temporário
- ✅ Acessar o Python 3 e rocksdbpy corretamente
- ✅ Completar fluxo inteiro de deploy automaticamente
- ✅ **Recuperar automaticamente** se algo der errado (container reinicia)
- ✅ Restaurar backups manualmente com `restore.sh`
- ✅ Listar backups disponíveis e escolher qual restaurar

## 📦 Arquivos Criados/Modificados

### Novo Arquivo
- ✨ `restore.sh` - Script de restauração e recuperação do sistema

### Arquivos Modificados
- 🔧 `deploy.sh` - Fluxo corrigido + recuperação automática em caso de falha
- 🔧 `backup-db.sh` - Para container antes de backup e reinicia após
- 🔧 `backup-cron-weekly.sh` - Para container antes de backup e reinicia após

---

**Tipo**: Bugfix
**Prioridade**: Alta (bloqueia deploy automatizado)
**Impacto**: Script de deploy agora funciona corretamente
