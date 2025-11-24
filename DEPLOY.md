# 🚀 Guia de Deploy - Melhor Envio

## 📋 Mudanças Implementadas

Esta atualização adiciona as seguintes funcionalidades:

### ✨ Novidades

1. **Mensagem de Boas-Vindas Automática** 👋
   - Enviada automaticamente quando uma nova etiqueta é detectada
   - Cronjob independente rodando a cada 10 minutos
   - Respeit horário configurado de monitoramento
   - Anti-colisão com cronjob principal

2. **Botão "Enviar Mensagem" Atualizado** 🔄
   - Agora consulta o rastreamento via GraphQL ANTES de enviar
   - Garante que a mensagem sempre contém dados atualizados
   - Atualiza o banco de dados automaticamente

3. **Interface de Templates** 📝
   - Dois templates editáveis: Boas-Vindas e Atualizações
   - Placeholders personalizáveis
   - Interface moderna na mesma página

4. **Sistema de Backup** 💾
   - Script manual de backup (`backup-db.sh`)
   - Script de backup semanal automático (`backup-cron-weekly.sh`)
   - Volume separado para backups no Docker

---

## ⚠️ IMPORTANTE: Backup Obrigatório

**ANTES DE FAZER QUALQUER DEPLOY**, faça backup do banco de dados:

```bash
# 1. Copiar script de backup para o servidor
scp backup-db.sh user@servidor:/opt/melhor_envio/

# 2. Executar backup no servidor
ssh user@servidor
cd /opt/melhor_envio
chmod +x backup-db.sh
./backup-db.sh
```

---

## 🔧 Passo a Passo para Deploy

### 1️⃣ Fazer Backup (OBRIGATÓRIO)

```bash
cd /opt/melhor_envio
./backup-db.sh
```

### 2️⃣ Migrar Shipments Existentes

**IMPORTANTE**: Execute a migração ANTES de rebuild do container!

Este script marca todos os shipments existentes como "já notificados" para evitar que clientes antigos recebam mensagens duplicadas.

```bash
# Primeiro fazer dry-run (simulação) para ver o que será alterado
python3 migrate_existing_shipments.py --dry-run

# Se estiver tudo ok, executar de verdade
python3 migrate_existing_shipments.py
```

**O que o script faz:**
- Marca todos os shipments atuais com `welcome_message_sent = True`
- Marca todos os shipments atuais com `first_message_sent = True`
- Evita envio de mensagens duplicadas para clientes antigos

### 3️⃣ Atualizar Código

```bash
# No servidor, atualizar o código
cd /opt/melhor_envio
git pull origin claude/understand-co-01YQqCTdiPnoqWdtxeSzuQ2m
```

### 4️⃣ Rebuild do Container

```bash
# Parar container atual
docker-compose down

# Rebuild com nova imagem
docker-compose up -d --build

# Verificar logs
docker-compose logs -f
```

### 5️⃣ Configurar Backup Automático Semanal (Opcional mas Recomendado)

```bash
# Copiar script de backup semanal
cd /opt/melhor_envio
chmod +x backup-cron-weekly.sh

# Adicionar ao crontab (executa todo domingo às 03:00)
crontab -e

# Adicionar esta linha:
0 3 * * 0 /opt/melhor_envio/backup-cron-weekly.sh >> /opt/melhor_envio/backups/backup.log 2>&1
```

---

## 🧪 Testar Após Deploy

### 1. Verificar Logs

```bash
docker-compose logs -f | grep -E "WELCOME|STARTUP"
```

Você deve ver:
```
[STARTUP] Iniciando agendamento do monitoramento com intervalo de X minutos...
[STARTUP] Inicializando cronjob de boas-vindas (novos shipments)...
[WELCOME_CRON] Cronjob de boas-vindas iniciado (intervalo: 10 min)
```

### 2. Testar Botão "Enviar Mensagem"

