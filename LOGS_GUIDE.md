# 📊 Sistema de Logs - Guia de Uso e Troubleshooting

## Visão Geral

O sistema de logs foi implementado para facilitar o diagnóstico de problemas nos cronjobs de rastreamento automático. Os logs capturam informações detalhadas sobre todas as operações do sistema, incluindo:

- ✅ Consultas à API do Melhor Envio
- ✅ Rastreamento via API GraphQL
- ✅ Envio de mensagens WhatsApp
- ✅ Execução dos cronjobs (monitor_shipments e welcome_shipments)
- ✅ Erros e exceções com stack traces completos

## 📁 Arquivos de Log

Os logs são armazenados em `/opt/melhor_envio/logs/` e incluem:

### Logs Principais

1. **melhor_envio.log**
   - Log geral do sistema
   - Contém todas as mensagens de INFO e acima
   - Rotacionado a cada 10 MB (mantém 5 backups)

2. **errors.log**
   - Apenas erros (ERROR e CRITICAL)
   - Útil para diagnóstico rápido de falhas
   - Rotacionado a cada 10 MB (mantém 5 backups)

### Logs de Cronjobs

3. **cronjob_monitor_shipments.log**
   - Logs específicos do cronjob principal de rastreamento
   - Inclui DEBUG, INFO, WARNING e ERROR
   - Rastreia cada shipment processado

4. **cronjob_welcome_shipments.log**
   - Logs do cronjob de boas-vindas
   - Mensagens enviadas para novos shipments

## 🖥️ Acessando os Logs pelo Painel Web

### Método 1: Interface Web (Recomendado)

1. Acesse o painel em: `http://seu-servidor/logs`
2. Faça login com suas credenciais
3. Selecione o arquivo de log desejado
4. Use os filtros:
   - **Filtro de nível**: ERROR, WARNING, INFO, DEBUG
   - **Número de linhas**: Quantas linhas exibir (padrão: 200)
5. Clique em "🔄 Atualizar" para recarregar

### Método 2: API REST

```bash
# Obter últimas 100 linhas do log geral
curl -X GET "http://seu-servidor/api/logs/melhor_envio.log?lines=100" \
  -H "Cookie: session=seu_cookie"

# Filtrar apenas ERRORs
curl -X GET "http://seu-servidor/api/logs/melhor_envio.log?lines=100&level=ERROR" \
  -H "Cookie: session=seu_cookie"

# Verificar saúde dos cronjobs
curl -X GET "http://seu-servidor/api/health/cronjobs" \
  -H "Cookie: session=seu_cookie"
```

### Método 3: SSH/Docker (Acesso Direto)

```bash
# Ver logs em tempo real
docker compose logs -f fastapi_app

# Ver logs dos cronjobs
tail -f /opt/melhor_envio/logs/cronjob_monitor_shipments.log

# Buscar por erros
grep "ERROR" /opt/melhor_envio/logs/melhor_envio.log | tail -n 50

# Buscar por shipment específico
grep "shipment_123456" /opt/melhor_envio/logs/cronjob_monitor_shipments.log
```

## 🔍 Formato dos Logs

Cada linha de log segue o formato:

```
2024-01-15 14:23:45 | INFO     | app.webhooks         | consultar_shipments      | Total de shipments carregados: 42 em 2 página(s)
[  timestamp   ] | [nivel  ] | [   módulo        ] | [      função         ] | [           mensagem                              ]
```

### Níveis de Log

- **DEBUG**: Informações detalhadas para diagnóstico
- **INFO**: Operações normais do sistema
- **WARNING**: Avisos que não impedem a operação
- **ERROR**: Erros que causaram falha em uma operação
- **CRITICAL**: Erros críticos que podem parar o sistema

## 🐛 Troubleshooting - Problemas Comuns

### Problema 1: Cronjobs não estão executando

**Sintomas:**
- Nenhuma notificação sendo enviada
- Logs não aparecem em `cronjob_monitor_shipments.log`

**Diagnóstico:**

1. Verificar se o scheduler está rodando:
```bash
curl http://localhost/api/health/cronjobs
```

Deve retornar:
```json
{
  "scheduler_running": true,
  "jobs": [
    {
      "id": "monitor_shipments",
      "next_run": "2024-01-15T17:30:00"
    }
  ]
}
```

2. Verificar logs de inicialização:
```bash
docker compose logs | grep "STARTUP"
```

Deve mostrar:
```
[STARTUP] Iniciando agendamento do monitoramento com intervalo de 30 minutos...
[STARTUP] Inicializando cronjob de boas-vindas (novos shipments)...
```

**Solução:**
- Se scheduler não estiver rodando, reiniciar container:
```bash
docker compose restart
```

### Problema 2: Rate Limit (429) da API

**Sintomas:**
- Logs mostram: `[RATE LIMIT] Pausando por 11.34s devido a 429`
- Muitos shipments na fila de retry

**Diagnóstico:**
```bash
grep "RATE LIMIT" /opt/melhor_envio/logs/cronjob_monitor_shipments.log | tail -n 20
```

**Solução:**
- Sistema já trata automaticamente com retries
- Se persistir, aumentar intervalo entre consultas em `.env`:
```env
WEBHOOKS_THROTTLE=1.5  # Aumentar de 0.5 para 1.5 segundos
```

### Problema 3: Erro ao extrair rastreio

