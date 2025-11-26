#!/bin/bash

#######################################
# Script de Restauração/Recovery
# Melhor Envio - Sistema de Rastreamento
#
# Uso:
#  ./restore.sh                 # Modo interativo
#  ./restore.sh quick           # Restaura último backup e inicia
#######################################

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Diretórios
APP_DIR="/opt/melhor_envio"
BACKUP_DIR="${APP_DIR}/backups"
DB_PATH="${APP_DIR}/database.db"

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

# Listar backups disponíveis
list_backups() {
    print_step "Backups disponíveis:"
    echo ""

    if [ ! -d "${BACKUP_DIR}" ] || [ -z "$(ls -A ${BACKUP_DIR}/database_* 2>/dev/null)" ]; then
        print_error "Nenhum backup encontrado em ${BACKUP_DIR}"
        return 1
    fi

    local i=1
    declare -g -A BACKUP_MAP

    while IFS= read -r backup; do
        local backup_name=$(basename "$backup")
        local backup_size=$(du -sh "$backup" 2>/dev/null | cut -f1)
        local backup_date=$(echo "$backup_name" | sed 's/database_\([0-9]\{8\}\)_\([0-9]\{6\}\).*/\1 \2/' | sed 's/\([0-9]\{4\}\)\([0-9]\{2\}\)\([0-9]\{2\}\) \([0-9]\{2\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)/\3\/\2\/\1 \4:\5:\6/')

        BACKUP_MAP[$i]="$backup"
        echo "  [$i] $backup_name"
        echo "      Data: $backup_date | Tamanho: $backup_size"
        echo ""
        ((i++))
    done < <(ls -t ${BACKUP_DIR}/database_* 2>/dev/null)

    return 0
}

# Restaurar backup
restore_backup() {
    local backup_path=$1

    if [ ! -d "$backup_path" ]; then
        print_error "Backup não encontrado: $backup_path"
        return 1
    fi

    print_step "Parando container..."
    cd "${APP_DIR}"
    docker compose down
    sleep 2

    print_step "Removendo banco atual..."
    if [ -d "${DB_PATH}" ]; then
        rm -rf "${DB_PATH}"
        print_success "Banco atual removido"
    fi

    print_step "Restaurando backup..."
    if cp -r "$backup_path" "${DB_PATH}"; then
        print_success "Backup restaurado: $(basename $backup_path)"
    else
        print_error "Falha ao restaurar backup!"
        return 1
    fi

    print_step "Iniciando container..."
    if docker compose up -d; then
        sleep 5
        print_success "Container iniciado"

        # Verificar saúde
        if docker compose ps | grep -q "Up"; then
            print_success "✅ Sistema restaurado e online!"
            echo ""
            echo "📊 Status do container:"
            docker compose ps
            return 0
        else
            print_error "Container não iniciou corretamente"
            echo "Verifique os logs: docker compose logs"
            return 1
        fi
    else
        print_error "Falha ao iniciar container!"
        return 1
    fi
}

# Modo rápido: restaura último backup e inicia
quick_restore() {
    echo -e "${BLUE}"
    echo "========================================="
    echo "  Restauração Rápida - Último Backup    "
    echo "========================================="
    echo -e "${NC}"

    # Encontrar último backup
    local latest_backup=$(ls -t ${BACKUP_DIR}/database_* 2>/dev/null | head -1)

    if [ -z "$latest_backup" ]; then
        print_error "Nenhum backup encontrado!"
        exit 1
    fi

    echo "Último backup encontrado:"
    echo "  $(basename $latest_backup)"
    echo ""

    if confirm "Deseja restaurar este backup?"; then
        restore_backup "$latest_backup"
    else
        print_warning "Restauração cancelada"
        exit 0
    fi
}

# Modo interativo
interactive_restore() {
    echo -e "${BLUE}"
    echo "========================================="
    echo "  Restauração Interativa                "
    echo "========================================="
    echo -e "${NC}"

    # Listar backups
    if ! list_backups; then
        exit 1
    fi

    # Escolher backup
    echo ""
    read -p "Escolha o número do backup para restaurar (ou 0 para cancelar): " choice

    if [ "$choice" == "0" ]; then
        print_warning "Restauração cancelada"
        exit 0
    fi

    if [ -z "${BACKUP_MAP[$choice]}" ]; then
        print_error "Opção inválida!"
        exit 1
    fi

    local selected_backup="${BACKUP_MAP[$choice]}"
    echo ""
    echo "Backup selecionado: $(basename $selected_backup)"
    echo ""

    print_warning "⚠️  ATENÇÃO: Esta operação irá:"
    print_warning "   1. Parar o container"
    print_warning "   2. APAGAR o banco de dados atual"
    print_warning "   3. Restaurar o backup selecionado"
    print_warning "   4. Reiniciar o container"
    echo ""

    if confirm "Tem CERTEZA que deseja continuar?"; then
        restore_backup "$selected_backup"
    else
        print_warning "Restauração cancelada"
        exit 0
    fi
}

# Apenas reiniciar container (sem restaurar backup)
just_restart() {
    echo -e "${BLUE}"
    echo "========================================="
    echo "  Reiniciar Container                    "
    echo "========================================="
    echo -e "${NC}"

    print_step "Parando container..."
    cd "${APP_DIR}"
    docker compose down
    sleep 2

    print_step "Iniciando container..."
    if docker compose up -d; then
        sleep 5
        print_success "Container iniciado"

        # Verificar saúde
        if docker compose ps | grep -q "Up"; then
            print_success "✅ Container online!"
            echo ""
            echo "📊 Status:"
            docker compose ps
        else
            print_error "Container não iniciou corretamente"
            echo "Verifique os logs: docker compose logs"
            exit 1
        fi
    else
        print_error "Falha ao iniciar container!"
        exit 1
    fi
}

# Menu principal
main_menu() {
    echo -e "${BLUE}"
    echo "========================================="
    echo "  Recuperação do Sistema                "
    echo "  Melhor Envio                          "
    echo "========================================="
    echo -e "${NC}"
    echo ""
    echo "Escolha uma opção:"
    echo ""
    echo "  [1] Restaurar backup (interativo)"
    echo "  [2] Restaurar último backup (rápido)"
    echo "  [3] Apenas reiniciar container"
    echo "  [0] Sair"
    echo ""
    read -p "Opção: " option

    case $option in
        1)
            interactive_restore
            ;;
        2)
            quick_restore
            ;;
        3)
            just_restart
            ;;
        0)
            print_warning "Operação cancelada"
            exit 0
            ;;
        *)
            print_error "Opção inválida!"
            exit 1
            ;;
    esac
}

# Executar
if [ "$1" == "quick" ]; then
    quick_restore
elif [ "$1" == "restart" ]; then
    just_restart
elif [ -z "$1" ]; then
    main_menu
else
    echo "Uso:"
    echo "  ./restore.sh           # Menu interativo"
    echo "  ./restore.sh quick     # Restaurar último backup"
    echo "  ./restore.sh restart   # Apenas reiniciar container"
    exit 1
fi
