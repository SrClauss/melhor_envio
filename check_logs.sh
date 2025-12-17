#!/bin/bash

# Script de diagnóstico rápido para sistema de logs
# Uso: ./check_logs.sh

echo "======================================"
echo "🔍 Diagnóstico do Sistema de Logs"
echo "======================================"
echo ""

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Verificar se logs existem
echo "1. Verificando diretório de logs..."
if [ -d "/opt/melhor_envio/logs" ]; then
    echo -e "${GREEN}✓${NC} Diretório de logs existe"
    ls -lh /opt/melhor_envio/logs/
else
    echo -e "${RED}✗${NC} Diretório de logs não encontrado"
    echo "   Criando diretório..."
    mkdir -p /opt/melhor_envio/logs
fi
echo ""

# Verificar tamanho dos logs
echo "2. Tamanho dos arquivos de log:"
if [ -d "/opt/melhor_envio/logs" ]; then
    du -sh /opt/melhor_envio/logs/* 2>/dev/null || echo "   Nenhum arquivo de log encontrado"
fi
echo ""

# Verificar últimas linhas do log principal
echo "3. Últimas 10 linhas do log principal:"
if [ -f "/opt/melhor_envio/logs/melhor_envio.log" ]; then
    tail -n 10 /opt/melhor_envio/logs/melhor_envio.log
else
    echo -e "${YELLOW}⚠${NC} Arquivo melhor_envio.log não encontrado"
fi
echo ""

# Contar erros recentes
echo "4. Contagem de erros nas últimas 24h:"
if [ -f "/opt/melhor_envio/logs/errors.log" ]; then
    ERROR_COUNT=$(grep "ERROR" /opt/melhor_envio/logs/errors.log 2>/dev/null | wc -l)
    if [ $ERROR_COUNT -gt 0 ]; then
        echo -e "${YELLOW}⚠${NC} $ERROR_COUNT erros encontrados"
        echo "   Últimos 5 erros:"
        grep "ERROR" /opt/melhor_envio/logs/errors.log | tail -n 5
    else
        echo -e "${GREEN}✓${NC} Nenhum erro recente"
    fi
else
    echo -e "${YELLOW}⚠${NC} Arquivo errors.log não encontrado"
fi
echo ""

# Verificar status dos cronjobs
echo "5. Status dos cronjobs:"
if command -v curl &> /dev/null; then
    HEALTH=$(curl -s http://localhost/api/health/cronjobs 2>/dev/null)
    if [ $? -eq 0 ]; then
        echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"
    else
        echo -e "${RED}✗${NC} Não foi possível conectar à API de health"
    fi
else
    echo -e "${YELLOW}⚠${NC} curl não instalado, pulando verificação de API"
fi
echo ""

# Verificar últimas execuções do cronjob principal
echo "6. Últimas execuções do cronjob de rastreamento:"
if [ -f "/opt/melhor_envio/logs/cronjob_monitor_shipments.log" ]; then
    echo "   Últimas 3 execuções (resumos):"
    grep "RESUMO" /opt/melhor_envio/logs/cronjob_monitor_shipments.log | tail -n 3
else
    echo -e "${YELLOW}⚠${NC} Log do cronjob não encontrado (pode não ter executado ainda)"
fi
echo ""

# Verificar rate limits
echo "7. Verificando rate limits (429):"
if [ -f "/opt/melhor_envio/logs/cronjob_monitor_shipments.log" ]; then
    RATE_LIMIT_COUNT=$(grep "RATE LIMIT" /opt/melhor_envio/logs/cronjob_monitor_shipments.log 2>/dev/null | wc -l)
    if [ $RATE_LIMIT_COUNT -gt 0 ]; then
        echo -e "${YELLOW}⚠${NC} $RATE_LIMIT_COUNT ocorrências de rate limit"
        echo "   Última ocorrência:"
        grep "RATE LIMIT" /opt/melhor_envio/logs/cronjob_monitor_shipments.log | tail -n 1
    else
        echo -e "${GREEN}✓${NC} Nenhum rate limit detectado"
    fi
else
    echo -e "${YELLOW}⚠${NC} Log do cronjob não encontrado"
fi
echo ""

# Resumo
echo "======================================"
echo "📊 Resumo"
echo "======================================"

# Verificar se há problemas críticos
CRITICAL_ISSUES=0

if [ ! -d "/opt/melhor_envio/logs" ]; then
    CRITICAL_ISSUES=$((CRITICAL_ISSUES + 1))
fi

if [ -f "/opt/melhor_envio/logs/errors.log" ]; then
    RECENT_ERRORS=$(grep "ERROR" /opt/melhor_envio/logs/errors.log 2>/dev/null | tail -n 50 | wc -l)
    if [ $RECENT_ERRORS -gt 10 ]; then
        CRITICAL_ISSUES=$((CRITICAL_ISSUES + 1))
    fi
fi

if [ $CRITICAL_ISSUES -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Sistema de logs funcionando normalmente"
    echo ""
    echo "Para visualizar logs em tempo real:"
    echo "  tail -f /opt/melhor_envio/logs/cronjob_monitor_shipments.log"
    echo ""
    echo "Para visualizar pelo navegador:"
    echo "  http://seu-servidor/logs"
else
    echo -e "${RED}✗${NC} Problemas detectados!"
    echo "Consulte o guia de troubleshooting: LOGS_GUIDE.md"
fi

echo ""
echo "======================================"
