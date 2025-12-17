# 📦 Sistema de Rastreamento - Melhor Envio

Sistema automatizado para rastreamento de encomendas com notificações via WhatsApp.

## 🆕 Sistema de Logs e Diagnóstico

### Acesso Rápido

- **Interface Web**: `http://seu-servidor/logs`
- **API de Health**: `http://seu-servidor/api/health/cronjobs`
- **Guia Completo**: [LOGS_GUIDE.md](LOGS_GUIDE.md)

### Diagnóstico Rápido

```bash
# Executar script de diagnóstico
./check_logs.sh

# Ver logs em tempo real
docker compose logs -f

# Ver logs do cronjob principal
tail -f /opt/melhor_envio/logs/cronjob_monitor_shipments.log

# Ver apenas erros
tail -f /opt/melhor_envio/logs/errors.log
```

## 📊 Arquivos de Log Disponíveis

- `melhor_envio.log` - Log geral do sistema
- `errors.log` - Apenas erros (ERROR e CRITICAL)
- `cronjob_monitor_shipments.log` - Log do cronjob principal de rastreamento
- `cronjob_welcome_shipments.log` - Log do cronjob de boas-vindas

## 🔍 Troubleshooting

### Cronjobs não estão executando?

1. Verificar status do scheduler:
```bash
curl http://localhost/api/health/cronjobs
```

2. Verificar logs de inicialização:
```bash
docker compose logs | grep "STARTUP"
```

3. Reiniciar se necessário:
```bash
docker compose restart
```

### Mensagens não estão sendo enviadas?

1. Verificar logs do cronjob:
```bash
grep "NOTIFICAÇÃO\|WHATSAPP" /opt/melhor_envio/logs/cronjob_monitor_shipments.log | tail -n 20
```

2. Verificar token Umbler no `.env`:
```bash
grep "TOKEN_UMBLER" .env
```

3. Testar envio manual pelo painel

### Muitos erros de Rate Limit (429)?

1. Verificar ocorrências:
```bash
grep "RATE LIMIT" /opt/melhor_envio/logs/cronjob_monitor_shipments.log | wc -l
```

2. Aumentar throttle no `.env`:
```env
WEBHOOKS_THROTTLE=1.5  # Default: 0.5
```

## 📖 Documentação Completa

Para guia detalhado de troubleshooting e interpretação de logs, consulte:

👉 **[LOGS_GUIDE.md](LOGS_GUIDE.md)**

## 🚀 Deploy

```bash
# Subir aplicação
docker compose up -d

# Verificar logs
docker compose logs -f

# Executar diagnóstico
./check_logs.sh
```

## 🛠️ Configuração

### Variáveis de Ambiente (`.env`)

```env
# Logging
LOG_LEVEL=INFO

# API Umbler (WhatsApp)
TOKEN_UMBLER=seu_token_aqui
UMBLER_FROM_PHONE=+5538999978213
UMBLER_ORG_ID=aORCMR51FFkJKvJe

# Throttling
WEBHOOKS_THROTTLE=0.5
WEBHOOKS_MAX_RETRIES=3
RATE_LIMIT_MAX_RETRIES=10

# Cronjob de Boas-vindas
WELCOME_INTERVAL_MINUTES=10

# Monitoramento
MONITOR_START_HOUR=06:00  # Horário de Brasília
MONITOR_END_HOUR=18:00    # Horário de Brasília
```

## 📁 Estrutura de Diretórios

```
/opt/melhor_envio/
├── database.db           # Banco de dados RocksDB
├── logs/                 # 📊 Logs do sistema
│   ├── melhor_envio.log
│   ├── errors.log
│   ├── cronjob_monitor_shipments.log
│   └── cronjob_welcome_shipments.log
└── backups/              # Backups do banco de dados
```

## 🔐 Acesso ao Sistema

### Credenciais Padrão

- **Usuário**: `admin`
- **Senha**: 4 espaços (`    `)

⚠️ **Importante**: Altere a senha padrão após o primeiro acesso!

## 🎯 Funcionalidades

### Cronjobs Automáticos

1. **Monitor de Rastreamento** (`monitor_shipments`)
   - Consulta API Melhor Envio a cada X minutos (configurável)
   - Extrai rastreamento via API GraphQL
   - Envia notificações WhatsApp quando há atualização
   - Gerencia rate limits automaticamente

2. **Cronjob de Boas-Vindas** (`welcome_shipments`)
   - Executa a cada 10 minutos (configurável)
   - Envia mensagem inicial para novas etiquetas
   - Tenta usar código da transportadora primeiro, depois código próprio

### Interface Web

- `/dashboard` - Painel principal
- `/envios` - Lista de envios ativos
- `/mensagem` - Edição de templates de mensagens
- `/logs` - 📊 **Visualização de logs** (NOVO)
- `/tokens` - Gerenciamento de tokens
- `/usuarios` - Gerenciamento de usuários

## 🔄 Atualizações e Manutenção

### Atualizar código

```bash
git pull
docker compose build
docker compose up -d
```

### Backup do banco de dados

```bash
./backup-db.sh
```

### Limpar logs antigos

```bash
# Logs com mais de 30 dias
find /opt/melhor_envio/logs -name "*.log.*" -mtime +30 -delete
```

## ⚙️ Recursos Avançados

### Monitoramento em Tempo Real

```bash
# Seguir execução do cronjob
tail -f /opt/melhor_envio/logs/cronjob_monitor_shipments.log

# Filtrar apenas notificações enviadas
grep "✅ Notificação enviada" /opt/melhor_envio/logs/cronjob_monitor_shipments.log

# Ver estatísticas de execução
grep "RESUMO" /opt/melhor_envio/logs/cronjob_monitor_shipments.log | tail -n 10
```

### API de Saúde

```bash
# Status dos cronjobs
curl http://localhost/api/health/cronjobs | jq

# Ler log específico via API
curl "http://localhost/api/logs/melhor_envio.log?lines=50&level=ERROR" \
  -H "Cookie: session=..."
```

## 📞 Suporte

Se encontrar problemas:

1. Execute o diagnóstico: `./check_logs.sh`
2. Consulte [LOGS_GUIDE.md](LOGS_GUIDE.md)
3. Verifique logs em `/opt/melhor_envio/logs/`
4. Revise configurações no `.env`

## 📝 Changelog

### v2.1.0 - Sistema de Logs
- ✨ Adicionado sistema centralizado de logging
- ✨ Interface web para visualização de logs
- ✨ API de health para monitoramento de cronjobs
- ✨ Logs detalhados com rotação automática
- ✨ Script de diagnóstico automático
- 📚 Guia completo de troubleshooting

### v2.0.0 - Cronjobs e Boas-vindas
- ✨ Sistema de cronjobs com APScheduler
- ✨ Mensagem de boas-vindas automática
- ✨ Retry automático para rate limits
- ✨ Suporte a múltiplos códigos de rastreio

## 📄 Licença

Desenvolvido por SrClauss
