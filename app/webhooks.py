from datetime import datetime, timedelta
from typing import Literal
from fastapi import HTTPException
import requests
import rocksdbpy
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import json
import asyncio
from dotenv import load_dotenv
import os
from app.tracking import rastrear, MelhorRastreioException
import time
import random
from zoneinfo import ZoneInfo


load_dotenv()


# Tipo correto para Python - suporta intervalos de 2min até 4h
MinutesInterval = Literal[2, 10, 15, 20, 30, 45, 60, 120, 180, 240]

# Scheduler global para monitoramento
scheduler = None

# Timezone de exibição (Brasília) e UTC para scheduler/storage
TZ_DISPLAY = ZoneInfo('America/Sao_Paulo')  # Para exibição e input do usuário
TZ_UTC = ZoneInfo('UTC')  # Para o scheduler e storage no banco


def _fmt_local(dt: datetime) -> str:
    """Formata datetime em horário de Brasília com sufixo 'BRT/BRST'."""
    try:
        if dt.tzinfo is None:
            # Se não tem timezone, assume UTC e converte para Brasília
            dt = dt.replace(tzinfo=TZ_UTC)
        return dt.astimezone(TZ_DISPLAY).strftime('%Y-%m-%d %H:%M %Z')
    except Exception:
        return dt.strftime('%Y-%m-%d %H:%M')


def _convert_brasilia_to_utc_hour(brasilia_hhmm: str) -> str:
    """Converte horário HH:MM de Brasília para UTC e retorna HH:MM.
    
    Exemplo: '10:00' (BRT -03:00) -> '13:00' (UTC)
    """
    try:
        hour, minute = map(int, brasilia_hhmm.split(':'))
        # Criar datetime de hoje em Brasília
        now_date = datetime.now(TZ_DISPLAY).date()
        dt_brasilia = datetime(now_date.year, now_date.month, now_date.day, hour, minute, tzinfo=TZ_DISPLAY)
        # Converter para UTC
        dt_utc = dt_brasilia.astimezone(TZ_UTC)
        return dt_utc.strftime('%H:%M')
    except Exception as e:
        print(f"[WARN] Erro ao converter Brasília->UTC '{brasilia_hhmm}': {e}")
        return brasilia_hhmm  # Fallback


def _convert_utc_to_brasilia_hour(utc_hhmm: str) -> str:
    """Converte horário HH:MM de UTC para Brasília e retorna HH:MM.
    
    Exemplo: '13:00' (UTC) -> '10:00' (BRT -03:00)
    """
    try:
        hour, minute = map(int, utc_hhmm.split(':'))
        # Criar datetime de hoje em UTC
        now_date = datetime.now(TZ_UTC).date()
        dt_utc = datetime(now_date.year, now_date.month, now_date.day, hour, minute, tzinfo=TZ_UTC)
        # Converter para Brasília
        dt_brasilia = dt_utc.astimezone(TZ_DISPLAY)
        return dt_brasilia.strftime('%H:%M')
    except Exception as e:
        print(f"[WARN] Erro ao converter UTC->Brasília '{utc_hhmm}': {e}")
        return utc_hhmm  # Fallback


def get_scheduler() -> AsyncIOScheduler:
    """Obtém (ou cria) um único scheduler global, já iniciado."""
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler(timezone=TZ_UTC)
        scheduler.start()
        print(f"[CRON] Scheduler iniciado (timezone=UTC)")
    elif not scheduler.running:
        try:
            scheduler.start()
            print("[CRON] Scheduler (re)iniciado")
        except Exception as e:
            print(f"[CRON] Falha ao iniciar scheduler existente: {e}")
    return scheduler



