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


def formatar_rastreio_para_whatsapp(rastreio_data):
    """
    Formata dados de rastreio JSON em texto legível para WhatsApp
    """
    if isinstance(rastreio_data, dict):
        if 'erro' in rastreio_data:
            return f"❌ Erro: {rastreio_data['erro']}"
        
        if 'ultimo_evento' in rastreio_data:
            # Montar uma string mais completa usando campos principais (formato BR)
            codigo = rastreio_data.get('codigo_original') or rastreio_data.get('codigo_interno') or ''
            status_atual = rastreio_data.get('status_atual') or ''
            consulta = rastreio_data.get('consulta_realizada_em') or ''
            evento = rastreio_data['ultimo_evento']

            def _format_data_br(dt_raw):
                if not dt_raw:
                    return 'Data desconhecida'
                # esperado formato ISO: YYYY-MM-DDTHH:MM:SS(.sss)Z
                try:
                    part_date, part_time = dt_raw.split('T')
                    time_part = part_time.replace('Z', '')
                    hhmm = time_part.split(':')[:2]
                    hhmm = ':'.join(hhmm)
                    yyyy, mm, dd = part_date.split('-')
                    return f"{dd}/{mm}/{yyyy} {hhmm}"
                except Exception:
                    # fallback simples
                    return dt_raw.replace('T', ' ').replace('Z', '')[:16]

            # Data/hora amigável
            data_raw = evento.get('data_registro') or evento.get('data_criacao') or ''
            data_amigavel = _format_data_br(data_raw)

            titulo = evento.get('titulo') or evento.get('descricao') or 'Evento'
            origem = evento.get('origem') or ''
            destino = evento.get('destino') or ''
            localizacao = evento.get('localizacao') or ''
            rota = evento.get('rota') or ''

            linhas = []
            if codigo:
                linhas.append(f"📦 Rastreio: {codigo}")
            if status_atual:
                linhas.append(f"Status: {status_atual}")
            linhas.append(f"Última atualização: {data_amigavel}")

            detalhe = titulo
            if origem or destino or rota:
                partes = []
                if origem:
                    partes.append(origem)
                if destino:
                    partes.append(destino)
                if rota and not (origem or destino):
                    partes.append(rota)
                if partes:
                    detalhe += " — " + " → ".join([p for p in partes if p])

            if localizacao:
                detalhe += f" ({localizacao})"

            linhas.append(f"• {detalhe}")

            if consulta:
                linhas.append(f"Consulta em: {_format_data_br(consulta)}")

            # Adicionar link amigável para rastreio (se tivermos o código)
            if codigo:
                linhas.append("")
                linhas.append(f"Ver rastreio: https://melhorrastreio.com.br/{codigo}")

            # Mensagem final, adequada para envio via WhatsApp no Brasil
            return "\n".join(linhas)
        
        eventos = rastreio_data.get('eventos', [])
        if not eventos:
            return "📦 Sem movimentação registrada"

        # Se não houver 'ultimo_evento' explícito, usar o primeiro evento para montar a mensagem
        if eventos:
            primeiro = eventos[0]
            # Tentar extrair mesmos campos usados quando 'ultimo_evento' existe
            codigo = rastreio_data.get('codigo_original') or rastreio_data.get('codigo_interno') or ''
            status_atual = rastreio_data.get('status_atual') or ''
            consulta = rastreio_data.get('consulta_realizada_em') or ''

            def _format_data_br(dt_raw):
                if not dt_raw:
                    return 'Data desconhecida'
                try:
                    part_date, part_time = dt_raw.split('T')
                    time_part = part_time.replace('Z', '')
                    hhmm = time_part.split(':')[:2]
                    hhmm = ':'.join(hhmm)
                    yyyy, mm, dd = part_date.split('-')
                    return f"{dd}/{mm}/{yyyy} {hhmm}"
                except Exception:
                    return dt_raw.replace('T', ' ').replace('Z', '')[:16]

            data_raw = primeiro.get('data_registro') or primeiro.get('data_criacao') or ''
            data_amigavel = _format_data_br(data_raw)

            titulo = primeiro.get('titulo') or primeiro.get('descricao') or 'Evento'
            origem = primeiro.get('origem') or ''
            destino = primeiro.get('destino') or ''
            localizacao = primeiro.get('localizacao') or ''
            rota = primeiro.get('rota') or ''

            linhas = []
            if codigo:
                linhas.append(f"📦 Rastreio: {codigo}")
            if status_atual:
                linhas.append(f"Status: {status_atual}")
            linhas.append(f"Última atualização: {data_amigavel}")

            detalhe = titulo
            if origem or destino or rota:
                partes = []
                if origem:
                    partes.append(origem)
                if destino:
                    partes.append(destino)
                if rota and not (origem or destino):
                    partes.append(rota)
                if partes:
                    detalhe += " — " + " → ".join([p for p in partes if p])

            if localizacao:
                detalhe += f" ({localizacao})"

            linhas.append(f"• {detalhe}")

            if consulta:
                linhas.append(f"Consulta em: {_format_data_br(consulta)}")

            if codigo:
                linhas.append("")
                linhas.append(f"Ver rastreio: https://melhorrastreio.com.br/{codigo}")

            return "\n".join(linhas)

        # Formatar os 3 eventos mais recentes (fallback)
        linhas = ["📦 Últimas atualizações do rastreio:"]
        for evento in eventos[:3]:
            data = evento.get('data_registro', '').split('T')[0] if evento.get('data_registro') else 'Data desconhecida'
            titulo = evento.get('titulo') or evento.get('descricao') or 'Evento'
            localizacao = evento.get('localizacao') or ''

            linha = f"• {data}: {titulo}"
            if localizacao:
                linha += f" ({localizacao})"

            linhas.append(linha)

        return '\n'.join(linhas)
    
    # Fallback para outros tipos
    return str(rastreio_data)


