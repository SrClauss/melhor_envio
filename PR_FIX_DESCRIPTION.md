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

## 🧪 Testado

O script agora funciona corretamente e consegue:
- ✅ Sempre puxar código da branch **master**
- ✅ Evitar erros de branches divergentes
- ✅ Acessar o Python 3 dentro do container
- ✅ Importar o módulo `rocksdbpy` corretamente
- ✅ Executar a migração de dados com sucesso

## 📦 Arquivo Modificado

- `deploy.sh` - Função `run_migration()` atualizada

---

**Tipo**: Bugfix
**Prioridade**: Alta (bloqueia deploy automatizado)
**Impacto**: Script de deploy agora funciona corretamente
