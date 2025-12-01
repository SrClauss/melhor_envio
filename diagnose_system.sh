#!/bin/bash
# Script de diagnóstico completo do sistema

echo "🔍 DIAGNÓSTICO COMPLETO DO SISTEMA"
echo "===================================="
echo ""
echo "⏰ Horário: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 1. Verificar se container está rodando
echo "1️⃣ STATUS DO CONTAINER"
echo "--------------------"
docker compose ps
echo ""

# 2. Verificar logs recentes do container (últimas 50 linhas)
echo "2️⃣ LOGS RECENTES DO CONTAINER (últimas 50 linhas)"
echo "------------------------------------------------"
docker compose logs --tail=50 fastapi_app 2>&1 | grep -E '\[WELCOME\]|\[STARTUP\]|Iniciando|cronjob|boas-vindas'
echo ""

# 3. Verificar banco de dados (quantidade de shipments)
echo "3️⃣ STATUS DO BANCO DE DADOS"
echo "-------------------------"
curl -s "http://localhost:8000/api/shipments" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    total = len(data.get('shipments', []))
    print(f'Total de shipments no banco: {total}')
    if total == 0:
        print('⚠️  PROBLEMA: Banco vazio - cronjob não está salvando dados')
    else:
        print(f'✅ Banco funcionando - {total} shipments salvos')
except:
    print('❌ Erro ao acessar API')
"
echo ""

# 4. Verificar se tracking específico tem eventos
echo "4️⃣ TESTE DO CÓDIGO LTM-95713684930"
echo "--------------------------------"
python3 << 'PYTHON_SCRIPT'
import sys
sys.path.insert(0, '/opt/melhor_envio')
try:
    from app.tracking import rastrear
    resultado = rastrear('LTM-95713684930')
    eventos = resultado.get('eventos', [])
    print(f"Eventos no tracking: {len(eventos)}")
    if eventos:
        print(f"✅ TEM EVENTOS - mensagem DEVERIA ser enviada")
        print(f"Último evento: {eventos[0].get('titulo_completo', 'N/A')}")
    else:
        print(f"❌ SEM EVENTOS - aguardando movimentação")
except Exception as e:
    print(f"❌ Erro ao testar: {e}")
PYTHON_SCRIPT
echo ""

# 5. Forçar execução do cronjob de boas-vindas manualmente
echo "5️⃣ FORÇAR EXECUÇÃO DO CRONJOB"
echo "----------------------------"
echo "Executando cronjob de boas-vindas manualmente..."
docker compose exec -T fastapi_app python3 << 'PYTHON_SCRIPT'
import sys
sys.path.insert(0, '/app')
try:
    from app.webhooks import consultar_novos_shipments_welcome
    import rocksdbpy

    db = rocksdbpy.open('database.db', rocksdbpy.Option())
    print("Executando consultar_novos_shipments_welcome()...")
    consultar_novos_shipments_welcome(db)
    print("✅ Cronjob executado")
except Exception as e:
    print(f"❌ Erro: {e}")
    import traceback
    traceback.print_exc()
PYTHON_SCRIPT
echo ""

echo "===================================="
echo "✅ DIAGNÓSTICO COMPLETO"
echo ""
echo "Se o banco está vazio (0 shipments):"
echo "  → Verificar se token Melhor Envio está configurado"
echo "  → Verificar se etiquetas têm status 'posted'"
echo "  → Verificar logs para erros de autenticação"
echo ""
echo "Se tracking não tem eventos:"
echo "  → Aguardar transportadora processar etiqueta"
echo "  → Normal para etiquetas recém-criadas"
