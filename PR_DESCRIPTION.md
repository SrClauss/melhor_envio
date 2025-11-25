# feat: Sistema de boas-vindas automático + proteção contra mensagens de erro

## 🎉 Novas Funcionalidades

### 1. Cronjob de Boas-Vindas Automático 👋
- Envia mensagem automática quando nova etiqueta é criada
- Executa a cada 10 minutos (configurável via `WELCOME_INTERVAL_MINUTES`)
- Respeita horário configurado de monitoramento
- **Anti-colisão**: não executa se estiver próximo (< 10 min) do cronjob principal
- **Validação**: só envia se rastreamento estiver disponível e com eventos válidos

### 2. Proteção Contra Mensagens de Erro 🔒
- **Problema resolvido**: sistema não envia mais mensagens de erro (como "PARCEL_NOT_FOUND") para clientes
- Validações em todos os pontos de envio:
  - Cronjob principal
  - Cronjob de boas-vindas
  - Botão manual "Enviar Mensagem"
- Aguarda rastreamento válido antes de enviar

### 3. Botão "Enviar Mensagem" Melhorado ✨
- Consulta rastreamento via GraphQL **antes** de enviar
- Garante dados sempre atualizados
- Fallback para dados do banco se API falhar
- Validações rigorosas antes do envio

### 4. Interface Dupla de Templates 📝
- Página `/mensagem` redesenhada com dois formulários:
  - 📦 **Mensagem de Atualizações** (quando rastreamento muda)
  - 👋 **Mensagem de Boas-Vindas** (quando etiqueta é criada)
- Placeholders personalizáveis para cada tipo
- Templates editáveis pelo painel admin

### 5. Sistema de Backup Automático 💾
- **Script manual**: `backup-db.sh` (backup sob demanda)
- **Script semanal**: `backup-cron-weekly.sh` (todo domingo às 03:00)
- Volume Docker separado para backups (`/opt/melhor_envio/backups`)
- Limpeza automática (mantém últimos 10 backups ou 60 dias)

### 6. Script de Migração 🔄
- `migrate_existing_shipments.py` marca shipments atuais como "já notificados"
- **Obrigatório** executar antes do deploy
- Dry-run disponível para teste
- Evita mensagens duplicadas para clientes antigos

---

## 📦 Arquivos Modificados

### Novos Arquivos
- ✨ `DEPLOY.md` - Documentação completa de implantação
- ✨ `backup-db.sh` - Script de backup manual
- ✨ `backup-cron-weekly.sh` - Script de backup semanal
- ✨ `migrate_existing_shipments.py` - Migração de dados

### Arquivos Atualizados
- 🔧 `app/webhooks.py` - Funções de boas-vindas + validações
- 🔧 `app/api.py` - Endpoint com validações de erro
- 🔧 `app/renders.py` - Rotas para templates duplos
- 🔧 `templates/mensagem.html` - Interface redesenhada
- 🔧 `main.py` - Inicialização do cronjob de boas-vindas
- 🔧 `docker-compose.yaml` - Volume de backups

---

## ⚠️ IMPORTANTE: Instruções de Deploy

### 1️⃣ Backup (OBRIGATÓRIO)
```bash
cd /opt/melhor_envio
./backup-db.sh
```

### 2️⃣ Migração (OBRIGATÓRIO)
```bash
# Dry-run primeiro
python3 migrate_existing_shipments.py --dry-run

# Executar de verdade
python3 migrate_existing_shipments.py
```

### 3️⃣ Atualizar e Rebuild
```bash
git pull origin claude/understand-co-01YQqCTdiPnoqWdtxeSzuQ2m
docker-compose down
docker-compose up -d --build
```

### 4️⃣ Configurar Backup Semanal (Opcional)
```bash
chmod +x backup-cron-weekly.sh
crontab -e
# Adicionar: 0 3 * * 0 /opt/melhor_envio/backup-cron-weekly.sh >> /opt/melhor_envio/backups/backup.log 2>&1
```

---

## ✅ Checklist de Testes

- [ ] Backup do banco executado
- [ ] Script de migração executado (dry-run + real)
- [ ] Container rebuild sem erros
- [ ] Logs verificados (cronjobs iniciados)
- [ ] Botão "Enviar Mensagem" testado
- [ ] Templates editáveis em `/mensagem`
- [ ] Cronjob de boas-vindas funcionando
- [ ] Nenhuma mensagem de erro enviada para clientes

---

## 🧪 Como Testar

### Cronjob de Boas-Vindas
1. Criar etiqueta nova no Melhor Envio
2. Aguardar até 10 minutos
3. Verificar logs: `docker-compose logs -f | grep WELCOME`

### Proteção Contra Erros
1. Criar etiqueta nova (rastreamento ainda não disponível)
2. Verificar logs: `[WELCOME] Rastreamento ainda não disponível, pulando envio`
3. Aguardar rastreamento estar disponível
4. Verificar que mensagem é enviada apenas com dados válidos

### Botão Manual
1. Acessar `/envios` → Clicar "Enviar WhatsApp"
2. Verificar que consulta GraphQL antes de enviar
3. Logs devem mostrar: `[WHATSAPP_MANUAL] Consultando rastreamento atualizado`

---

## 📊 Benefícios

✅ **Clientes não recebem mais mensagens de erro**
✅ **Mensagem de boas-vindas automática**
✅ **Dados sempre atualizados antes de enviar**
✅ **Backup automático semanal**
✅ **Sistema robusto com múltiplas validações**
✅ **Templates totalmente personalizáveis**

---

## 📚 Documentação

Veja `DEPLOY.md` para:
- Passo a passo completo de deploy
- Troubleshooting
- Instruções de rollback
- Monitoramento

---

**Versão**: 2.0.0
**Data**: 2025-11-25
