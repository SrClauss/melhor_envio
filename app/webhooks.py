from datetime import datetime, timedelta
from typing import Literal
from fastapi import HTTPException
import requests
import rocksdbpy
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import json
import asyncio
from dotenv import load_dotenv
import os
from app.tracking import rastrear, MelhorRastreioException
import time
import random


load_dotenv()


# Tipo correto para Python
MinutesInterval = Literal[2, 10, 15, 20, 30, 45, 60]

# Scheduler global para monitoramento
scheduler = None



def normalize_next_interval(interval: MinutesInterval) -> str:
    """
    Retorna o próximo horário baseado no intervalo de minutos no formato "YYYY-MM-DD HH:MM Local"
    Exemplo: se agora são 14:23 e interval=15, retorna "2024-01-01 14:30 Local"
    """
    
    now = datetime.now()  # Usar horário local do sistema
    
    if interval == 60:
        # Próxima hora cheia
        next_time = (now.replace(minute=0, second=0, microsecond=0) + 
                    timedelta(hours=1))
    else:
        # Calcula quantos minutos faltam para o próximo intervalo
        current_minute = now.minute
        remainder = current_minute % interval
        
        if remainder == 0:
            # Já está exatamente no intervalo, vai para o próximo
            minutes_to_add = interval
        else:
            # Calcula minutos para chegar ao próximo intervalo
            minutes_to_add = interval - remainder
        
        next_time = (now.replace(second=0, microsecond=0) + 
                    timedelta(minutes=minutes_to_add))
    
    return next_time.strftime("%Y-%m-%d %H:%M Local")