def normalize_next_interval(interval: MinutesInterval) -> str:
    """
    Retorna o próximo horário baseado no intervalo de minutos no formato "YYYY-MM-DD HH:MM Local"
    Exemplo: se agora são 14:23 e interval=15, retorna "2024-01-01 14:30 Local"
    """
    
    now = datetime.now(TZ_UTC)  # Usar UTC do servidor
    
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
    
    return _fmt_local(next_time)


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
        
        # Bloco opcional: aviso para assistir ao vídeo (configurável por env)
        try:
            video_url = os.getenv('VIDEO_AVISO_URL', '').strip()
        except Exception:
            video_url = ''
        if video_url:
            linhas.append("🚨 ATENÇÃO! ASSISTA O VÍDEO ABAIXO, TEM UMA INFORMAÇÃO IMPORTANTE PRA VOCÊ 🚨")
            linhas.append("👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇")
            linhas.append(video_url)
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
        # Configurável via env WEBHOOKS_THROTTLE (padrão: 0.5 segundos)
        throttle_time = float(os.getenv('WEBHOOKS_THROTTLE', 0.5))
        time.sleep(throttle_time)
        
        # Retornar dados completos da API em formato JSON
        return resultado
        
    except MelhorRastreioException as e:
        return {"erro": f"Erro API Melhor Rastreio: {str(e)}", "codigo": codigo_rastreio}
    except Exception as e:
        return {"erro": f"Erro ao consultar rastreio: {str(e)}", "codigo": codigo_rastreio}

def enviar_para_whatsapp_(mensagem, telefone):
    print(f"[DEBUG] Enviando mensagem via Umbler para {telefone}")
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
                is_error_rastreio = not isinstance(rastreio_detalhado, dict) or (isinstance(rastreio_detalhado, dict) and 'erro' in rastreio_detalhado)
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
                    #enviar_para_whatsapp(mensagem, telefone)
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
                        # Ignorar chaves auxiliares como :last_error
                        if ':last_error' in key_str:
                            continue
                        
                        shipment_id_in_db = key_str.replace('etiqueta:', '')
                        if shipment_id_in_db not in current_shipment_ids:
                            keys_to_remove.append(key)
                except Exception as e:
                    print(f"Erro ao processar chave durante limpeza: {e}")
                    continue
            
            # Remover as chaves fora do iterator
            for key in keys_to_remove:
                try:
                    key_str = key.decode('utf-8')
                    shipment_id_in_db = key_str.replace('etiqueta:', '')
                    
                    # Remover chave principal
                    db.delete(key)
                    removed_count += 1
                    
                    # Remover chave :last_error associada, se existir
                    last_error_key = f"etiqueta:{shipment_id_in_db}:last_error".encode('utf-8')
                    try:
                        db.delete(last_error_key)
                    except:
                        pass  # Chave não existe, ignorar
                    
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


def _get_monitor_hours(job_db):
    """Retorna tuple (start_hour, end_hour) como inteiros de horas (0-24) EM UTC.
    
    Lê strings 'HH:MM' do DB (que estão em UTC) e converte para horas inteiras.
    """
    try:
        if job_db is None:
            job_db = rocksdbpy.open('database.db', rocksdbpy.Option())
        start_key = b"config:monitor_start_hour"
        end_key = b"config:monitor_end_hour"
        start = job_db.get(start_key)
        end = job_db.get(end_key)
        
        # Valores padrão em UTC (06:00 BRT = 09:00 UTC, 18:00 BRT = 21:00 UTC)
        if start:
            start_hour_str = start.decode('utf-8')
        else:
            # Converter padrão de Brasília para UTC
            start_hour_str = _convert_brasilia_to_utc_hour(os.getenv('MONITOR_START_HOUR', '06:00'))
        
        if end:
            end_hour_str = end.decode('utf-8')
        else:
            # Converter padrão de Brasília para UTC
            end_hour_str = _convert_brasilia_to_utc_hour(os.getenv('MONITOR_END_HOUR', '18:00'))
        
        # Sanitize e converter para inteiro (hora)
        start_hour_str = _sanitize_time_format(start_hour_str)
        end_hour_str = _sanitize_time_format(end_hour_str)

        try:
            start_h = int(start_hour_str.split(':')[0])
        except Exception:
            start_h = 9  # 06:00 BRT = 09:00 UTC
        try:
            end_h = int(end_hour_str.split(':')[0])
        except Exception:
            end_h = 21  # 18:00 BRT = 21:00 UTC

        # bounds
        start_h = max(0, min(23, start_h))
        end_h = max(1, min(24, end_h))
        return start_h, end_h
    except Exception as e:
        print(f"[CRON] Erro ao ler horas de monitoramento: {e}")
        return 9, 21  # Padrão: 06:00-18:00 BRT = 09:00-21:00 UTC