**Sintomas:**
- Logs mostram: `Erro ao extrair rastreio: Erro de rede`
- `PARCEL_NOT_FOUND` frequente

**Diagnóstico:**
```bash
grep "Erro ao extrair rastreio" /opt/melhor_envio/logs/cronjob_monitor_shipments.log | tail -n 20
```

**Possíveis Causas:**

1. **PARCEL_NOT_FOUND** - Normal para etiquetas recém-criadas
   - Solução: Aguardar algumas horas até a transportadora indexar

2. **Timeout** - Rede lenta ou API instável
   - Verificar conectividade:
   ```bash
   curl -I https://api.melhorrastreio.com.br/graphql
   ```

3. **Erro HTTP 401/403** - Token inválido
   - Verificar token no banco:
   ```bash
   docker exec -it melhor_envio_fastapi_app_1 python3 -c "import rocksdbpy; db=rocksdbpy.open('database.db', rocksdbpy.Option()); print(db.get(b'token:melhor_envio'))"
   ```

### Problema 4: WhatsApp não está enviando

**Sintomas:**
- Logs mostram: `❌ Falha ao enviar WhatsApp`
- Rastreio funciona mas mensagens não chegam

**Diagnóstico:**
```bash
grep "Falha ao enviar WhatsApp" /opt/melhor_envio/logs/cronjob_monitor_shipments.log
```

**Verificar:**

1. Token Umbler configurado:
```bash
grep "TOKEN_UMBLER" .env
```

2. Logs detalhados do erro:
```bash
grep -A 5 "Falha ao enviar WhatsApp" /opt/melhor_envio/logs/melhor_envio.log
```

**Solução:**
- Verificar credenciais da API Umbler no `.env`
- Testar envio manual pelo painel

### Problema 5: Cronjob executa mas não processa shipments

**Sintomas:**
- Logs mostram: `Processados: 0 shipments`
- `HTTP 401` ao consultar API Melhor Envio

**Diagnóstico:**
```bash
grep "Processados:" /opt/melhor_envio/logs/cronjob_monitor_shipments.log | tail -n 5
```

**Verificar token:**
```bash
# Entrar no container
docker exec -it melhor_envio_fastapi_app_1 /bin/bash

# Verificar token no banco
python3 << EOF
import rocksdbpy
db = rocksdbpy.open('database.db', rocksdbpy.Option())
token = db.get(b'token:melhor_envio')
print(f"Token existe: {token is not None}")
if token:
    print(f"Tamanho: {len(token)} bytes")
EOF
```

**Solução:**
- Reconfigurar token no painel em `/tokens`
- Verificar se token não expirou

## 📈 Monitoramento Contínuo

### Comando útil para monitorar em tempo real

```bash
# Ver logs de cronjob em tempo real
tail -f /opt/melhor_envio/logs/cronjob_monitor_shipments.log

# Filtrar apenas erros em tempo real
tail -f /opt/melhor_envio/logs/errors.log

# Ver estatísticas de execução
grep "RESUMO" /opt/melhor_envio/logs/cronjob_monitor_shipments.log | tail -n 10
```

### Criar alerta para erros (opcional)

```bash
# Adicionar em crontab para receber email se houver muitos erros
*/10 * * * * ERROR_COUNT=$(grep "ERROR" /opt/melhor_envio/logs/errors.log | wc -l); if [ $ERROR_COUNT -gt 100 ]; then echo "Muitos erros no sistema de rastreamento!" | mail -s "ALERTA: Sistema Melhor Envio" admin@exemplo.com; fi
```

## 🔧 Configuração de Logs

### Variáveis de Ambiente

Adicione no `.env`:

```env
# Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL=INFO

# Throttle entre requisições (segundos)
WEBHOOKS_THROTTLE=0.5

# Máximo de retries para rate limit
WEBHOOKS_MAX_RETRIES=3
RATE_LIMIT_MAX_RETRIES=10
```

### Limpeza de Logs Antigos (Opcional)

Logs são automaticamente rotacionados, mas você pode limpar manualmente:

```bash
# Limpar logs com mais de 30 dias
find /opt/melhor_envio/logs -name "*.log.*" -mtime +30 -delete

# Compactar logs antigos
find /opt/melhor_envio/logs -name "*.log.*" -exec gzip {} \;
```

## 📞 Suporte

Se após seguir este guia o problema persistir:

1. Colete os logs relevantes:
```bash
# Últimas 500 linhas do log de erros
tail -n 500 /opt/melhor_envio/logs/errors.log > /tmp/debug_errors.log

# Últimas 1000 linhas do cronjob principal
tail -n 1000 /opt/melhor_envio/logs/cronjob_monitor_shipments.log > /tmp/debug_cronjob.log

# Status do scheduler
curl http://localhost/api/health/cronjobs > /tmp/debug_health.json
```

2. Compartilhe os arquivos gerados para análise

## ✅ Checklist de Verificação Rápida

- [ ] Logs estão sendo gerados em `/opt/melhor_envio/logs/`?
- [ ] Cronjobs aparecem em `/api/health/cronjobs`?
- [ ] Token do Melhor Envio configurado?
- [ ] Token Umbler configurado (se usar WhatsApp)?
- [ ] Sem erros críticos em `errors.log`?
- [ ] Scheduler rodando? (`scheduler_running: true`)
- [ ] Próxima execução agendada? (`next_run` presente)

Se todos os itens estão OK mas ainda há problemas, revisar logs detalhados do cronjob específico.