def formatar_mensagem_rastreio(rastreio_data, shipment_data=None, cliente_nome=None):
    """
    Formata dados de rastreio em mensagem unificada estilo Magalu.
    Funciona tanto para WhatsApp quanto para painel.
    
    Args:
        rastreio_data: Dados do rastreio da API GraphQL
        shipment_data: Dados da etiqueta do Melhor Envio (opcional)
        cliente_nome: Nome do cliente (opcional)
    """
    if isinstance(rastreio_data, dict):
        if 'erro' in rastreio_data:
            return f"❌ Erro: {rastreio_data['erro']}"
        
        # Extrair nome do cliente (primeiro nome apenas) e formatar corretamente
        nome_cliente = ""
        if cliente_nome:
            primeiro_nome = cliente_nome.split()[0] if cliente_nome.split() else ""
            # Converter para título (primeira letra maiúscula, resto minúscula)
            nome_cliente = primeiro_nome.title() if primeiro_nome else ""
        elif shipment_data and shipment_data.get('to', {}).get('name'):
            nome_completo = shipment_data['to']['name']
            primeiro_nome = nome_completo.split()[0] if nome_completo.split() else ""
            # Converter para título (primeira letra maiúscula, resto minúscula)
            nome_cliente = primeiro_nome.title() if primeiro_nome else ""
        
        # Obter código de rastreio
        codigo_rastreio = ""
        if rastreio_data.get('codigo_original'):
            codigo_rastreio = rastreio_data['codigo_original']
        elif rastreio_data.get('codigo_interno'):
            codigo_rastreio = rastreio_data['codigo_interno']
        elif shipment_data and shipment_data.get('tracking'):
            codigo_rastreio = shipment_data['tracking']

        def _format_data_br(dt_raw):
            """Formata data no padrão brasileiro com hora"""
            if not dt_raw:
                return 'Data desconhecida'
            try:
                part_date, part_time = dt_raw.split('T')
                time_part = part_time.replace('Z', '')
                hhmm = time_part.split(':')[:2]
                hhmm = ':'.join(hhmm)
                yyyy, mm, dd = part_date.split('-')
                return f"{dd}/{mm}/{yyyy} às {hhmm}"
            except Exception:
                return dt_raw.replace('T', ' ').replace('Z', '')[:16]

        # Montar mensagem baseada nos eventos
        if 'ultimo_evento' in rastreio_data:
            evento = rastreio_data['ultimo_evento']
        elif rastreio_data.get('eventos'):
            evento = rastreio_data['eventos'][0]  # Primeiro evento (mais recente)
        else:
            return "📦 Sem movimentação registrada"

        # Extrair informações do evento
        data_raw = evento.get('data_registro') or evento.get('data_criacao') or ''
        data_formatada = _format_data_br(data_raw)
        titulo = evento.get('titulo') or evento.get('descricao') or 'Movimentação registrada'
        localizacao = evento.get('localizacao') or ''
        origem = evento.get('origem') or ''
        destino = evento.get('destino') or ''
        rota = evento.get('rota') or ''

        # Construir mensagem estilo Magalu
        linhas = []
        
        # Saudação personalizada
        if nome_cliente:
            linhas.append(f"{nome_cliente},")
            linhas.append("")
            linhas.append(f"Tô passando pra avisar que sua encomenda movimentou! 📦")
        else:
            linhas.append("Olá!")
            linhas.append("")
            linhas.append("Tô passando pra avisar que sua encomenda movimentou! 📦")
        
        linhas.append("")
        
        # Status atual
        emoji_status = '📦'
        if titulo:
            if 'transferencia' in titulo.lower() or 'transferência' in titulo.lower():
                emoji_status = '🔄'
            elif 'entrega' in titulo.lower():
                emoji_status = '🚚'
            elif 'postado' in titulo.lower() or 'postagem' in titulo.lower():
                emoji_status = '📮'
            elif 'trânsito' in titulo.lower() or 'transito' in titulo.lower():
                emoji_status = '🚛'
            elif 'saiu' in titulo.lower():
                emoji_status = '📤'
            elif 'chegou' in titulo.lower() or 'chegada' in titulo.lower():
                emoji_status = '📥'
            elif 'aguarde' in titulo.lower() or 'aguard' in titulo.lower():
                emoji_status = '⏳'
            elif 'entregue' in titulo.lower() or 'delivered' in titulo.lower():
                emoji_status = '✅'
        linhas.append(f"{emoji_status} {titulo}")

        # Localização se disponível
        if localizacao:
            linhas.append(f"📍 Localização: {localizacao}")

        # Rota se disponível
        if origem or destino or rota:
            partes = []
            if origem:
                partes.append(origem)
            if destino:
                partes.append(destino)
            if rota and not (origem or destino):
                partes.append(rota)
            if partes:
                linhas.append(f"🚛 Rota: {' → '.join([p for p in partes if p])}")

        linhas.append("")
        linhas.append(f"🕒 Última atualização: {data_formatada}")
        linhas.append("")
        
        # Link para rastreio detalhado
        if codigo_rastreio:
            linhas.append("Você também pode acompanhar o pedido sempre que quiser pelo link: 👇")
            linhas.append(f"https://melhorrastreio.com.br/{codigo_rastreio}")
            linhas.append("")
        
        linhas.append("Mas pode deixar que assim que tiver alguma novidade, corro aqui pra te avisar! 🏃‍♀️")
        linhas.append("")
        linhas.append("⚠️ Ah, e atenção: nunca solicitamos pagamentos adicionais, dados ou senhas para finalizar a entrega.")
        linhas.append("")
        linhas.append("Se tiver dúvidas, entre em contato conosco.")
        linhas.append("")
        linhas.append("Até mais! 💙")

        return "\n".join(linhas)
    
    # Fallback para outros tipos
    return str(rastreio_data)


def formatar_rastreio_para_whatsapp(rastreio_data, shipment_data=None, cliente_nome=None):
    """
    Wrapper para compatibilidade - usa a função unificada
    """
    return formatar_mensagem_rastreio(rastreio_data, shipment_data, cliente_nome)


def formatar_rastreio_para_painel(rastreio_data, shipment_data=None, cliente_nome=None):
    """
    Wrapper para compatibilidade - usa a função unificada
    """
    return formatar_mensagem_rastreio(rastreio_data, shipment_data, cliente_nome)


def extrair_rastreio_api(codigo_rastreio):
    """
    Extrai rastreio usando API GraphQL do Melhor Rastreio
    Retorna dados completos da API em formato JSON ou mensagem de erro
    """
    print(f"[DEBUG] Extraindo rastreio para código: {codigo_rastreio}")
    
    try:
        resultado = rastrear(codigo_rastreio)
        
        # Throttle simples: aguardar um pequeno intervalo antes da próxima requisição
        # Configurável via env WEBHOOKS_THROTTLE (padrão: 0.3 segundos)
        throttle_time = float(os.getenv('WEBHOOKS_THROTTLE', 0.3))
        time.sleep(throttle_time)
        
        # Retornar dados completos da API em formato JSON
        return resultado
        
    except MelhorRastreioException as e:
        return {"erro": f"Erro API Melhor Rastreio: {str(e)}", "codigo": codigo_rastreio}
    except Exception as e:
        return {"erro": f"Erro ao consultar rastreio: {str(e)}", "codigo": codigo_rastreio}


