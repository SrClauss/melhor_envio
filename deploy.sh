#!/bin/bash

#######################################
# Script de Deploy Automatizado
# Melhor Envio - Sistema de Rastreamento
#######################################

set -e  # Para na primeira falha

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Diretório base (ajustar conforme necessário)
APP_DIR="/opt/melhor_envio"
BACKUP_DIR="${APP_DIR}/backups"
BRANCH="claude/understand-co-01YQqCTdiPnoqWdtxeSzuQ2m"

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
        exit 1
    fi

    print_success "Diretório OK"
}

# Fazer backup do banco de dados
backup_database() {
    print_step "Fazendo backup do banco de dados..."

    if [ ! -f "./backup-db.sh" ]; then
        print_error "Script backup-db.sh não encontrado!"
        exit 1
    fi

    chmod +x ./backup-db.sh

    if ./backup-db.sh; then
        print_success "Backup realizado com sucesso"
    else
        print_error "Falha no backup!"
        exit 1
    fi
}

# Atualizar código do repositório
update_code() {
    print_step "Atualizando código do repositório..."

    # Verificar se há mudanças não commitadas
    if [ -n "$(git status --porcelain)" ]; then
        print_warning "Existem mudanças não commitadas no diretório"
        if ! confirm "Deseja continuar mesmo assim?"; then
            exit 1
        fi
    fi

    # Fazer pull
    print_step "Executando git pull..."
    if git pull origin "${BRANCH}"; then
        print_success "Código atualizado"
    else
        print_error "Falha ao fazer git pull!"
        exit 1
    fi
}

# Executar migração de shipments existentes
run_migration() {
    print_step "Migração de shipments existentes..."

    if [ ! -f "./migrate_existing_shipments.py" ]; then
        print_warning "Script de migração não encontrado, pulando..."
        return 0
    fi

    # Verificar se o container está rodando
    if ! docker-compose ps | grep -q "Up"; then
        print_warning "Container não está rodando. Iniciando temporariamente para migração..."
        if ! docker-compose up -d; then
            print_error "Falha ao iniciar container para migração!"
            exit 1
        fi
        sleep 5  # Aguardar container inicializar
    fi

    # Dry-run primeiro (executando DENTRO do container)
    print_step "Executando dry-run da migração (dentro do container)..."
    if docker-compose exec -T web python3 migrate_existing_shipments.py --dry-run; then
        print_success "Dry-run concluído"

        if confirm "Deseja executar a migração de verdade?"; then
            print_step "Executando migração (dentro do container)..."
            if docker-compose exec -T web python3 migrate_existing_shipments.py; then
                print_success "Migração concluída"
            else
                print_error "Falha na migração!"
                exit 1
            fi
        else
            print_warning "Migração pulada pelo usuário"
        fi
    else
        print_error "Falha no dry-run da migração!"
        exit 1
    fi
}

# Parar containers
stop_containers() {
    print_step "Parando containers..."

    if docker-compose down; then
        print_success "Containers parados"
    else
        print_warning "Nenhum container estava rodando ou erro ao parar"
    fi
}

# Rebuild e iniciar containers
start_containers() {
    print_step "Rebuilding e iniciando containers..."

    if docker-compose up -d --build; then
        print_success "Containers iniciados"
    else
        print_error "Falha ao iniciar containers!"
        exit 1
    fi
}

# Verificar saúde do container
check_health() {
    print_step "Verificando saúde do container..."

    sleep 5  # Aguardar container inicializar

    # Verificar se container está rodando
    if docker-compose ps | grep -q "Up"; then
        print_success "Container está rodando"
    else
        print_error "Container não está rodando!"
        print_warning "Verifique os logs: docker-compose logs"
        exit 1
    fi

    # Mostrar últimas linhas do log
    print_step "Últimas linhas do log:"
    docker-compose logs --tail=20
}

# Verificar inicialização dos cronjobs
check_cronjobs() {
    print_step "Verificando inicialização dos cronjobs..."

    if docker-compose logs | grep -E "STARTUP.*Iniciando agendamento" > /dev/null; then
        print_success "Cronjob principal inicializado"
    else
        print_warning "Não foi possível confirmar inicialização do cronjob principal"
    fi

    if docker-compose logs | grep -E "STARTUP.*Inicializando cronjob de boas-vindas" > /dev/null; then
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
    echo "   docker-compose logs -f"
    echo ""
    echo "2. Testar interface de templates:"
    echo "   Acessar: http://seu-servidor/mensagem"
    echo ""
    echo "3. Testar botão 'Enviar Mensagem':"
    echo "   Acessar: http://seu-servidor/envios"
    echo ""
    echo "4. Monitorar cronjob de boas-vindas:"
    echo "   docker-compose logs -f | grep WELCOME"
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
        exit 0
    fi

    # Executar passos
    check_directory
    backup_database
    update_code
    run_migration
    stop_containers
    start_containers
    check_health
    check_cronjobs
    show_next_steps
}

# Executar script
main "$@"