def _sanitize_time_format(time_str):
    """Garante que o formato do horário seja HH:MM."""
    try:
        datetime.strptime(time_str, '%H:%M')
        return time_str
    except ValueError:
        return '00:00'  # fallback para um valor padrão


def _calculate_next_valid_execution(interval_minutes: int, db) -> datetime:
    """Calcula a próxima execução válida DENTRO do horário de monitor
    
    IMPORTANTE: Horários de monitoramento são em BRASÍLIA, mas o cálculo retorna UTC.
    - Usuário configura: 06:00-23:00 BRT
    - Banco armazena: 09:00-02:00 UTC (convertido)
    - Esta função: calcula baseado em horário ATUAL de Brasília para verificar se está dentro do range
    
    Retorna um datetime UTC que respeita:
    1. O intervalo de minutos configurado
    2. O horário de monitoramento (verificado em horário de Brasília)
    """
    # Pegar horário atual em Brasília E em UTC
    now_brasilia = datetime.now(TZ_DISPLAY)
    now_utc = datetime.now(TZ_UTC)
    
    # Ler horários do banco (estão em UTC) e converter para Brasília
    start_h_utc, end_h_utc = _get_monitor_hours(db)
    
    # CONVERTER os horários UTC para Brasília para comparação
    # Criar datetime UTC de hoje e converter para Brasília
    today_utc = now_utc.date()
    start_dt_utc = datetime(today_utc.year, today_utc.month, today_utc.day, start_h_utc, 0, tzinfo=TZ_UTC)
    end_dt_utc = datetime(today_utc.year, today_utc.month, today_utc.day, end_h_utc, 0, tzinfo=TZ_UTC)
    
    start_dt_brasilia = start_dt_utc.astimezone(TZ_DISPLAY)
    end_dt_brasilia = end_dt_utc.astimezone(TZ_DISPLAY)
    
    start_h_brt = start_dt_brasilia.hour
    end_h_brt = end_dt_brasilia.hour
    
    print(f"[DEBUG] Horário atual Brasília: {now_brasilia.strftime('%H:%M')}")
    print(f"[DEBUG] Range permitido Brasília: {start_h_brt:02d}:00 - {end_h_brt:02d}:00")
    
    # Calcular o próximo horário baseado no intervalo (em Brasília)
    if interval_minutes == 60:
        # Próxima hora cheia
        next_time = (now_brasilia.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    elif interval_minutes < 60:
        # Próximo múltiplo de minutos
        current_minute = now_brasilia.minute
        remainder = current_minute % interval_minutes
        if remainder == 0 and now_brasilia.second == 0:
            minutes_to_add = interval_minutes
        else:
            minutes_to_add = interval_minutes - remainder if remainder > 0 else interval_minutes
        next_time = (now_brasilia.replace(second=0, microsecond=0) + timedelta(minutes=minutes_to_add))
    else:
        # Intervalos >= 120min: próximo múltiplo de horas
        step_hours = interval_minutes // 60
        base = now_brasilia.replace(minute=0, second=0, microsecond=0)
        if now_brasilia.minute != 0 or now_brasilia.second != 0:
            base = base + timedelta(hours=1)
        add_hours = (step_hours - (base.hour % step_hours)) % step_hours
        if add_hours == 0:
            add_hours = step_hours
        next_time = base + timedelta(hours=add_hours)
    
    print(f"[DEBUG] Próximo horário calculado (Brasília): {next_time.strftime('%Y-%m-%d %H:%M')}")
    
    # Ajustar se está fora do horário permitido (comparação em Brasília)
    max_attempts = 10
    attempts = 0
    while attempts < max_attempts:
        attempts += 1
        
        # Verificar se está dentro do range em horário de Brasília
        if start_h_brt <= next_time.hour < end_h_brt:
            print(f"[DEBUG] ✅ Horário {next_time.strftime('%H:%M')} está dentro do range permitido")
            break
        
        # Se for antes do início, pular para start_h
        if next_time.hour < start_h_brt:
            print(f"[DEBUG] Hora {next_time.hour} < start {start_h_brt}, ajustando para início do período")
            next_time = next_time.replace(hour=start_h_brt, minute=0, second=0, microsecond=0)
            # Garantir alinhamento com intervalo
            if interval_minutes < 60 and interval_minutes != 1:
                next_time = next_time.replace(minute=(next_time.minute // interval_minutes) * interval_minutes)
        else:
            # Passou do horário de hoje, vai para start_h de amanhã
            print(f"[DEBUG] Hora {next_time.hour} >= end {end_h_brt}, indo para amanhã")
            next_time = (next_time + timedelta(days=1)).replace(hour=start_h_brt, minute=0, second=0, microsecond=0)
    
    # Converter de volta para UTC para o scheduler
    next_time_utc = next_time.astimezone(TZ_UTC)
    print(f"[DEBUG] Próximo horário final (UTC): {next_time_utc.strftime('%Y-%m-%d %H:%M')}")
    print(f"[DEBUG] Próximo horário final (Brasília): {next_time.strftime('%Y-%m-%d %H:%M')}")
    
    return next_time_utc
    
    return next_time


def iniciar_monitoramento(interval_minutes: MinutesInterval = 10, db=None):
    """Cria/atualiza o job de monitoramento sem desligar o scheduler global.

    Retorna string com a próxima execução calculada.
    """
    sched = get_scheduler()

    # Remover job existente (se houver) em vez de desligar o scheduler
    try:
        existing = sched.get_job('monitor_shipments')
        if existing:
            sched.remove_job('monitor_shipments')
            print("[CRON] Job anterior removido")
    except Exception as e:
        print(f"[CRON] Não foi possível remover job anterior: {e}")

    # Calcular a próxima execução válida que respeita o horário de monitoramento
    next_valid_time = _calculate_next_valid_execution(interval_minutes, db)
    
    # Usar IntervalTrigger com start_date para garantir execução no horário calculado
    try:
        trigger = IntervalTrigger(
            minutes=interval_minutes, 
            start_date=next_valid_time,
            timezone=TZ_UTC
        )
        print(f"[CRON] Trigger criado: IntervalTrigger({interval_minutes}min, start={_fmt_local(next_valid_time)})")
    except Exception as e:
        print(f"[CRON] Erro ao criar trigger, usando IntervalTrigger simples: {e}")
        trigger = IntervalTrigger(minutes=interval_minutes, timezone=TZ_UTC)
    
    # Job que executa as consultas - verifica horário em BRASÍLIA
    async def _scheduled_job(job_db):
        now_utc = datetime.now(TZ_UTC)
        now_brasilia = datetime.now(TZ_DISPLAY)
        hour_brasilia = now_brasilia.hour
        
        # Ler horários UTC do banco e converter para Brasília
        start_h_utc, end_h_utc = _get_monitor_hours(job_db)
        
        # Converter para Brasília
        today_utc = now_utc.date()
        start_dt_utc = datetime(today_utc.year, today_utc.month, today_utc.day, start_h_utc, 0, tzinfo=TZ_UTC)
        end_dt_utc = datetime(today_utc.year, today_utc.month, today_utc.day, end_h_utc, 0, tzinfo=TZ_UTC)
        
        start_h_brt = start_dt_utc.astimezone(TZ_DISPLAY).hour
        end_h_brt = end_dt_utc.astimezone(TZ_DISPLAY).hour
        
        print(f"[CRON] ⏰ Job disparado em {_fmt_local(now_utc)} (Brasília: {now_brasilia.strftime('%H:%M')})")
        print(f"[CRON] Range permitido: {start_h_brt:02d}:00 - {end_h_brt:02d}:00 (Brasília)")
        
        # Executar apenas entre start_hour e end_hour EM HORÁRIO DE BRASÍLIA
        if start_h_brt <= hour_brasilia < end_h_brt:
            try:
                print(f"[CRON] ✅ Dentro do horário permitido, executando consulta...")
                await consultar_shipments_async(job_db)
            except Exception as e:
                print(f"[CRON] ❌ Erro ao executar consultar_shipments_async: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"[CRON] ⏭️  PULANDO: Hora atual {hour_brasilia:02d}:xx não está entre {start_h_brt:02d}:00-{end_h_brt:02d}:00 (Brasília)")

    try:
        sched.add_job(
            _scheduled_job,
            trigger=trigger,
            args=[db],
            id='monitor_shipments',
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
        print(f"[CRON] Monitoramento iniciado com intervalo de {interval_minutes} minutos")
        # Exibir e retornar a próxima execução REAL do APScheduler
        try:
            job = sched.get_job('monitor_shipments')
            if job and job.next_run_time:
                next_run_str = _fmt_local(job.next_run_time)
                print(f"[CRON] Próxima execução (real): {next_run_str}")
                return next_run_str
        except Exception as e:
            print(f"[CRON] Não foi possível obter próxima execução: {e}")
        return normalize_next_interval(interval_minutes)
    except Exception as e:
        print(f"Erro ao iniciar monitoramento: {e}")
        return normalize_next_interval(interval_minutes)


def parar_monitoramento():
    """Remove o job de monitoramento (mantém o scheduler vivo)."""
    try:
        sched = get_scheduler()
        if sched.get_job('monitor_shipments'):
            sched.remove_job('monitor_shipments')
            print("[CRON] Monitoramento parado (job removido)")
        else:
            print("[CRON] Nenhum job de monitoramento para remover")
    except Exception as e:
        print(f"[CRON] Erro ao parar monitoramento: {e}")


def shutdown_scheduler():
    """Encerra o scheduler global com segurança (usar apenas no shutdown da app)."""
    global scheduler
    if scheduler is None:
        return
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            print("[CRON] Scheduler encerrado")
    except Exception as e:
        # Silenciar erro comum quando já não está rodando
        if 'Scheduler is not running' in str(e):
            print("[CRON] Scheduler já não estava rodando ao encerrar")
        else:
            print(f"[CRON] Erro ao encerrar scheduler: {e}")


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
def forcar_extracao_rastreio(db=None):
    """
    Força a extração do rastreio atualizando o banco de dados, mas sem enviar WhatsApp.
    Similar à consultar_shipments, mas sem notificações.
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
                is_error_rastreio = not isinstance(rastreio_detalhado, dict) or (isinstance(rastreio_detalhado, dict) and 'erro' in rastreio_detalhado)
            except Exception:
                is_error_rastreio = True

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
            
            # NÃO enviar notificação (diferente da consultar_shipments)
            print(f"[EXTRAÇÃO] Rastreio extraído para {shipment_id} (sem WhatsApp)")
            
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
                        # Ignorar chaves auxiliares como :last_error
                        if ':last_error' in key_str:
                            continue
                        
                        shipment_id_in_db = key_str.replace('etiqueta:', '')
                        if shipment_id_in_db not in current_shipment_ids:
                            keys_to_remove.append(key)
                except Exception as e:
                    print(f"Erro ao processar chave durante limpeza: {e}")
                    continue
            
            # Remover as chaves fora do iterator
            for key in keys_to_remove:
                try:
                    key_str = key.decode('utf-8')
                    shipment_id_in_db = key_str.replace('etiqueta:', '')
                    
                    # Remover chave principal
                    db.delete(key)
                    removed_count += 1
                    
                    # Remover chave :last_error associada, se existir
                    last_error_key = f"etiqueta:{shipment_id_in_db}:last_error".encode('utf-8')
                    try:
                        db.delete(last_error_key)
                    except:
                        pass  # Chave não existe, ignorar
                    
                    print(f"[REMOVIDO] Shipment {shipment_id_in_db} não encontrado na API, removido do banco")
                except Exception as e:
                    print(f"Erro ao remover chave {key}: {e}")
                    
        except Exception as e:
            print(f"Erro ao limpar shipments antigos: {e}")
        
        print(f"[RESUMO EXTRAÇÃO] Processados: {processed_count} shipments, Removidos: {removed_count}")
        
    else:
        raise HTTPException(status_code=response.status_code, detail=response.text)


async def forcar_extracao_rastreio_async(db):
    """
    Versão assíncrona da forcar_extracao_rastreio.
    Executa a extração em um executor para não bloquear o event loop.
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, forcar_extracao_rastreio, db)



