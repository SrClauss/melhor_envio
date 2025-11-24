#!/usr/bin/env python3
"""
Script de migração one-time para marcar todos os shipments existentes no banco
como já tendo recebido mensagens de boas-vindas e primeira mensagem.

IMPORTANTE: Execute este script ANTES de ativar o novo cronjob de boas-vindas,
caso contrário os clientes antigos receberão mensagens duplicadas!

Uso:
    python migrate_existing_shipments.py

    # Ou para fazer dry-run (apenas mostrar o que seria alterado):
    python migrate_existing_shipments.py --dry-run
"""

import rocksdbpy
import json
import sys
from datetime import datetime

def migrate_existing_shipments(dry_run=False):
    """
    Marca todos os shipments existentes no banco com:
    - welcome_message_sent = True
    - first_message_sent = True

    Isso evita que clientes antigos recebam mensagens duplicadas.
    """

    print("=" * 70)
    print("🔄 MIGRAÇÃO DE SHIPMENTS EXISTENTES")
    print("=" * 70)
    print(f"Modo: {'DRY-RUN (simulação)' if dry_run else 'EXECUÇÃO REAL'}")
    print(f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()

    try:
        # Abrir banco de dados
        print("📂 Abrindo banco de dados...")
        db = rocksdbpy.open('database.db', rocksdbpy.Option())
        print("✅ Banco aberto com sucesso")
        print()

        # Iterar sobre todas as chaves
        print("🔍 Buscando shipments no banco...")
        shipments_found = []

        it = db.iterator()
        for key, value in it:
            try:
                key_str = key.decode('utf-8')

                # Filtrar apenas chaves de etiquetas (ignorar :last_error)
                if key_str.startswith('etiqueta:') and ':last_error' not in key_str:
                    shipment_id = key_str.replace('etiqueta:', '')

                    # Carregar dados do shipment
                    try:
                        shipment_data = json.loads(value.decode('utf-8'))
                    except Exception as e:
                        print(f"   ⚠️  Erro ao ler dados do shipment {shipment_id}: {e}")
                        continue

                    shipments_found.append({
                        'id': shipment_id,
                        'key': key,
                        'data': shipment_data
                    })
            except Exception as e:
                # Ignorar chaves que não conseguimos processar
                continue

        print(f"✅ Encontrados {len(shipments_found)} shipments no banco")
        print()

        if len(shipments_found) == 0:
            print("ℹ️  Nenhum shipment encontrado. Nada a fazer.")
            return

        # Processar cada shipment
        print("🔄 Processando shipments...")
        print()

        updated_count = 0
        already_migrated = 0

        for shipment in shipments_found:
            shipment_id = shipment['id']
            shipment_data = shipment['data']
            key = shipment['key']

            # Verificar se já foi migrado
            welcome_sent = shipment_data.get('welcome_message_sent', False)
            first_sent = shipment_data.get('first_message_sent', False)

            if welcome_sent and first_sent:
                already_migrated += 1
                print(f"   ⏭️  Shipment {shipment_id}: já migrado (pulando)")
                continue

            # Marcar flags
            original_data = dict(shipment_data)
            shipment_data['welcome_message_sent'] = True
            shipment_data['first_message_sent'] = True
            shipment_data['migration_date'] = datetime.now().isoformat()

            # Mostrar mudanças
            nome = shipment_data.get('nome', 'N/A')
            telefone = shipment_data.get('telefone', 'N/A')
            tracking = shipment_data.get('tracking', 'N/A')

            print(f"   📦 Shipment {shipment_id}")
            print(f"      Nome: {nome}")
            print(f"      Telefone: {telefone}")
            print(f"      Tracking: {tracking}")
            print(f"      Mudanças:")
            print(f"         welcome_message_sent: {welcome_sent} → True")
            print(f"         first_message_sent: {first_sent} → True")

            # Salvar no banco (se não for dry-run)
            if not dry_run:
                try:
                    db.set(key, json.dumps(shipment_data, ensure_ascii=False).encode('utf-8'))
                    print(f"      ✅ Atualizado no banco")
                except Exception as e:
                    print(f"      ❌ ERRO ao salvar: {e}")
                    continue
            else:
                print(f"      ⚠️  DRY-RUN: não foi salvo (simulação)")

            updated_count += 1
            print()

        # Resumo
        print("=" * 70)
        print("📊 RESUMO DA MIGRAÇÃO")
        print("=" * 70)
        print(f"Total de shipments encontrados: {len(shipments_found)}")
        print(f"Já migrados (pulados): {already_migrated}")
        print(f"Atualizados: {updated_count}")
        print()

        if dry_run:
            print("⚠️  ATENÇÃO: Esta foi uma SIMULAÇÃO (dry-run)")
            print("   Nenhuma alteração foi feita no banco de dados.")
            print("   Execute novamente sem --dry-run para aplicar as mudanças.")
        else:
            print("✅ Migração concluída com sucesso!")
            print("   Todos os shipments existentes foram marcados como já notificados.")
            print("   Agora você pode ativar o cronjob de boas-vindas com segurança.")

        print("=" * 70)

    except Exception as e:
        print(f"❌ ERRO FATAL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    # Verificar se foi passado --dry-run
    dry_run = '--dry-run' in sys.argv

    if not dry_run:
        print()
        print("⚠️  ATENÇÃO: Você está prestes a MODIFICAR O BANCO DE DADOS!")
        print()
        resposta = input("Tem certeza que deseja continuar? (digite 'SIM' para confirmar): ")

        if resposta.strip().upper() != 'SIM':
            print("❌ Operação cancelada pelo usuário.")
            sys.exit(0)
        print()

    migrate_existing_shipments(dry_run=dry_run)
