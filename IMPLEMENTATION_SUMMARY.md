# 🎯 Resumo da Implementação - Sistema de Captura de Logs

## O Que Foi Implementado

Criei um **sistema completo de logging e diagnóstico** para resolver o problema de cronjobs de rastreamento que estavam falhando silenciosamente.

## 📦 Arquivos Criados/Modificados

### Novos Arquivos

1. **`app/logger.py`** (245 linhas)
   - Módulo centralizado de logging
   - Rotação automática de arquivos (10 MB, 5 backups)
   - Suporte a múltiplos níveis (DEBUG, INFO, WARNING, ERROR, CRITICAL)
   - Logs separados por cronjob
   - Fallback automático para desenvolvimento

2. **`templates/logs.html`** (285 linhas)
   - Interface web moderna para visualização de logs
   - Filtros por nível e quantidade de linhas
   - Destaque de cores por tipo de log
   - Atualização em tempo real

3. **`LOGS_GUIDE.md`** (300+ linhas)
   - Guia completo de troubleshooting
   - 7 cenários comuns documentados
   - Comandos prontos para diagnóstico
   - Checklist de verificação

4. **`README.md`** (200+ linhas)
   - Documentação geral do projeto
   - Quick start guide
   - Referência rápida de troubleshooting

5. **`check_logs.sh`** (130 linhas)
   - Script automatizado de diagnóstico
   - Verifica saúde do sistema
   - Detecta problemas comuns
   - Relatório colorido e organizado

### Arquivos Modificados

1. **`app/webhooks.py`**
   - Adicionado logging detalhado em todas as funções do cronjob
   - Logger específico para `monitor_shipments` e `welcome_shipments`
   - Captura de exceções com stack traces
   - Logs de início/fim com estatísticas

2. **`app/tracking.py`**
   - Logging de requisições à API GraphQL
   - Captura de timeouts e erros de rede
   - Logs de rate limits (429)
   - Debug de extração de rastreio

3. **`app/api.py`**
   - Novo endpoint: `/api/logs/{filename}` - Buscar conteúdo de logs
   - Novo endpoint: `/api/health/cronjobs` - Status dos cronjobs

4. **`app/renders.py`**
   - Nova rota: `/logs` - Interface de visualização

5. **`docker-compose.yaml`**
   - Volume para persistência: `/opt/melhor_envio/logs`
   - Variável de ambiente: `LOG_LEVEL`

## 📊 Logs Gerados

### Estrutura de Diretórios

```
/opt/melhor_envio/logs/
├── melhor_envio.log                    # Log geral (rotação: 10 MB × 5)
├── errors.log                          # Apenas erros (rotação: 10 MB × 5)
├── cronjob_monitor_shipments.log       # Cronjob principal (rotação: 5 MB × 3)
└── cronjob_welcome_shipments.log       # Cronjob de boas-vindas (rotação: 5 MB × 3)
```

### Formato dos Logs

```
2025-12-17 14:23:45 | INFO     | app.webhooks         | consultar_shipments      | Total de shipments carregados: 42 em 2 página(s)
```

