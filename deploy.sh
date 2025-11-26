#!/bin/bash

#######################################
# Script de Deploy Automatizado
# Melhor Envio - Sistema de Rastreamento
#######################################

# Função de cleanup em caso de erro
cleanup_on_error() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo ""
        print_error "❌ Deploy falhou! Tentando reiniciar container..."
        echo ""

        # Tentar reiniciar container
        cd "${APP_DIR}" 2>/dev/null || cd /opt/melhor_envio
        if docker compose up -d 2>/dev/null; then
            print_warning "⚠️  Container reiniciado com código ANTERIOR"
            print_warning "    O deploy NÃO foi concluído, mas o sistema está online"
            print_warning "    Corrija o erro e execute ./deploy.sh novamente"
        else
            print_error "❌ FALHA ao reiniciar container!"
            print_error "   Execute manualmente: cd ${APP_DIR} && docker compose up -d"
        fi
    fi
}

# Registrar cleanup para rodar em caso de erro
trap cleanup_on_error EXIT

# Não usar 'set -e' para permitir cleanup controlado

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Diretório base (ajustar conforme necessário)
APP_DIR="/opt/melhor_envio"
BACKUP_DIR="${APP_DIR}/backups"
BRANCH="master"

# Funções auxiliares
print_step() {
    echo -e "\n${BLUE}==>${NC} ${1}"
}

print_success() {
    echo -e "${GREEN}✓${NC} ${1}"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} ${1}"
}

print_error() {
    echo -e "${RED}✗${NC} ${1}"
}

# Confirmar execução
confirm() {
    read -p "$1 (s/N): " response
    case "$response" in
        [sS][iI][mM]|[sS])
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# Verificar se está no diretório correto
check_directory() {
    print_step "Verificando diretório..."

    if [ ! -f "main.py" ] || [ ! -f "docker-compose.yaml" ]; then
        print_error "Não estou no diretório correto do projeto!"
        print_warning "Execute: cd ${APP_DIR}"
        return 1
    fi

    print_success "Diretório OK"
}

# Fazer backup do banco de dados
backup_database() {
    print_step "Fazendo backup do banco de dados..."

    # Parar container primeiro
    print_step "Parando container para backup seguro..."
    docker compose down
    sleep 2

    BACKUP_DIR="/opt/melhor_envio/backups"
    DB_PATH="/opt/melhor_envio/database.db"
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="${BACKUP_DIR}/database_${TIMESTAMP}.db"

    # Criar diretório de backup se não existir
    mkdir -p "${BACKUP_DIR}"

    # Verificar se o banco existe
    if [ ! -d "${DB_PATH}" ]; then
        print_error "Banco de dados não encontrado em ${DB_PATH}"
        return 1
    fi

    # Fazer backup
    echo "📦 Criando backup..."
    echo "   Origem: ${DB_PATH}"
    echo "   Destino: ${BACKUP_FILE}"

    if cp -r "${DB_PATH}" "${BACKUP_FILE}"; then
        SIZE=$(du -sh "${BACKUP_FILE}" | cut -f1)
        print_success "Backup criado: $(basename ${BACKUP_FILE}) (${SIZE})"

        # Limpeza de backups antigos
        cd "${BACKUP_DIR}"
        BACKUP_COUNT_BEFORE=$(ls -1 | grep database_ | wc -l)
        ls -t | grep database_ | tail -n +11 | xargs -r rm -rf
        BACKUP_COUNT_AFTER=$(ls -1 | grep database_ | wc -l)

        if [ $BACKUP_COUNT_BEFORE -gt 10 ]; then
            REMOVED=$((BACKUP_COUNT_BEFORE - BACKUP_COUNT_AFTER))
            echo "   Removidos ${REMOVED} backups antigos (mantendo últimos 10)"
        fi

        print_success "Backup concluído (${BACKUP_COUNT_AFTER} backups disponíveis)"
    else
        print_error "Falha ao criar backup!"
        return 1
    fi
}

# Atualizar código do repositório
update_code() {
    print_step "Atualizando código do repositório..."

    # Verificar se há mudanças não commitadas
    if [ -n "$(git status --porcelain)" ]; then
        print_warning "Existem mudanças não commitadas no diretório"
        if ! confirm "Deseja continuar mesmo assim?"; then
            print_warning "Deploy cancelado pelo usuário"
            trap - EXIT
            exit 0
        fi
    fi

    # Fazer pull (sempre da master, com merge strategy)
    print_step "Executando git pull da master..."

    # Garantir que estamos na branch master
    if ! git checkout master 2>/dev/null; then
        print_warning "Branch master não existe localmente, criando..."
        git checkout -b master origin/master
    fi

    # Pull com merge (não rebase)
    if git pull --no-rebase origin "${BRANCH}"; then
        print_success "Código atualizado da branch ${BRANCH}"
    else
        print_error "Falha ao fazer git pull!"
        return 1
    fi
}