def enviar_para_whatsapp(mensagem, telefone):
    """
    Envia a mensagem para o número de telefone via WhatsApp Web.
    
    Args:
        mensagem: Texto da mensagem a ser enviada.
        telefone: Número de telefone no formato internacional (ex.: "5511999999999").
    """
    # Carregar token e configuração do .env
    token = os.getenv("TOKEN_UMBLER")
    from_phone = os.getenv("UMBLER_FROM_PHONE", "+5538999978213")
    organization_id = os.getenv("UMBLER_ORG_ID", "aORCMR51FFkJKvJe")

    if not token:
        raise Exception("TOKEN_UMBLER não encontrado nas variáveis de ambiente")

    # Normalizar telefone: manter apenas dígitos e garantir código do Brasil (+55) se não informado
    digits = ''.join([c for c in str(telefone) if c.isdigit()])
    if not digits:
        raise Exception(f"Telefone inválido: {telefone}")
    if not digits.startswith('55'):
        digits = '55' + digits
    to_phone = f"+{digits}"

    payload = {
        "toPhone": to_phone,
        #"toPhone": "+5527998870163",
        "fromPhone": from_phone,
        "organizationId": organization_id,
        "message": mensagem,
        "file": None,
        "skipReassign": False,
        "contactName": "Rastreio"
    }

    headers = {
        'accept': 'application/json',
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    print(f"[DEBUG] Enviando mensagem via Umbler para {to_phone}")
    try:
        resp = requests.post('https://app-utalk.umbler.com/api/v1/messages/simplified/', headers=headers, json=payload, timeout=15)
        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception:
                return {'raw_response': resp.text}
        else:
            # incluir corpo da resposta para diagnostico
            raise Exception(f"Umbler API retornou {resp.status_code}: {resp.text}")
    except requests.RequestException as e:
        raise Exception(f"Erro ao conectar com Umbler: {str(e)}")
def consultar_shipments(db=None):
    """
    Consulta shipments do Melhor Envio e monitora mudanças de rastreio.
    Envia WhatsApp para clientes quando há nova movimentação.
    """
    if db is None:
        db = rocksdbpy.open('database.db', rocksdbpy.Option())
    
    token = db.get(b"token:melhor_envio")
    if not token:   
        raise HTTPException(status_code=401, detail="Token do Melhor Envio não encontrado.")
    token = token.decode('utf-8')

    status = 'posted'
    response = requests.get("https://melhorenvio.com.br/api/v2/me/orders", headers={
        'Authorization': f'Bearer {token}'
    }, params={
        'status': status,
        'page': 1})
    shipments = []

    if response.status_code == 200:
        corrent_page = response.json().get('current_page')
        shipments.extend(response.json().get('data', []))
        status_code = response.status_code
        
        # Buscar todas as páginas
        while status_code == 200:
            response = requests.get("https://melhorenvio.com.br/api/v2/me/orders", headers={
                'Authorization': f'Bearer {token}'
            }, params={
                'status': status,
                'page': corrent_page + 1})
            if response.status_code == 200:
                corrent_page = response.json().get('current_page')
                shipments.extend(response.json().get('data', []))
            else:
                status_code = response.status_code
        
        processed_count = 0
        notifications_sent = 0
        current_shipment_ids = set()
        
        for shipment in shipments:
            shipment_id = shipment.get('id')
            if not shipment_id:
                continue
                
            # Manter registro dos IDs atuais
            current_shipment_ids.add(shipment_id)
                
            # Extrair dados necessários
            to_data = shipment.get('to', {})
            nome = to_data.get('name', '')
            telefone = to_data.get('phone', '')
            
            if not telefone:
                print(f"Shipment {shipment_id} sem telefone do destinatário")
                continue
            
            # Obter rastreamento atual usando API com retry para 429
            codigo_rastreio = shipment.get('tracking')
            if codigo_rastreio:
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        rastreio_detalhado = extrair_rastreio_api(codigo_rastreio)
                    except Exception as e:
                        rastreio_detalhado = f"Erro ao extrair rastreio: {e}"
                    
                    # Verificar se é erro 429
                    if isinstance(rastreio_detalhado, dict) and 'erro' in rastreio_detalhado and '429' in str(rastreio_detalhado['erro']):
                        if attempt < max_retries - 1:
                            sleep_time = random.uniform(10, 12)  # Pausa maior para rate limit
                            print(f"[RATE LIMIT] Pausando por {sleep_time:.2f} segundos devido a 429 para {codigo_rastreio} (tentativa {attempt + 1}/{max_retries})")
                            time.sleep(sleep_time)
                            continue
                        else:
                            print(f"[RATE LIMIT] Máximo de tentativas atingido para {codigo_rastreio}")
                    break  # Sai do loop se não for 429 ou última tentativa
            else:
                rastreio_detalhado = "Sem código de rastreio"
            
            # Verificar se existe entrada anterior no banco
            key = f"etiqueta:{shipment_id}".encode('utf-8')
            existing_data = db.get(key)
            
            # Preparar dados atuais e mesclar com existentes
            should_notify = False

            # Carregar dados antigos se existirem
            old_data = {}
            try:
                if existing_data:
                    old_data = json.loads(existing_data.decode('utf-8'))
            except Exception as e:
                print(f"Erro ao processar dados antigos para {shipment_id}: {e}")

            old_rastreio = old_data.get('rastreio_detalhado', '')

            # Determinar se rastreio atual é erro
            try:
                is_error_rastreio = isinstance(rastreio_detalhado, dict) and 'erro' in rastreio_detalhado
            except Exception:
                is_error_rastreio = True

            # Verificar mudança para notificação (apenas quando rastreio válido)
            if not is_error_rastreio:
                eventos = rastreio_detalhado.get('eventos', [])
                if eventos:
                    ultimo_evento = eventos[0]
                    old_ultimo = old_data.get('rastreio_detalhado', {}).get('ultimo_evento', {})
                    if ultimo_evento != old_ultimo:
                        should_notify = True
                        print(f"[MUDANÇA] {shipment_id}: rastreio atualizado")
                elif rastreio_detalhado != old_rastreio:
                    should_notify = True
                    print(f"[MUDANÇA] {shipment_id}: rastreio atualizado")

            if not existing_data:
                print(f"[NOVO] Criando entrada para shipment {shipment_id}")

            # Montar objeto a gravar: mesclar campos, garantir que 'tracking' seja salvo sempre que disponível
            merged = dict(old_data) if isinstance(old_data, dict) else {}
            merged['nome'] = nome
            merged['telefone'] = telefone
            # Salvar o código de rastreio do próprio objeto (tracking) sempre que presente
            if codigo_rastreio:
                merged['tracking'] = codigo_rastreio

            # Só atualizar rastreio_detalhado quando for uma extração válida
            if not is_error_rastreio:
                eventos = rastreio_detalhado.get('eventos', [])
                if eventos:
                    ultimo_evento = eventos[0]  # Assumindo que o primeiro é o mais recente
                    merged['rastreio_detalhado'] = {
                        'codigo_original': rastreio_detalhado.get('codigo_original'),
                        'status_atual': rastreio_detalhado.get('status_atual'),
                        'ultimo_evento': ultimo_evento,
                        'consulta_realizada_em': rastreio_detalhado.get('consulta_realizada_em')
                    }
                else:
                    merged['rastreio_detalhado'] = rastreio_detalhado

            # Gravar merged no banco
            try:
                db.set(key, json.dumps(merged, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                print(f"Erro ao gravar dados para {shipment_id}: {e}")

            # Se houve erro, registrar last_error
            if is_error_rastreio:
                print(f"[IGNORADO] Não atualizou rastreio_detalhado para {shipment_id} devido a erro: {rastreio_detalhado}")
                try:
                    last_error_key = f"etiqueta:{shipment_id}:last_error".encode('utf-8')
                    last_error_value = json.dumps({
                        "error": rastreio_detalhado,
                        "timestamp": datetime.now().isoformat()
                    }, ensure_ascii=False).encode('utf-8')
                    db.set(last_error_key, last_error_value)
                except Exception as e:
                    print(f"Erro ao gravar last_error para {shipment_id}: {e}")
            
            # Enviar notificação se necessário
            if should_notify:
                try:
                    mensagem = formatar_rastreio_para_whatsapp(rastreio_detalhado, shipment, nome)
                    enviar_para_whatsapp(mensagem, telefone)
                    notifications_sent += 1
                    print(f"[WHATSAPP] Notificação enviada para {telefone}")
                except Exception as e:
                    print(f"Falha ao enviar WhatsApp para {telefone}: {e}")
            
            processed_count += 1
            
            # Timeout aleatório entre 0.75 e 2 segundos entre shipments
            time.sleep(random.uniform(1.9, 2.1))
        
        # Limpar shipments que não existem mais
        removed_count = 0
        try:
            # Buscar todas as chaves que começam com "etiqueta:"
            keys_to_remove = []
            it = db.iterator()
            for key, value in it:
                try:
                    key_str = key.decode('utf-8')
                    if key_str.startswith('etiqueta:'):
                        shipment_id_in_db = key_str.replace('etiqueta:', '')
                        if shipment_id_in_db not in current_shipment_ids:
                            keys_to_remove.append(key)
                except Exception as e:
                    print(f"Erro ao processar chave durante limpeza: {e}")
                    continue
            
            # Remover as chaves fora do iterator
            for key in keys_to_remove:
                try:
                    db.delete(key)
                    removed_count += 1
                    key_str = key.decode('utf-8')
                    shipment_id_in_db = key_str.replace('etiqueta:', '')
                    print(f"[REMOVIDO] Shipment {shipment_id_in_db} não encontrado na API, removido do banco")
                except Exception as e:
                    print(f"Erro ao remover chave {key}: {e}")
                    
        except Exception as e:
            print(f"Erro ao limpar shipments antigos: {e}")
        
        print(f"[RESUMO] Processados: {processed_count} shipments, Notificações enviadas: {notifications_sent}, Removidos: {removed_count}")
        
    else:
        raise HTTPException(status_code=response.status_code, detail=response.text)


async def consultar_shipments_async(db=None):
    """Wrapper async para consultar_shipments que executa a função síncrona em um executor (thread).
    Isso evita bloquear o loop de eventos durante o webscraping com Selenium.
    """
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, consultar_shipments, db)
        print(f"[CRON] Consulta de shipments executada em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        print(f"[CRON] Erro na consulta de shipments: {e}")


def iniciar_monitoramento(interval_minutes: MinutesInterval = 10, db=None):
    """Inicia o monitoramento automático de shipments"""
    global scheduler
    
    if scheduler and scheduler.running:
        try:
            scheduler.shutdown(wait=False)
        except Exception as e:
            print(f"Erro ao parar scheduler anterior: {e}")
    
    scheduler = AsyncIOScheduler()
    
    # Usar IntervalTrigger com o intervalo especificado
    trigger = IntervalTrigger(minutes=interval_minutes)
    
    def _get_monitor_hours(job_db):
        """Retorna tuple (start_hour, end_hour) como inteiros de horas (0-24).
        Lê strings 'HH:MM' do DB/.env e converte para horas inteiras com fallback 06-18.
        """
        try:
            if job_db is None:
                job_db = rocksdbpy.open('database.db', rocksdbpy.Option())
            start_key = b"config:monitor_start_hour"
            end_key = b"config:monitor_end_hour"
            start = job_db.get(start_key)
            end = job_db.get(end_key)
            if start:
                start_hour = start.decode('utf-8')
            else:
                start_hour = os.getenv('MONITOR_START_HOUR', '06:00')
            if end:
                end_hour = end.decode('utf-8')
            else:
                end_hour = os.getenv('MONITOR_END_HOUR', '18:00')
            # sanitize e converter para inteiro (hora)
            start_hour = _sanitize_time_format(start_hour)
            end_hour = _sanitize_time_format(end_hour)

            try:
                start_h = int(start_hour.split(':')[0])
            except Exception:
                start_h = 6
            try:
                end_h = int(end_hour.split(':')[0])
            except Exception:
                end_h = 18

            # bounds
            start_h = max(0, min(23, start_h))
            end_h = max(1, min(24, end_h))
            return start_h, end_h
        except Exception as e:
            print(f"[CRON] Erro ao ler horas de monitoramento: {e}")
            return 6, 18

    def _sanitize_time_format(time_str):
        """Garante que o formato do horário seja HH:MM."""
        try:
            datetime.strptime(time_str, '%H:%M')
            return time_str
        except ValueError:
            return '00:00'  # fallback para um valor padrão

    # Agendar um job que só executa as consultas dentro do horário permitido (configurável)
    async def _scheduled_job(job_db):
        now = datetime.now()
        hour = now.hour
        start_hour, end_hour = _get_monitor_hours(job_db)
        # Executar apenas entre start_hour (inclusive) e end_hour (exclusive)
        if start_hour <= hour < end_hour:
            try:
                await consultar_shipments_async(job_db)
            except Exception as e:
                print(f"[CRON] Erro ao executar consultar_shipments_async: {e}")
        else:
            print(f"[CRON] Pulando execução automática fora do horário permitido ({now.strftime('%Y-%m-%d %H:%M')}) - permitido {start_hour}:00-{end_hour}:00")

    try:
        scheduler.add_job(
            _scheduled_job,
            trigger=trigger,
            args=[db],
            id='monitor_shipments',
            replace_existing=True,
            max_instances=1
        )
        
        scheduler.start()
        print(f"[CRON] Monitoramento iniciado com intervalo de {interval_minutes} minutos")
        print(f"[CRON] Próxima execução: {normalize_next_interval(interval_minutes)}")
            
    except Exception as e:
        print(f"Erro ao iniciar monitoramento: {e}")


def parar_monitoramento():
    """Para o monitoramento automático"""
    global scheduler
    if scheduler and scheduler.running:
        try:
            scheduler.shutdown(wait=True)
            print("[CRON] Monitoramento parado")
        except Exception as e:
            print(f"Erro ao parar monitoramento: {e}")
    else:
        print("Scheduler não estava rodando")


def get_shipments_for_api(db):
    """Retorna shipments para visualização na API (sem processar monitoramento)"""
    token = db.get(b"token:melhor_envio")
    if not token:   
        raise HTTPException(status_code=401, detail="Token do Melhor Envio não encontrado.")
    token = token.decode('utf-8')

    status = 'posted'
    response = requests.get("https://melhorenvio.com.br/api/v2/me/orders", headers={
        'Authorization': f'Bearer {token}'
    }, params={
        'status': status,
        'page': 1})
    shipments = []

    if response.status_code == 200:
        corrent_page = response.json().get('current_page')
        shipments.extend(response.json().get('data', []))
        status_code = response.status_code
        
        while status_code == 200:
            response = requests.get("https://melhorenvio.com.br/api/v2/me/orders", headers={
                'Authorization': f'Bearer {token}'
            }, params={
                'status': status,
                'page': corrent_page + 1})
            if response.status_code == 200:
                corrent_page = response.json().get('current_page')
                shipments.extend(response.json().get('data', []))
            else:
                status_code = response.status_code
        
        # Adicionar dados do banco para cada shipment
        for shipment in shipments:
            shipment_id = shipment.get('id')
            if shipment_id:
                key = f"etiqueta:{shipment_id}".encode('utf-8')
                existing_data = db.get(key)
                if existing_data:
                    try:
                        stored_data = json.loads(existing_data.decode('utf-8'))
                        rastreio_data = stored_data.get('rastreio_detalhado', 'Sem dados de rastreio')
                        nome_cliente = stored_data.get('nome', '') or shipment.get('to', {}).get('name', '')
                        shipment['rastreio_detalhado'] = rastreio_data
                        shipment['rastreio_html'] = formatar_rastreio_para_painel(rastreio_data, shipment, nome_cliente)
                        shipment['rastreio_whatsapp'] = formatar_rastreio_para_whatsapp(rastreio_data, shipment, nome_cliente)
                        # JSON stringificado para exibir no painel (stringify)
                        try:
                            shipment['rastreio_json'] = json.dumps(rastreio_data, ensure_ascii=False, indent=2)
                        except Exception:
                            shipment['rastreio_json'] = str(rastreio_data)
                    except:
                        shipment['rastreio_detalhado'] = 'Erro ao ler dados de rastreio'
                        shipment['rastreio_html'] = '<p>Erro ao ler dados de rastreio</p>'
                        shipment['rastreio_whatsapp'] = 'Erro ao ler dados de rastreio'
                        shipment['rastreio_json'] = 'Erro ao ler dados de rastreio'
                else:
                    shipment['rastreio_detalhado'] = 'Ainda não processado'
                    shipment['rastreio_html'] = '<p>Ainda não processado</p>'
                    shipment['rastreio_whatsapp'] = 'Ainda não processado'
                    shipment['rastreio_json'] = 'Ainda não processado'
        
        return shipments
    else:
        raise HTTPException(status_code=response.status_code, detail=response.text)