**Componentes:**
- Timestamp (com fuso horário)
- Nível (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Módulo (origem do log)
- Função (onde foi gerado)
- Mensagem (descrição detalhada)

## 🔍 Como Diagnosticar Problemas

### Método 1: Interface Web (Mais Fácil)

1. Acesse: `http://seu-servidor/logs`
2. Clique no arquivo de log desejado
3. Use filtros para refinar:
   - **Nível**: ERROR, WARNING, INFO, DEBUG
   - **Linhas**: Quantidade a exibir (10-5000)
4. Clique em "🔄 Atualizar" para recarregar

### Método 2: Script de Diagnóstico

```bash
# Executar no servidor
./check_logs.sh
```

**Output:**
- ✅ Status do diretório de logs
- 📊 Tamanho dos arquivos
- ⚠️  Contagem de erros
- 🔄 Status dos cronjobs
- 📝 Últimas execuções
- 🚨 Rate limits detectados

### Método 3: Linha de Comando

```bash
# Ver logs em tempo real do cronjob principal
tail -f /opt/melhor_envio/logs/cronjob_monitor_shipments.log

# Ver apenas erros
tail -f /opt/melhor_envio/logs/errors.log

# Buscar por palavra-chave
grep "RATE LIMIT" /opt/melhor_envio/logs/cronjob_monitor_shipments.log

# Ver estatísticas de execução
grep "RESUMO" /opt/melhor_envio/logs/cronjob_monitor_shipments.log | tail -n 10
```

### Método 4: API REST

```bash
# Status dos cronjobs
curl http://localhost/api/health/cronjobs | jq

# Últimas 50 linhas do log de erros
curl "http://localhost/api/logs/errors.log?lines=50" | jq

# Filtrar apenas ERRORs
curl "http://localhost/api/logs/melhor_envio.log?lines=200&level=ERROR" | jq
```

## 🎓 Exemplos de Uso

### Exemplo 1: Descobrir por que notificações não estão sendo enviadas

```bash
# Verificar se cronjob está executando
curl http://localhost/api/health/cronjobs

# Ver logs do cronjob
grep "NOTIFICAÇÃO\|WHATSAPP" /opt/melhor_envio/logs/cronjob_monitor_shipments.log | tail -n 20

# Verificar erros no envio
grep "Falha ao enviar WhatsApp" /opt/melhor_envio/logs/cronjob_monitor_shipments.log
```

### Exemplo 2: Investigar rate limits (429)

```bash
# Contar ocorrências
grep "RATE LIMIT" /opt/melhor_envio/logs/cronjob_monitor_shipments.log | wc -l

# Ver detalhes das últimas ocorrências
grep "RATE LIMIT" /opt/melhor_envio/logs/cronjob_monitor_shipments.log | tail -n 10

# Verificar se a fila foi limpa
grep "RATE LIMIT QUEUE" /opt/melhor_envio/logs/cronjob_monitor_shipments.log | tail -n 5
```

### Exemplo 3: Monitorar execução em tempo real

```bash
# Terminal 1: Logs em tempo real
tail -f /opt/melhor_envio/logs/cronjob_monitor_shipments.log

# Terminal 2: Apenas erros
tail -f /opt/melhor_envio/logs/errors.log

# Terminal 3: Docker logs
docker compose logs -f
```

## 🚨 Problemas Mais Comuns e Soluções

### 1. Cronjob não executa

**Sintoma:**
```
# Não aparece no health check
curl http://localhost/api/health/cronjobs
```

**Solução:**
```bash
# Reiniciar container
docker compose restart

# Verificar logs de inicialização
docker compose logs | grep "STARTUP"
```

### 2. Muitos erros 429 (Rate Limit)

**Sintoma:**
```
grep "RATE LIMIT" /opt/melhor_envio/logs/cronjob_monitor_shipments.log | wc -l
# Output: >50
```

**Solução:**
```bash
# Editar .env
WEBHOOKS_THROTTLE=1.5  # Aumentar de 0.5

# Reiniciar
docker compose restart
```

### 3. Token inválido

**Sintoma:**
```
grep "HTTP 401" /opt/melhor_envio/logs/cronjob_monitor_shipments.log
```

**Solução:**
```bash
# Reconfigurar token no painel
# Acessar: http://seu-servidor/tokens
# Inserir novo token
```

### 4. WhatsApp não envia

**Sintoma:**
```
grep "Falha ao enviar WhatsApp" /opt/melhor_envio/logs/cronjob_monitor_shipments.log
```

**Solução:**
```bash
# Verificar token Umbler no .env
grep "TOKEN_UMBLER" .env

# Ver erro específico
grep -A 5 "Falha ao enviar WhatsApp" /opt/melhor_envio/logs/errors.log | tail -n 20
```

## 📈 Informações Capturadas pelos Logs

### Por Execução do Cronjob

- ✅ Timestamp de início e fim
- ✅ Número de shipments processados
- ✅ Número de notificações enviadas
- ✅ Número de shipments removidos
- ✅ Tempo total de execução
- ✅ Rate limits encontrados
- ✅ Erros e exceções com stack trace

### Por Shipment

- ✅ ID do shipment
- ✅ Nome e telefone do cliente
- ✅ Código de rastreio (tracking e self_tracking)
- ✅ Status da extração de rastreio
- ✅ Eventos encontrados
- ✅ Se notificação foi enviada
- ✅ Erros específicos (PARCEL_NOT_FOUND, 429, etc)

### Por Requisição à API

- ✅ URL e método
- ✅ Status code da resposta
- ✅ Tempo de resposta
- ✅ Timeouts
- ✅ Erros de conexão
- ✅ Rate limits (429)

## 🎯 Próximos Passos Recomendados

1. **Deploy da Atualização**
```bash
git pull
docker compose build
docker compose up -d
```

2. **Verificar Logs Iniciais**
```bash
# Aguardar 5 minutos
sleep 300

# Executar diagnóstico
./check_logs.sh
```

3. **Monitorar Primeira Execução**
```bash
tail -f /opt/melhor_envio/logs/cronjob_monitor_shipments.log
```

4. **Acessar Interface Web**
- Abrir: `http://seu-servidor/logs`
- Verificar se todos os arquivos aparecem
- Testar filtros

5. **Documentar Problemas Encontrados**
- Anotar mensagens de erro específicas
- Consultar LOGS_GUIDE.md
- Aplicar soluções documentadas

## 📚 Recursos de Documentação

1. **LOGS_GUIDE.md** - Guia completo de troubleshooting
   - 300+ linhas
   - 7 cenários documentados
   - Comandos prontos
   - Checklist de verificação

2. **README.md** - Visão geral do projeto
   - Quick start
   - Estrutura de diretórios
   - Configuração
   - Recursos avançados

3. **check_logs.sh** - Diagnóstico automatizado
   - Verifica saúde do sistema
   - Detecta problemas comuns
   - Relatório organizado

## ✅ Conclusão

O sistema de logs agora permite:

1. ✅ **Visibilidade Total** - Ver exatamente o que cada cronjob está fazendo
2. ✅ **Diagnóstico Rápido** - Identificar problemas em segundos
3. ✅ **Troubleshooting Guiado** - Documentação para todos os problemas comuns
4. ✅ **Interface Amigável** - Não precisa usar SSH para ver logs
5. ✅ **Monitoramento em Tempo Real** - Acompanhar execuções conforme acontecem
6. ✅ **Histórico Persistente** - Logs rotacionados e mantidos por semanas

**Agora você tem tudo que precisa para diagnosticar e resolver problemas nos cronjobs de rastreamento!** 🎉

---

**Desenvolvido por:** GitHub Copilot Agent
**Data:** 2024-12-17
**Versão:** 2.1.0