# Executar migração de shipments existentes
run_migration() {
    print_step "Migração de shipments existentes..."

    if [ ! -f "./migrate_existing_shipments.py" ]; then
        print_warning "Script de migração não encontrado, pulando..."
        return 0
    fi

    # Executar migração usando docker compose run (cria container temporário, sem iniciar FastAPI)
    # Banco está parado, então não há lock
    print_step "Executando dry-run da migração (container temporário)..."
    if docker compose run --rm -v "$(pwd)/migrate_existing_shipments.py:/app/migrate_existing_shipments.py:ro" fastapi_app python3 /app/migrate_existing_shipments.py --dry-run; then
        print_success "Dry-run concluído"

        if confirm "Deseja executar a migração de verdade?"; then
            print_step "Executando migração..."
            if docker compose run --rm -v "$(pwd)/migrate_existing_shipments.py:/app/migrate_existing_shipments.py:ro" fastapi_app python3 /app/migrate_existing_shipments.py; then
                print_success "Migração concluída"
            else
                print_error "Falha na migração!"
                return 1
            fi
        else
            print_warning "Migração pulada pelo usuário (continuando deploy sem migração)"
        fi
    else
        print_error "Falha no dry-run da migração!"
        return 1
    fi
}

# Parar containers
stop_containers() {
    print_step "Parando containers..."

    if docker compose down; then
        print_success "Containers parados"
    else
        print_warning "Nenhum container estava rodando ou erro ao parar"
    fi
}

# Rebuild e iniciar containers
start_containers() {
    print_step "Rebuilding e iniciando containers..."

    if docker compose up -d --build; then
        print_success "Containers iniciados"
    else
        print_error "Falha ao iniciar containers!"
        return 1
    fi
}

# Verificar saúde do container
check_health() {
    print_step "Verificando saúde do container..."

    sleep 5  # Aguardar container inicializar

    # Verificar se container está rodando
    if docker compose ps | grep -q "Up"; then
        print_success "Container está rodando"
    else
        print_error "Container não está rodando!"
        print_warning "Verifique os logs: docker compose logs"
        return 1
    fi

    # Mostrar últimas linhas do log
    print_step "Últimas linhas do log:"
    docker compose logs --tail=20
}

# Verificar inicialização dos cronjobs
check_cronjobs() {
    print_step "Verificando inicialização dos cronjobs..."

    if docker compose logs | grep -E "STARTUP.*Iniciando agendamento" > /dev/null; then
        print_success "Cronjob principal inicializado"
    else
        print_warning "Não foi possível confirmar inicialização do cronjob principal"
    fi

    if docker compose logs | grep -E "STARTUP.*Inicializando cronjob de boas-vindas" > /dev/null; then
        print_success "Cronjob de boas-vindas inicializado"
    else
        print_warning "Não foi possível confirmar inicialização do cronjob de boas-vindas"
    fi
}

# Mostrar próximos passos
show_next_steps() {
    echo -e "\n${GREEN}========================================${NC}"
    echo -e "${GREEN}Deploy concluído com sucesso! 🚀${NC}"
    echo -e "${GREEN}========================================${NC}\n"

    echo "📝 Próximos passos:"
    echo ""
    echo "1. Verificar logs completos:"
    echo "   docker compose logs -f"
    echo ""
    echo "2. Testar interface de templates:"
    echo "   Acessar: http://seu-servidor/mensagem"
    echo ""
    echo "3. Testar botão 'Enviar Mensagem':"
    echo "   Acessar: http://seu-servidor/envios"
    echo ""
    echo "4. Monitorar cronjob de boas-vindas:"
    echo "   docker compose logs -f | grep WELCOME"
    echo ""
    echo "5. Configurar backup semanal (se ainda não configurado):"
    echo "   crontab -e"
    echo "   Adicionar: 0 3 * * 0 ${APP_DIR}/backup-cron-weekly.sh >> ${BACKUP_DIR}/backup.log 2>&1"
    echo ""
}

# Função principal
main() {
    echo -e "${BLUE}"
    echo "========================================="
    echo "  Deploy Automatizado - Melhor Envio    "
    echo "========================================="
    echo -e "${NC}"

    # Confirmação inicial
    if ! confirm "Deseja iniciar o deploy?"; then
        print_warning "Deploy cancelado pelo usuário"
        trap - EXIT  # Remover trap antes de sair normalmente
        exit 0
    fi

    # Executar passos (com verificação de erro em cada passo)
    check_directory || return 1
    backup_database || return 1  # Já para o container
    update_code || return 1
    run_migration || return 1    # Roda com container parado (banco sem lock)
    start_containers || return 1 # Rebuild e sobe container
    check_health || return 1
    check_cronjobs || return 1
    show_next_steps

    # Deploy concluído com sucesso, remover trap de erro
    trap - EXIT
    return 0
}

# Executar script
main "$@"
