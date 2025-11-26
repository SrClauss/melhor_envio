# Atualização: Proteção PARCEL_NOT_FOUND + Sistema de Retry Robusto

## 📋 Resumo das Mudanças (Commit 795a8b1)

Baseado no feedback do @SrClauss, implementamos duas mudanças principais:

### 1. ⚠️ Proteção PARCEL_NOT_FOUND Restaurada

**Problema Original**: Sistema enviava mensagens de erro "PARCEL_NOT_FOUND" para clientes
**Solução**: Restaurada proteção específica para este erro

#### Locais Modificados:

**a) app/webhooks.py - `consultar_shipments()` (linhas ~737-750)**
```python
# Verificar se é especificamente erro PARCEL_NOT_FOUND (não enviar ao cliente)
is_parcel_not_found = False
if is_error_rastreio and isinstance(rastreio_detalhado, dict) and 'erro' in rastreio_detalhado:
    erro_txt = str(rastreio_detalhado['erro']).lower()
    if ('parcel_not_found' in erro_txt) or ('parcel not' in erro_txt) or ('not found' in erro_txt):
        is_parcel_not_found = True
        print(f"[PARCEL_NOT_FOUND] Não enviará mensagem para {shipment_id}")

# Primeira mensagem só envia se NÃO for PARCEL_NOT_FOUND
if is_first_notify and not is_parcel_not_found:
    should_notify = True
```

**b) app/webhooks.py - `enviar_mensagem_boas_vindas()` (linhas ~1641-1653)**
```python
# Verificar se rastreio é PARCEL_NOT_FOUND antes de enviar
try:
    rastreio_check = extrair_rastreio_api(codigo_rastreio)
    if isinstance(rastreio_check, dict) and 'erro' in rastreio_check:
        erro_txt = str(rastreio_check['erro']).lower()
        if ('parcel_not_found' in erro_txt) or ('parcel not' in erro_txt):
            print(f"[WELCOME] PARCEL_NOT_FOUND para {codigo_rastreio} - não enviando")
            return False
except Exception as e:
    pass  # Em caso de erro, continua e envia
```

**c) app/api.py - `enviar_whatsapp_shipment()` (linhas ~537-543)**
```python
# Verificar se é PARCEL_NOT_FOUND - não permitir envio manual
if isinstance(rastreio_detalhado, dict) and 'erro' in rastreio_detalhado:
    erro_txt = str(rastreio_detalhado['erro']).lower()
    if ('parcel_not_found' in erro_txt) or ('parcel not' in erro_txt):
        raise HTTPException(
            status_code=400, 
            detail="Rastreamento ainda não disponível (PARCEL_NOT_FOUND)..."
        )
```

### 2. 🔄 Sistema Robusto de Retry para Rate Limit

**Problema**: Rate limit (429) não tinha retry adequado
**Solução**: Sistema de fila com múltiplas rodadas de retry

#### Como Funciona:

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Processamento Inicial de Shipments                       │
│    - Tenta extrair rastreio (máx 3 tentativas)              │
│    - Se rate limit após 3 tentativas → adiciona à FILA      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. Processamento da Fila de Rate Limit                      │
│    Até 10 rodadas (configurável):                           │
│    ┌───────────────────────────────────────────────────┐   │
│    │ a) Aguarda 15-20s                                  │   │
│    │ b) Tenta todos os shipments da fila                │   │
│    │ c) Sucesso → remove da fila                        │   │
│    │ d) Ainda com 429 → volta para fila                 │   │
│    │ e) Outro erro → remove da fila                     │   │
│    └───────────────────────────────────────────────────┘   │
│    Continua até fila vazia OU máximo de rodadas             │
└─────────────────────────────────────────────────────────────┘
```

#### Código Implementado (linhas ~865-970):

```python
# Fila para retries de rate limit
rate_limit_queue = []

# Durante processamento inicial
if has_rate_limit:
    rate_limit_queue.append(shipment)
    continue

# Após processar todos shipments
if rate_limit_queue:
    max_queue_retries = int(os.getenv('RATE_LIMIT_MAX_RETRIES', 10))
    retry_round = 0
    
    while rate_limit_queue and retry_round < max_queue_retries:
        retry_round += 1
        print(f"[RATE LIMIT QUEUE] Rodada {retry_round}/{max_queue_retries}")
        
        # Aguardar antes de retry
        sleep_time = random.uniform(15, 20)
        time.sleep(sleep_time)
        
        # Processar fila
        current_queue = rate_limit_queue.copy()
        rate_limit_queue.clear()
        
        for shipment in current_queue:
            rastreio = extrair_rastreio_api(codigo_rastreio)
            
            # Ainda com rate limit? Volta para fila
            if is_rate_limit(rastreio):
                rate_limit_queue.append(shipment)
            else:
                # Sucesso - salvar no banco
                ...
```

#### Configurações:

| Variável de Ambiente | Padrão | Descrição |
|---------------------|--------|-----------|
| `WEBHOOKS_MAX_RETRIES` | 3 | Tentativas durante processamento inicial |
| `RATE_LIMIT_MAX_RETRIES` | 10 | Rodadas de retry da fila |

#### Exemplo de Logs:

```
[RATE LIMIT] Adicionando BR123456789BR à fila de retry

[RATE LIMIT QUEUE] Processando 5 shipments com rate limit...
[RATE LIMIT QUEUE] Rodada 1/10 - 5 shipments na fila
[RATE LIMIT QUEUE] Aguardando 17.3s antes de retentar...
[RATE LIMIT RETRY] Tentando novamente BR123456789BR...
[RATE LIMIT RETRY] Sucesso para BR123456789BR
[RATE LIMIT RETRY] Ainda com rate limit: BR987654321BR

[RATE LIMIT QUEUE] Rodada 2/10 - 1 shipments na fila
[RATE LIMIT QUEUE] Aguardando 18.7s antes de retentar...
[RATE LIMIT RETRY] Tentando novamente BR987654321BR...
[RATE LIMIT RETRY] Sucesso para BR987654321BR

[RATE LIMIT QUEUE] ✅ Fila limpa após 2 rodada(s)!
```

## 📊 Impacto Final

### ❌ PARCEL_NOT_FOUND (NÃO Enviado)
- Cronjob principal: bloqueado
- Boas-vindas: bloqueado
- Botão manual: erro 400

### ✅ Rate Limit 429 (Retry Robusto)
- Sistema de fila automático
- Até 10 rodadas de retry
- Aguarda entre tentativas
- Continua até resolver

### ✅ Outros Erros (Enviados)
- Timeout: enviado
- Erros de API: enviados
- Erros desconhecidos: enviados

## 🔒 Segurança

- ✅ Sintaxe Python validada
- ✅ CodeQL scan: 0 vulnerabilidades
- ✅ Nenhuma exposição de dados sensíveis

## 🚀 Deploy

Pronto para merge e deploy com:
```bash
cd /opt/melhor_envio
./deploy.sh
```

---

**Data**: 2025-11-26  
**Commit**: 795a8b1  
**Branch**: copilot/revert-error-message-not-parcel
