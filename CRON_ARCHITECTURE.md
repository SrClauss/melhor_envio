# 🏗️ Arquitetura dos Cronjobs - Sistema de Notificações

## 📋 Visão Geral

O sistema possui **DOIS cronjobs independentes** com responsabilidades bem definidas:

1. **WELCOME CRON** 👋 - Boas-vindas para novos shipments
2. **TRACKING CRON** 🔍 - Monitoramento de mudanças de status

---

## 👋 WELCOME CRON

**Arquivo:** `app/webhooks.py::consultar_novos_shipments_welcome()`  
**Frequência:** A cada 10 minutos  
**Flag utilizada:** `welcome_message_sent`

### Responsabilidades

✅ Detectar shipments novos (não estão no banco OU `welcome_message_sent = False`)  
✅ Enviar mensagem de boas-vindas personalizada  
✅ Marcar `welcome_message_sent = True`  

### O que NÃO faz

❌ Monitorar mudanças de status  
❌ Consultar rastreio detalhado  
❌ Enviar notificações de atualização  

### Fluxo

```
1. Buscar todos os shipments (status=posted)
2. Para cada shipment:
   a. Verificar se existe no banco
   b. Verificar flag welcome_message_sent
   c. Se novo OU sem flag:
      - Enviar mensagem de boas-vindas
      - Marcar welcome_message_sent = True
      - Salvar no banco
```

### Template

Usa `config:whatsapp_template_welcome` do banco ou `DEFAULT_WELCOME_TEMPLATE`

Placeholders disponíveis:
- `[cliente]` - Primeiro nome do cliente
- `[codigo]` - Código de rastreio
- `[link_rastreio]` - Link para rastreamento

---

## 🔍 TRACKING CRON

**Arquivo:** `app/webhooks.py::consultar_shipments()`  
**Frequência:** A cada 60 minutos (configurável) + pausado durante madrugada  
**Flag utilizada:** Nenhuma (compara eventos)

### Responsabilidades

✅ Consultar rastreio atual de todos os shipments  
✅ Detectar mudanças no `ultimo_evento`  
✅ Enviar notificação WhatsApp quando houver atualização  
✅ Salvar novo estado no banco  

### O que NÃO faz

❌ Enviar mensagens de boas-vindas  
❌ Enviar "primeira mensagem"  
❌ Verificar flags de welcome  

### Fluxo

```
1. Buscar todos os shipments (status=posted)
2. Para cada shipment:
   a. Consultar rastreio via API (com retries para rate limit)
   b. Carregar dados antigos do banco
   c. Comparar ultimo_evento atual vs salvo
   d. Se diferente:
      - Enviar notificação WhatsApp
      - Salvar novo estado
   e. Se igual:
      - Apenas atualizar dados (sem notificar)
```

### Detecção de Mudanças

```python
ultimo_evento_atual = rastreio_detalhado['eventos'][0]
ultimo_evento_salvo = old_data['rastreio_detalhado']['ultimo_evento']

if ultimo_evento_atual != ultimo_evento_salvo:
    should_notify = True  # ← ENVIAR NOTIFICAÇÃO
```

### Rate Limit Handling

- Shipments com 429 (rate limit) vão para fila
- Máximo de 10 rodadas de retry
- Pausa de 15-20s entre rodadas
- Delay de 1.9-2.1s entre shipments

---

## 🔄 Ciclo de Vida de um Shipment

```
┌─────────────────────────────────────────────────────────────┐
│ 1. ETIQUETA CRIADA NA API DO MELHOR ENVIO                  │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. WELCOME CRON detecta (novo shipment)                    │
│    - Envia: "Olá [cliente]! Sua encomenda está a caminho..."│
│    - Marca: welcome_message_sent = True                     │
│    - Salva no banco                                         │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. TRACKING CRON monitora mudanças                         │
│    - Consulta rastreio a cada hora                          │
│    - Compara evento atual vs último salvo                   │
│    - Se mudou: envia notificação                            │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. NOVA MOVIMENTAÇÃO                                        │
│    - Detecta: ultimo_evento diferente                       │
│    - Envia: "📦 Atualização! Seu pacote está em..."         │
│    - Atualiza banco com novo evento                         │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
                   (loop)
```