1. Acessar `/envios`
2. Clicar em "Atualizar"
3. Clicar no botão "Enviar WhatsApp" em um shipment
4. Verificar nos logs:
   ```
   [WHATSAPP_MANUAL] Consultando rastreamento atualizado via GraphQL...
   [WHATSAPP_MANUAL] Rastreamento obtido com sucesso, atualizando banco
   ```

### 3. Testar Templates

1. Acessar `/mensagem`
2. Verificar que aparecem 2 formulários:
   - 📦 Mensagem de Atualizações de Rastreamento
   - 👋 Mensagem de Boas-Vindas
3. Editar e salvar ambos os templates

### 4. Testar Cronjob de Boas-Vindas

Criar uma etiqueta nova no Melhor Envio e aguardar até 10 minutos. Verificar logs:
```bash
docker-compose logs -f | grep WELCOME
```

Deve aparecer:
```
[WELCOME_CRON] ⏰ Job disparado em...
[WELCOME_CRON] ✅ Executando consulta de novos shipments...
[WELCOME] Novo shipment detectado: 123456
[WELCOME] Enviando boas-vindas para +55...
[WELCOME] ✅ Boas-vindas enviada com sucesso
```

---

## 🎛️ Variáveis de Ambiente (Opcionais)

Você pode adicionar estas variáveis no `.env` (ou docker-compose) para personalizar:

```bash
# Intervalo do cronjob de boas-vindas (padrão: 10 minutos)
WELCOME_INTERVAL_MINUTES=10

# Templates padrão (se não configurados no painel)
WHATSAPP_TEMPLATE_DEFAULT="Mensagem de atualização personalizada..."
WHATSAPP_WELCOME_TEMPLATE_DEFAULT="Mensagem de boas-vindas personalizada..."
```

---

## 📊 Monitoramento

### Verificar Status dos Cronjobs

Veja os próximos horários de execução nos logs de startup:

```bash
docker-compose logs | grep "Próxima execução"
```

### Verificar Backups

```bash
ls -lh /opt/melhor_envio/backups/
```

### Ver Log de Backups Semanais

```bash
tail -f /opt/melhor_envio/backups/backup.log
```

---

## 🔄 Rollback (Se algo der errado)

### Reverter para Backup

```bash
# 1. Parar container
docker-compose down

# 2. Restaurar backup
cd /opt/melhor_envio
rm -rf database.db
cp -r backups/database_TIMESTAMP.db database.db

# 3. Reiniciar
docker-compose up -d
```

### Reverter Código

```bash
git checkout COMMIT_ANTERIOR
docker-compose up -d --build
```

---

## 📝 Checklist de Deploy

- [ ] Backup do banco de dados executado
- [ ] Script de migração executado (dry-run E real)
- [ ] Código atualizado (git pull)
- [ ] Container rebuild (docker-compose up -d --build)
- [ ] Logs verificados (sem erros)
- [ ] Botão "Enviar Mensagem" testado
- [ ] Templates testados (acessar `/mensagem`)
- [ ] Cronjob de boas-vindas funcionando
- [ ] Backup semanal configurado (crontab)

---

## 🆘 Troubleshooting

### Container não inicia

```bash
# Ver logs completos
docker-compose logs

# Verificar se o banco está travado
ls -la /opt/melhor_envio/database.db/LOCK
# Se existir e não houver processo rodando, deletar:
rm /opt/melhor_envio/database.db/LOCK
```

### Cronjob de boas-vindas não executa

Verificar:
1. Está dentro do horário configurado? (ver `/dashboard` → Configurações)
2. Está muito próximo do cronjob principal? (anti-colisão de 10 min)

```bash
# Ver logs do cronjob
docker-compose logs | grep WELCOME_CRON
```

### Mensagens duplicadas sendo enviadas

Se clientes antigos estiverem recebendo mensagens:
1. Parar container
2. Executar script de migração novamente
3. Reiniciar container

---

## 📞 Suporte

Em caso de problemas:
1. Verificar logs: `docker-compose logs -f`
2. Restaurar backup se necessário
3. Reportar issue com logs completos

---

**Data de criação**: 2025-11-24
**Versão**: 2.0.0 - Cronjob de Boas-Vindas + Backup Automático
