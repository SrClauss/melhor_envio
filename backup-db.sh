#!/bin/bash

# Script de backup manual do banco de dados RocksDB
# Uso: ./backup-db.sh

BACKUP_DIR="/opt/melhor_envio/backups"
DB_PATH="/opt/melhor_envio/database.db"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/database_${TIMESTAMP}.db"

# Criar diretório de backup se não existir
mkdir -p "${BACKUP_DIR}"

# Verificar se o banco existe
if [ ! -d "${DB_PATH}" ]; then
    echo "❌ ERRO: Banco de dados não encontrado em ${DB_PATH}"
    exit 1
fi

# Fazer backup
echo "📦 Iniciando backup do banco de dados..."
echo "   Origem: ${DB_PATH}"
echo "   Destino: ${BACKUP_FILE}"

cp -r "${DB_PATH}" "${BACKUP_FILE}"

if [ $? -eq 0 ]; then
    echo "✅ Backup criado com sucesso!"
    echo "   Arquivo: $(basename ${BACKUP_FILE})"

    # Mostrar tamanho do backup
    SIZE=$(du -sh "${BACKUP_FILE}" | cut -f1)
    echo "   Tamanho: ${SIZE}"

    # Listar backups existentes
    echo ""
    echo "📋 Backups disponíveis:"
    ls -lh "${BACKUP_DIR}" | grep database_ | awk '{print "   " $9 " (" $5 ")"}'

    # Remover backups antigos (manter apenas últimos 10)
    echo ""
    echo "🧹 Limpando backups antigos (mantendo últimos 10)..."
    cd "${BACKUP_DIR}"
    ls -t | grep database_ | tail -n +11 | xargs -r rm -rf
    echo "✅ Limpeza concluída"
else
    echo "❌ ERRO ao criar backup!"
    exit 1
fi