---

## 🚫 Erros Comuns Evitados

### ❌ ANTES (Sistema Antigo)

```python
# TRACKING CRON tentava fazer TUDO:
if is_first_notify:  # ← Confusão!
    should_notify = True
    merged['first_message_sent'] = True  # ← Flag duplicada

if ultimo_evento != old_ultimo:
    should_notify = True  # ← Lógica misturada
```

**Problemas:**
- Duas flags (`welcome_message_sent` vs `first_message_sent`)
- TRACKING enviando boas-vindas
- Estado inconsistente
- Lógica complexa e confusa

### ✅ AGORA (Sistema Corrigido)

```python
# WELCOME CRON:
if not shipment_data.get('welcome_message_sent'):
    enviar_boas_vindas()
    shipment_data['welcome_message_sent'] = True

# TRACKING CRON:
if ultimo_evento_atual != ultimo_evento_salvo:
    enviar_notificacao_mudanca()
    # Sem flags! Apenas compara eventos
```

**Benefícios:**
- Uma flag por cronjob
- Responsabilidades claras
- Código mais simples
- Fácil debugar

---

## 🛠️ Configurações

### Intervalos

```python
# WELCOME CRON
WELCOME_CRON_INTERVAL = 10  # minutos

# TRACKING CRON  
TRACKING_CRON_INTERVAL = 60  # minutos
TRACKING_START_HOUR = 6     # Brasília
TRACKING_END_HOUR = 20      # Brasília
```

### Rate Limits

```python
WEBHOOKS_MAX_RETRIES = 3           # Por shipment
RATE_LIMIT_MAX_RETRIES = 10        # Rodadas de fila
DELAY_BETWEEN_SHIPMENTS = 1.9-2.1  # segundos
DELAY_RETRY_QUEUE = 15-20          # segundos
```

---

## 📊 Monitoramento

### Logs do WELCOME CRON

```
[WELCOME] Novo shipment detectado: abc-123
[WELCOME] ✅ Marcado welcome_message_sent para abc-123
[WELCOME_RESUMO] Processados: 17, Boas-vindas enviadas: 3
```

### Logs do TRACKING CRON

```
[MUDANÇA] abc-123: novo status detectado - Em trânsito
[NOTIFICAÇÃO] Enviando atualização WhatsApp para +5511...
[✅ ENVIADO] Notificação de mudança entregue
[RESUMO] Processados: 15 | Notificações: 4 | Removidos: 0
```

---

## 🔧 Troubleshooting

### "Não recebo boas-vindas"

1. Verificar se `welcome_message_sent = False` no banco
2. Verificar logs do WELCOME CRON
3. Confirmar telefone no shipment
4. Testar template de boas-vindas

### "Não recebo atualizações"

1. Verificar se rastreio tem eventos
2. Confirmar mudança no `ultimo_evento`
3. Verificar logs do TRACKING CRON
4. Confirmar rate limits não bloquearam

### "Recebo duplicado"

1. Verificar se ambos cronjobs estão rodando simultaneamente
2. Confirmar que TRACKING não tem lógica de `is_first_notify`
3. Verificar flags no banco (`welcome_message_sent`)

---

## 📝 Notas de Desenvolvimento

### Ao adicionar nova funcionalidade

**Pergunta:** Este recurso é sobre BOAS-VINDAS ou MUDANÇAS?

- **Boas-vindas** → Adicionar em `consultar_novos_shipments_welcome()`
- **Mudanças** → Adicionar em `consultar_shipments()`

### Não misturar responsabilidades!

❌ **ERRADO:**
```python
def consultar_shipments():
    if shipment_novo:
        enviar_boas_vindas()  # ← Não!
```

✅ **CERTO:**
```python
def consultar_novos_shipments_welcome():
    if shipment_novo:
        enviar_boas_vindas()  # ← Sim!
```

---

**Última atualização:** 23/02/2026  
**Autor:** Sistema de Rastreamento Melhor Envio
