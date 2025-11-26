#!/bin/bash

# Script de backup automático semanal do banco de dados RocksDB
# Este script deve ser adicionado ao crontab do servidor (não do container)
#
# Para instalar o cron semanal (todo domingo às 03:00):
# crontab -e
# Adicione a linha:
# 0 3 * * 0 /opt/melhor_envio/backup-cron-weekly.sh >> /opt/melhor_envio/backups/backup.log 2>&1

BACKUP_DIR="/opt/melhor_envio/backups"
DB_PATH="/opt/melhor_envio/database.db"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/database_${TIMESTAMP}.db"
LOG_FILE="${BACKUP_DIR}/backup.log"

# Criar diretório de backup se não existir
mkdir -p "${BACKUP_DIR}"

# Logging
echo "========================================" | tee -a "${LOG_FILE}"
echo "🕐 Backup automático iniciado: $(date)" | tee -a "${LOG_FILE}"
echo "========================================" | tee -a "${LOG_FILE}"

# Verificar se o banco existe
if [ ! -d "${DB_PATH}" ]; then
    echo "❌ ERRO: Banco de dados não encontrado em ${DB_PATH}" | tee -a "${LOG_FILE}"
    exit 1
fi

# Parar container para liberar lock do banco de dados
echo "🛑 Parando container para liberar lock do banco de dados..." | tee -a "${LOG_FILE}"
cd /opt/melhor_envio
docker compose down
sleep 2

# Fazer backup
echo "📦 Criando backup..." | tee -a "${LOG_FILE}"
echo "   Origem: ${DB_PATH}" | tee -a "${LOG_FILE}"
echo "   Destino: ${BACKUP_FILE}" | tee -a "${LOG_FILE}"

cp -r "${DB_PATH}" "${BACKUP_FILE}"

if [ $? -eq 0 ]; then
    SIZE=$(du -sh "${BACKUP_FILE}" | cut -f1)
    echo "✅ Backup criado com sucesso!" | tee -a "${LOG_FILE}"
    echo "   Arquivo: $(basename ${BACKUP_FILE})" | tee -a "${LOG_FILE}"
    echo "   Tamanho: ${SIZE}" | tee -a "${LOG_FILE}"

    # Remover backups com mais de 60 dias
    echo "🧹 Removendo backups com mais de 60 dias..." | tee -a "${LOG_FILE}"
    find "${BACKUP_DIR}" -name "database_*.db" -type d -mtime +60 -exec rm -rf {} \; 2>/dev/null

    # Contar backups restantes
    BACKUP_COUNT=$(ls -1 "${BACKUP_DIR}" | grep database_ | wc -l)
    echo "📊 Total de backups: ${BACKUP_COUNT}" | tee -a "${LOG_FILE}"

    echo "✅ Backup semanal concluído com sucesso!" | tee -a "${LOG_FILE}"

    # Reiniciar container
    echo "🚀 Reiniciando container..." | tee -a "${LOG_FILE}"
    cd /opt/melhor_envio
    docker compose up -d
    echo "✅ Container reiniciado" | tee -a "${LOG_FILE}"
else
    echo "❌ ERRO ao criar backup!" | tee -a "${LOG_FILE}"
    # Tentar reiniciar container mesmo em caso de erro
    echo "🚀 Tentando reiniciar container..." | tee -a "${LOG_FILE}"
    cd /opt/melhor_envio
    docker compose up -d
    exit 1
fi

echo "========================================" | tee -a "${LOG_FILE}"
echo "" | tee -a "${LOG_FILE}"