def formatar_rastreio_para_painel(rastreio_data):
    """
    Formata dados de rastreio JSON em HTML legível para painel administrativo
    """
    if isinstance(rastreio_data, dict):
        if 'erro' in rastreio_data:
            return f"<p style='color: red;'>Erro: {rastreio_data['erro']}</p>"
        
        if 'ultimo_evento' in rastreio_data:
            evento = rastreio_data['ultimo_evento']
            data = evento.get('data_registro', '').split('T')[0] if evento.get('data_registro') else 'Data desconhecida'
            titulo = evento.get('titulo') or evento.get('descricao') or 'Evento'
            localizacao = evento.get('localizacao') or ''
            origem = evento.get('origem') or ''
            destino = evento.get('destino') or ''
            
            html = "<table border='1' style='border-collapse: collapse; width: 100%;'><thead><tr><th>Data</th><th>Status</th><th>Localização</th><th>Origem</th><th>Destino</th></tr></thead><tbody>"
            html += f"<tr><td>{data}</td><td>{titulo}</td><td>{localizacao}</td><td>{origem}</td><td>{destino}</td></tr>"
            html += "</tbody></table>"
            return html
        
        eventos = rastreio_data.get('eventos', [])
        if not eventos:
            return "<p>Sem movimentação registrada</p>"
        
        # Formatar os 10 eventos mais recentes em tabela HTML
        html = "<table border='1' style='border-collapse: collapse; width: 100%;'><thead><tr><th>Data</th><th>Status</th><th>Localização</th><th>Origem</th><th>Destino</th></tr></thead><tbody>"
        for evento in eventos[:10]:
            data = evento.get('data_registro', '').split('T')[0] if evento.get('data_registro') else 'Data desconhecida'
            titulo = evento.get('titulo') or evento.get('descricao') or 'Evento'
            localizacao = evento.get('localizacao') or ''
            origem = evento.get('origem') or ''
            destino = evento.get('destino') or ''
            
            html += f"<tr><td>{data}</td><td>{titulo}</td><td>{localizacao}</td><td>{origem}</td><td>{destino}</td></tr>"
        
        html += "</tbody></table>"
        return html
    
    # Fallback para outros tipos
    return str(rastreio_data)


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
        #"toPhone": to_phone,
        "toPhone": "+5527998870163",
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
                    mensagem = formatar_rastreio_para_whatsapp(rastreio_detalhado)
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
        """Retorna tuple (start_hour, end_hour) lidos do DB ou .env com fallback 6-18."""
        try:
            if job_db is None:
                job_db = rocksdbpy.open('database.db', rocksdbpy.Option())
            start_key = b"config:monitor_start_hour"
            end_key = b"config:monitor_end_hour"
            start = job_db.get(start_key)
            end = job_db.get(end_key)
            if start:
                start_hour = int(start.decode('utf-8'))
            else:
                start_hour = int(os.getenv('MONITOR_START_HOUR', 6))
            if end:
                end_hour = int(end.decode('utf-8'))
            else:
                end_hour = int(os.getenv('MONITOR_END_HOUR', 18))
            # sanitize
            start_hour = max(0, min(23, start_hour))
            end_hour = max(0, min(24, end_hour))
            return start_hour, end_hour
        except Exception as e:
            print(f"[CRON] Erro ao ler horas de monitoramento: {e}")
            return 6, 18

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
                        shipment['rastreio_detalhado'] = rastreio_data
                        shipment['rastreio_html'] = formatar_rastreio_para_painel(rastreio_data)
                        shipment['rastreio_whatsapp'] = formatar_rastreio_para_whatsapp(rastreio_data)
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



