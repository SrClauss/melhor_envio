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
from app.logger import get_logger, get_cronjob_logger, log_execution_time

# Logger principal do módulo
logger = get_logger(__name__)

# Cache simples para template de WhatsApp (evita ler o DB a cada chamada)
_WHATSAPP_TEMPLATE_CACHE = {
    "value": None,  # tipo: Optional[str]
    "ts": 0        # epoch seconds
}

# Template padrão de WhatsApp (inclui bloco do vídeo). Usado quando não há template salvo no DB.
DEFAULT_WHATSAPP_TEMPLATE = (
    "[cliente],\n\n"
    "Tô passando pra avisar que sua encomenda movimentou! 📦\n\n"
    "[rastreio]\n\n"
    "Você também pode acompanhar o pedido sempre que quiser pelo link: 👇\n"
    "[link_rastreio]\n\n"
    "🚨ATENÇÃO! ASSISTA O VIDEO ABAIXO, POIS TEMOS UMA IMPORTANTE INFORMAÇÃO PARA TE PASSAR🚨\n"
    "👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇\n"
    "https://youtube.com/shorts/CcgV7C8m6Ls?si=o-TqLzsBCBli6gdN\n\n"
    "Mas pode deixar que assim que tiver alguma novidade, corro aqui pra te avisar! 🏃‍♀️\n\n"
    "⚠️ Ah, e atenção: nunca solicitamos pagamentos adicionais, dados ou senhas para finalizar a entrega.\n\n"
    "Se tiver dúvidas, entre em contato conosco.\n\n"
    "Até mais! 💙"
)

# Template padrão de mensagem de BOAS-VINDAS (primeira mensagem quando etiqueta é criada)
DEFAULT_WELCOME_TEMPLATE = (
    "Olá [cliente]! 👋\n\n"
    "Seu pedido foi postado com sucesso! 📦\n\n"
    "Código de rastreio: [codigo]\n\n"
    "Você pode acompanhar sua encomenda pelo link:\n"
    "[link_rastreio]\n\n"
    "Vou te avisar automaticamente sempre que houver alguma movimentação! 🚚\n\n"
    "⚠️ Ah, e atenção: nunca solicitamos pagamentos adicionais, dados ou senhas para finalizar a entrega.\n\n"
    "Se tiver dúvidas, entre em contato conosco.\n\n"
    "Até logo! 💙"
)

def _get_whatsapp_template_from_db(db=None, ttl_seconds: int = 60):
    """Obtém o template customizado do WhatsApp do RocksDB com cache simples.
    Se não existir, retorna o DEFAULT_WHATSAPP_TEMPLATE. Se houver erro ao ler, ignora silenciosamente.
    """
    try:
        now = time.time()
        if _WHATSAPP_TEMPLATE_CACHE["value"] is not None and (now - _WHATSAPP_TEMPLATE_CACHE["ts"]) < ttl_seconds:
            return _WHATSAPP_TEMPLATE_CACHE["value"]

        raw = None
        if db is not None:
            try:
                raw = db.get(b"config:whatsapp_template")
            except Exception:
                raw = None
        else:
            # Como fallback, tenta abrir rapidamente o DB (mesmo padrão usado em outras partes)
            try:
                raw = rocksdbpy.open('database.db', rocksdbpy.Option()).get(b"config:whatsapp_template")
            except Exception:
                raw = None

        value = raw.decode('utf-8') if raw else None

        # Se não houver no DB, permitir default via ENV, e por fim cair no DEFAULT_WHATSAPP_TEMPLATE
        if not value:
            env_default = os.getenv('WHATSAPP_TEMPLATE_DEFAULT', '').strip()
            value = env_default or DEFAULT_WHATSAPP_TEMPLATE

        _WHATSAPP_TEMPLATE_CACHE["value"] = value
        _WHATSAPP_TEMPLATE_CACHE["ts"] = now
        return value
    except Exception:
        return None


# Cache para template de boas-vindas (similar ao template principal)
_WELCOME_TEMPLATE_CACHE = {
    "value": None,
    "ts": 0
}


def _get_welcome_template_from_db(db=None, ttl_seconds: int = 60):
    """Obtém o template de boas-vindas do RocksDB com cache simples.
    Se não existir, retorna o DEFAULT_WELCOME_TEMPLATE.
    """
    try:
        now = time.time()
        if _WELCOME_TEMPLATE_CACHE["value"] is not None and (now - _WELCOME_TEMPLATE_CACHE["ts"]) < ttl_seconds:
            return _WELCOME_TEMPLATE_CACHE["value"]

        raw = None
        if db is not None:
            try:
                raw = db.get(b"config:whatsapp_template_welcome")
            except Exception:
                raw = None
        else:
            try:
                raw = rocksdbpy.open('database.db', rocksdbpy.Option()).get(b"config:whatsapp_template_welcome")
            except Exception:
                raw = None

        value = raw.decode('utf-8') if raw else None

        # Se não houver no DB, usar default via ENV ou DEFAULT_WELCOME_TEMPLATE
        if not value:
            env_default = os.getenv('WHATSAPP_WELCOME_TEMPLATE_DEFAULT', '').strip()
            value = env_default or DEFAULT_WELCOME_TEMPLATE

        _WELCOME_TEMPLATE_CACHE["value"] = value
        _WELCOME_TEMPLATE_CACHE["ts"] = now
        return value
    except Exception:
        return DEFAULT_WELCOME_TEMPLATE


load_dotenv()


# Tipo correto para Python - suporta intervalos de 2min até 4h
MinutesInterval = Literal[2, 10, 15, 20, 30, 45, 60, 120, 180, 240]

# Scheduler global para monitoramento
scheduler = None

# Controle de pausa do cronjob de boas-vindas (usado quando forçar cron principal)
_welcome_cron_paused_until = None

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

        # NOVO: Priorizar título e descrição traduzidos completos
        titulo = (
            evento.get('titulo_completo') or
            evento.get('titulo') or
            evento.get('descricao') or
            'Movimentação registrada'
        )
        descricao_completa = evento.get('descricao_completa')

        # Processar localização (pode ser dict ou string)
        localizacao = evento.get('localizacao')
        if isinstance(localizacao, dict):
            # Nova estrutura com mais detalhes
            loc_str = localizacao.get('endereco_completo') or ''
            if localizacao.get('cep'):
                loc_str = f"{loc_str} (CEP: {localizacao['cep']})" if loc_str else f"CEP: {localizacao['cep']}"
            localizacao = loc_str
        elif not localizacao:
            localizacao = ''

        origem = evento.get('origem') or ''
        destino = evento.get('destino') or ''
        rota = evento.get('rota') or ''

        # Informações adicionais disponíveis
        info_adicional = evento.get('informacao_adicional') or ''
        observacoes = evento.get('observacoes') or ''

        # Construir mensagem estilo Magalu (ou aplicar template customizado)
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
        linhas.append(f"*{titulo}*")
        linhas.append("")

        # NOVO: Adicionar descrição completa traduzida se disponível
        if descricao_completa:
            linhas.append(f"_{descricao_completa}_")
            linhas.append("")

        # Localização se disponível
        if localizacao:
            linhas.append(f"📍 *Local:* {localizacao}")

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
                linhas.append(f"🚛 *Rota:* {' → '.join([p for p in partes if p])}")

        # NOVO: Informações adicionais se disponíveis
        if info_adicional:
            linhas.append(f"ℹ️  *Info:* {info_adicional}")

        if observacoes:
            linhas.append(f"📝 *Obs:* {observacoes}")

        if localizacao or origem or destino or rota or info_adicional or observacoes:
            linhas.append("")

        # Se existir template customizado no DB, aplicar substituições e retornar
        template_custom = _get_whatsapp_template_from_db()
        if template_custom:
            # Montar blocos para placeholders
            status_line = f"{emoji_status} {titulo}" if titulo else ""
            rota_partes = []
            if origem:
                rota_partes.append(origem)
            if destino:
                rota_partes.append(destino)
            rota_texto = " → ".join([p for p in rota_partes if p]) if rota_partes else (rota or "")
            link_rastreio = f"https://melhorrastreio.com.br/{codigo_rastreio}" if codigo_rastreio else ""
            # placeholder [rota] inclui label e emoji, se houver valor
            rota_texto_label = f"🚛 Rota: {rota_texto}" if rota_texto else ""

            info_blocos = []
            if status_line:
                info_blocos.append(f"*{titulo}*")
            # NOVO: Adicionar descrição completa
            if descricao_completa:
                info_blocos.append("")
                info_blocos.append(f"_{descricao_completa}_")

            # Adicionar linha vazia antes dos detalhes se houver descrição
            if descricao_completa and (localizacao or rota_texto or info_adicional or observacoes):
                info_blocos.append("")

            if localizacao:
                info_blocos.append(f"📍 *Local:* {localizacao}")
            if rota_texto:
                info_blocos.append(f"🚛 *Rota:* {rota_texto}")
            # NOVO: Adicionar informações extras
            if info_adicional:
                info_blocos.append(f"ℹ️  *Info:* {info_adicional}")
            if observacoes:
                info_blocos.append(f"📝 *Obs:* {observacoes}")

            # Adicionar linha vazia antes da data se houver informações acima
            if localizacao or rota_texto or info_adicional or observacoes:
                info_blocos.append("")

            if data_formatada:
                info_blocos.append(f"🕒 {data_formatada}")
            info_texto = "\n".join(info_blocos)

            final_msg = template_custom
            # Placeholders suportados (incluindo novos)
            replacements = {
                "[cliente]": (nome_cliente or "Olá"),
                "[info]": info_texto,
                "[rastreio]": info_texto,
                "[link_rastreio]": link_rastreio,
                "[codigo]": (codigo_rastreio or ""),
                "[status]": status_line,
                "[descricao]": (descricao_completa or ""),
                "[rota]": rota_texto_label,
                "[localizacao]": (localizacao or ""),
                "[data]": (data_formatada or ""),
                "[info_adicional]": (info_adicional or ""),
                "[observacoes]": (observacoes or ""),
            }
            try:
                for k, v in replacements.items():
                    final_msg = final_msg.replace(k, v)
                return final_msg
            except Exception:
                # Se der erro, cai para o fluxo padrão
                pass

        # Caso não use template custom, continuar com o fluxo padrão
        linhas.append(f"🕒 {data_formatada}")
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
    🔍 CRON DE TRACKING - Monitora mudanças de status dos shipments
    
    RESPONSABILIDADE: 
    - Consultar rastreio atual de todos os shipments
    - Detectar mudanças no último evento
    - Enviar notificação WhatsApp quando houver atualização
    - Salvar novo estado no banco
    
    ⚠️ NÃO É RESPONSÁVEL POR:
    - Enviar mensagens de boas-vindas (isso é feito pelo WELCOME CRON)
    - Primeira mensagem ao criar etiqueta (welcome_message_sent)
    
    Implementa sistema robusto de retries para rate limits:
    - Shipments com rate limit (429) são colocados em fila de retry
    - Retenta até que não haja mais erros de rate limit
    - PARCEL_NOT_FOUND não envia mensagem ao cliente
    """
    # Logger específico para este cronjob
    cron_logger = get_cronjob_logger('monitor_shipments')
    cron_logger.info("=" * 80)
    cron_logger.info("INICIANDO CONSULTA DE SHIPMENTS - Monitoramento de Rastreio")
    cron_logger.info("=" * 80)
    
    try:
        if db is None:
            db = rocksdbpy.open('database.db', rocksdbpy.Option())
            cron_logger.debug("Banco de dados RocksDB aberto")
        
        token = db.get(b"token:melhor_envio")
        if not token:
            cron_logger.error("Token do Melhor Envio não encontrado no banco de dados")
            raise HTTPException(status_code=401, detail="Token do Melhor Envio não encontrado.")
        token = token.decode('utf-8')
        cron_logger.debug("Token do Melhor Envio recuperado com sucesso")

        status = 'posted'
        cron_logger.info(f"Consultando API Melhor Envio - Status: {status}")
        
        try:
            response = requests.get("https://melhorenvio.com.br/api/v2/me/orders", headers={
                'Authorization': f'Bearer {token}'
            }, params={
                'status': status,
                'page': 1}, timeout=30)
        except requests.exceptions.Timeout as e:
            cron_logger.error(f"Timeout ao consultar API Melhor Envio: {e}")
            raise
        except requests.exceptions.RequestException as e:
            cron_logger.error(f"Erro de rede ao consultar API Melhor Envio: {e}", exc_info=True)
            raise
        
        shipments = []

        if response.status_code == 200:
            corrent_page = response.json().get('current_page')
            shipments.extend(response.json().get('data', []))
            status_code = response.status_code
            cron_logger.info(f"Página 1 carregada: {len(shipments)} shipments encontrados")
            
            # Buscar todas as páginas
            page_count = 1
            while status_code == 200:
                page_count += 1
                try:
                    response = requests.get("https://melhorenvio.com.br/api/v2/me/orders", headers={
                        'Authorization': f'Bearer {token}'
                    }, params={
                        'status': status,
                        'page': corrent_page + 1}, timeout=30)
                except requests.exceptions.RequestException as e:
                    cron_logger.warning(f"Erro ao buscar página {page_count}: {e}")
                    break
                    
                if response.status_code == 200:
                    corrent_page = response.json().get('current_page')
                    page_data = response.json().get('data', [])
                    shipments.extend(page_data)
                    cron_logger.debug(f"Página {page_count} carregada: {len(page_data)} shipments")
                else:
                    status_code = response.status_code
                    cron_logger.debug(f"Última página alcançada: {page_count - 1}")
            
            cron_logger.info(f"Total de shipments carregados: {len(shipments)} em {page_count} página(s)")
            
            processed_count = 0
            notifications_sent = 0
            current_shipment_ids = set()
            
            # Fila para retries de rate limit - processados ao final
            rate_limit_queue = []
            
            for idx, shipment in enumerate(shipments, 1):
                shipment_id = shipment.get('id')
                if not shipment_id:
                    cron_logger.warning(f"Shipment #{idx} sem ID, pulando")
                    continue
                    
                cron_logger.debug(f"[{idx}/{len(shipments)}] Processando shipment {shipment_id}")
                
                # Manter registro dos IDs atuais
                current_shipment_ids.add(shipment_id)
                    
                # Extrair dados necessários
                to_data = shipment.get('to', {})
                nome = to_data.get('name', '')
                telefone = to_data.get('phone', '')
                
                if not telefone:
                    cron_logger.warning(f"Shipment {shipment_id} sem telefone do destinatário")
                    continue
                
                # Obter rastreamento atual usando API com retries controlados.
                # Estratégia:
                # - Retentar para casos transitórios: HTTP 429 (rate limit), timeouts, e erros conhecidos como PARCEL_NOT_FOUND
                # - Pausar um pouco entre tentativas (backoff simples)
                # - Não enviar notificação caso a extração não retorne eventos válidos (já tratado mais adiante)
                codigo_rastreio = shipment.get('tracking')  # Código da transportadora (pode demorar para aparecer)
                codigo_self_tracking = shipment.get('self_tracking')  # Código próprio do Melhor Envio (disponível imediatamente)
                if codigo_rastreio:
                    cron_logger.debug(f"Shipment {shipment_id} tem código de rastreio: {codigo_rastreio}")
                    max_retries = int(os.getenv('WEBHOOKS_MAX_RETRIES', 3))
                    rastreio_detalhado = None
                    has_rate_limit = False
                    
                    for attempt in range(1, max_retries + 1):
                        try:
                            cron_logger.debug(f"Tentativa {attempt}/{max_retries} de extrair rastreio para {codigo_rastreio}")
                            rastreio_detalhado = extrair_rastreio_api(codigo_rastreio)
                        except Exception as e:
                            # Normalizar para dict com 'erro' para facilitar análise
                            cron_logger.error(f"Exceção ao extrair rastreio {codigo_rastreio}: {e}", exc_info=True)
                            rastreio_detalhado = {"erro": f"Erro ao extrair rastreio: {e}"}

                        # Se veio um dict sem 'erro' e com eventos, considerar sucesso imediato
                        if isinstance(rastreio_detalhado, dict) and 'erro' not in rastreio_detalhado and rastreio_detalhado.get('eventos'):
                            cron_logger.debug(f"Rastreio extraído com sucesso para {codigo_rastreio}: {len(rastreio_detalhado.get('eventos', []))} eventos")
                            break

                        # Inspecionar texto do erro para decidir retry
                        try:
                            txt = json.dumps(rastreio_detalhado)
                        except Exception:
                            txt = str(rastreio_detalhado)
                        txt_low = txt.lower()

                        # Rate limit (429) - marcar para fila de retry
                        if ('429' in txt_low) or ('rate limit' in txt_low):
                            if attempt < max_retries:
                                sleep_time = random.uniform(10, 12)
                                cron_logger.warning(f"[RATE LIMIT] Pausando por {sleep_time:.2f}s devido a 429 para {codigo_rastreio} (tentativa {attempt}/{max_retries})")
                                time.sleep(sleep_time)
                                continue
                            else:
                                # Máximo de tentativas atingido - adicionar à fila para retry posterior
                                cron_logger.warning(f"[RATE LIMIT] Adicionando {codigo_rastreio} à fila de retry")
                                has_rate_limit = True
                                break

                        # Timeout - retry
                        if ('timeout' in txt_low) or ('timed out' in txt_low):
                            if attempt < max_retries:
                                sleep_time = random.uniform(1, 3)
                                cron_logger.warning(f"[RETRY] Pausando por {sleep_time:.2f}s antes de nova tentativa para {codigo_rastreio} (tentativa {attempt}/{max_retries})")
                                time.sleep(sleep_time)
                                continue
                            else:
                                cron_logger.warning(f"[RETRY] Máximo de tentativas atingido para {codigo_rastreio}")
                                break

                        # PARCEL_NOT_FOUND - não fazer retry, será filtrado depois
                        # (não envia mensagem para cliente)
                        if ('parcel_not_found' in txt_low) or ('parcel not' in txt_low) or ('not found' in txt_low):
                            cron_logger.debug(f"[PARCEL_NOT_FOUND] Rastreio ainda não disponível para {codigo_rastreio}")
                            break

                        # Caso não seja um erro identificável para retry, sair
                        break
                    
                    # Se tem rate limit, adicionar à fila para processar depois
                if has_rate_limit:
                    rate_limit_queue.append(shipment)
                    continue
                    
                # Se não obteve resultado, normalizar texto
                if rastreio_detalhado is None:
                    rastreio_detalhado = {"erro": "Sem resultado da extração"}
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

            # ========================================================================
            # TRACKING CRON: Responsável APENAS por monitorar MUDANÇAS de status
            # Boas-vindas são enviadas pelo WELCOME CRON separadamente
            # ========================================================================
            
            # Determinar se rastreio atual é erro
            try:
                is_error_rastreio = not isinstance(rastreio_detalhado, dict) or (isinstance(rastreio_detalhado, dict) and 'erro' in rastreio_detalhado)
            except Exception:
                is_error_rastreio = True
            
            # Verificar se é especificamente erro PARCEL_NOT_FOUND (não logar muito)
            is_parcel_not_found = False
            if is_error_rastreio and isinstance(rastreio_detalhado, dict) and 'erro' in rastreio_detalhado:
                erro_txt = str(rastreio_detalhado['erro']).lower()
                if ('parcel_not_found' in erro_txt) or ('parcel not' in erro_txt) or ('not found' in erro_txt):
                    is_parcel_not_found = True
                    cron_logger.debug(f"[PARCEL_NOT_FOUND] Rastreio ainda não disponível para {shipment_id}")

            # ========== DETECTAR MUDANÇAS DE STATUS (única responsabilidade) ==========
            # Notificar SOMENTE quando houver eventos E o último evento for diferente
            if not is_error_rastreio:
                eventos = rastreio_detalhado.get('eventos', [])
                if eventos:
                    ultimo_evento = eventos[0]
                    old_ultimo = old_data.get('rastreio_detalhado', {}).get('ultimo_evento', {})
                    
                    # Verificar se houve mudança real no evento
                    if ultimo_evento != old_ultimo:
                        should_notify = True
                        cron_logger.info(f"[MUDANÇA] {shipment_id}: novo status detectado - {rastreio_detalhado.get('status_atual')}")
                    else:
                        cron_logger.debug(f"[SEM MUDANÇA] {shipment_id}: status inalterado")

            # ========== SEMPRE PROCESSAR E SALVAR DADOS ==========
            if not existing_data:
                cron_logger.info(f"[NOVO] Criando entrada para shipment {shipment_id}")

            # Montar objeto a gravar: mesclar campos, garantir que 'tracking' seja salvo sempre que disponível
            merged = dict(old_data) if isinstance(old_data, dict) else {}
            merged['nome'] = nome
            merged['telefone'] = telefone
            # Salvar o código de rastreio do próprio objeto (tracking) sempre que presente
            if codigo_rastreio:
                merged['tracking'] = codigo_rastreio
            # Salvar também o self_tracking (código próprio do Melhor Envio)
            if codigo_self_tracking:
                merged['self_tracking'] = codigo_self_tracking

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
                    cron_logger.debug(f"Rastreio atualizado para {shipment_id}: {rastreio_detalhado.get('status_atual')}")
                else:
                    merged['rastreio_detalhado'] = rastreio_detalhado
                    cron_logger.debug(f"Rastreio sem eventos para {shipment_id}")

            # Gravar merged no banco
            try:
                db.set(key, json.dumps(merged, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                cron_logger.error(f"Erro ao gravar dados para {shipment_id}: {e}", exc_info=True)

            # Se houve erro, registrar last_error
            if is_error_rastreio:
                cron_logger.warning(f"[IGNORADO] Não atualizou rastreio_detalhado para {shipment_id} devido a erro")
                cron_logger.debug(f"Erro detalhado: {rastreio_detalhado}")
                try:
                    last_error_key = f"etiqueta:{shipment_id}:last_error".encode('utf-8')
                    last_error_value = json.dumps({
                        "error": rastreio_detalhado,
                        "timestamp": datetime.now().isoformat()
                    }, ensure_ascii=False).encode('utf-8')
                    db.set(last_error_key, last_error_value)
                except Exception as e:
                    cron_logger.error(f"Erro ao gravar last_error para {shipment_id}: {e}")
            
            # ========== ENVIAR NOTIFICAÇÃO DE MUDANÇA ==========
            # Apenas envia se detectou mudança de status (should_notify = True)
            if should_notify:
                try:
                    mensagem = formatar_rastreio_para_whatsapp(rastreio_detalhado, shipment, nome)
                    cron_logger.info(f"[NOTIFICAÇÃO] Enviando atualização WhatsApp para {telefone} - {shipment_id}")
                    enviar_para_whatsapp(mensagem, telefone)
                    notifications_sent += 1
                    cron_logger.info(f"[✅ ENVIADO] Notificação de mudança entregue para {telefone}")
                except Exception as e:
                    cron_logger.error(f"[❌ FALHA] Erro ao enviar WhatsApp para {telefone}: {e}")
            
            processed_count += 1
            
            # Timeout aleatório entre 0.75 e 2 segundos entre shipments
            time.sleep(random.uniform(1.9, 2.1))
        
        # ========== PROCESSAMENTO DA FILA DE RATE LIMIT ==========
        # Retry shipments com rate limit até que não haja mais erros
        if rate_limit_queue:
            print(f"\n[RATE LIMIT QUEUE] Processando {len(rate_limit_queue)} shipments com rate limit...")
            max_queue_retries = int(os.getenv('RATE_LIMIT_MAX_RETRIES', 10))
            retry_round = 0
            
            while rate_limit_queue and retry_round < max_queue_retries:
                retry_round += 1
                print(f"[RATE LIMIT QUEUE] Rodada {retry_round}/{max_queue_retries} - {len(rate_limit_queue)} shipments na fila")
                
                # Pausar antes de retry para respeitar rate limit
                sleep_time = random.uniform(15, 20)
                print(f"[RATE LIMIT QUEUE] Aguardando {sleep_time:.1f}s antes de retentar...")
                time.sleep(sleep_time)
                
                # Processar fila atual
                current_queue = rate_limit_queue.copy()
                rate_limit_queue.clear()
                
                for shipment in current_queue:
                    shipment_id = shipment.get('id')
                    codigo_rastreio = shipment.get('tracking')
                    
                    if not codigo_rastreio:
                        continue
                    
                    print(f"[RATE LIMIT RETRY] Tentando novamente {codigo_rastreio}...")
                    
                    try:
                        rastreio_detalhado = extrair_rastreio_api(codigo_rastreio)
                        
                        # Verificar se ainda tem rate limit
                        if isinstance(rastreio_detalhado, dict) and 'erro' in rastreio_detalhado:
                            erro_txt = str(rastreio_detalhado['erro']).lower()
                            if ('429' in erro_txt) or ('rate limit' in erro_txt):
                                # Ainda com rate limit - voltar para fila
                                rate_limit_queue.append(shipment)
                                print(f"[RATE LIMIT RETRY] Ainda com rate limit: {codigo_rastreio}")
                                continue
                        
                        # Sucesso ou outro erro - processar normalmente
                        to_data = shipment.get('to', {})
                        nome = to_data.get('name', '')
                        telefone = to_data.get('phone', '')
                        
                        if not telefone:
                            continue
                        
                        key = f"etiqueta:{shipment_id}".encode('utf-8')
                        existing_data = db.get(key)
                        
                        old_data = {}
                        if existing_data:
                            try:
                                old_data = json.loads(existing_data.decode('utf-8'))
                            except:
                                pass
                        
                        # Salvar dados atualizados
                        merged = dict(old_data) if isinstance(old_data, dict) else {}
                        merged['nome'] = nome
                        merged['telefone'] = telefone
                        if codigo_rastreio:
                            merged['tracking'] = codigo_rastreio
                        
                        # Atualizar rastreio se válido
                        if isinstance(rastreio_detalhado, dict) and 'erro' not in rastreio_detalhado:
                            eventos = rastreio_detalhado.get('eventos', [])
                            if eventos:
                                merged['rastreio_detalhado'] = {
                                    'codigo_original': rastreio_detalhado.get('codigo_original'),
                                    'status_atual': rastreio_detalhado.get('status_atual'),
                                    'ultimo_evento': eventos[0],
                                    'consulta_realizada_em': rastreio_detalhado.get('consulta_realizada_em')
                                }
                        
                        db.set(key, json.dumps(merged, ensure_ascii=False).encode('utf-8'))
                        print(f"[RATE LIMIT RETRY] Sucesso para {codigo_rastreio}")
                        processed_count += 1
                        
                    except Exception as e:
                        print(f"[RATE LIMIT RETRY] Erro ao processar {codigo_rastreio}: {e}")
                        # Não readicionar à fila em caso de erro
                    
                    # Pequeno delay entre retries
                    time.sleep(random.uniform(2, 3))
                
                if not rate_limit_queue:
                    print(f"[RATE LIMIT QUEUE] ✅ Fila limpa após {retry_round} rodada(s)!")
                    break
            
            if rate_limit_queue:
                print(f"[RATE LIMIT QUEUE] ⚠️ Ainda restam {len(rate_limit_queue)} shipments com rate limit após {max_queue_retries} rodadas")
        
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
                    
                    cron_logger.info(f"[REMOVIDO] Shipment {shipment_id_in_db} não encontrado na API, removido do banco")
                except Exception as e:
                    cron_logger.error(f"Erro ao remover chave {key}: {e}")
                    
        except Exception as e:
            cron_logger.error(f"Erro ao limpar shipments antigos: {e}", exc_info=True)
        
            cron_logger.info("=" * 80)
            cron_logger.info(f"[RESUMO] Processados: {processed_count} | Notificações: {notifications_sent} | Removidos: {removed_count}")
            cron_logger.info("=" * 80)
        
        else:
            # HTTP 204 (No Content) é válido quando não há mais dados/páginas
            if response.status_code == 204:
                cron_logger.debug("API retornou 204 (No Content) - sem mais dados disponíveis")
            else:
                cron_logger.error(f"Erro ao consultar API Melhor Envio: HTTP {response.status_code}")
                cron_logger.error(f"Detalhes: {response.text}")
                raise HTTPException(status_code=response.status_code, detail=response.text)
    
    except Exception as e:
        cron_logger.error(f"❌ ERRO CRÍTICO ao consultar shipments: {e}", exc_info=True)
        raise

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
            codigo_rastreio = shipment.get('tracking')  # Código da transportadora
            codigo_self_tracking = shipment.get('self_tracking')  # Código próprio do Melhor Envio
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
            # Salvar também o self_tracking (código próprio do Melhor Envio)
            if codigo_self_tracking:
                merged['self_tracking'] = codigo_self_tracking

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


def formatar_mensagem_boas_vindas(nome_cliente, codigo_rastreio, db=None):
    """
    Formata a mensagem de boas-vindas usando o template customizado ou padrão.

    Placeholders suportados:
        [cliente] - Primeiro nome do cliente
        [codigo] - Código de rastreio
        [link_rastreio] - Link para rastreamento

    Args:
        nome_cliente: Nome completo do cliente
        codigo_rastreio: Código de rastreio da encomenda
        db: Instância do banco de dados (opcional)

    Returns:
        String com a mensagem formatada
    """
    # Obter template do banco ou usar padrão
    template = _get_welcome_template_from_db(db)

    # Extrair primeiro nome
    primeiro_nome = ""
    if nome_cliente:
        primeiro_nome = nome_cliente.split()[0] if nome_cliente.split() else ""
        primeiro_nome = primeiro_nome.title() if primeiro_nome else "Olá"
    else:
        primeiro_nome = "Olá"

    # Link de rastreamento
    link_rastreio = f"https://melhorrastreio.com.br/{codigo_rastreio}" if codigo_rastreio else ""

    # Substituir placeholders
    mensagem = template
    replacements = {
        "[cliente]": primeiro_nome,
        "[codigo]": (codigo_rastreio or ""),
        "[link_rastreio]": link_rastreio,
    }

    for placeholder, valor in replacements.items():
        mensagem = mensagem.replace(placeholder, valor)

    return mensagem


def enviar_mensagem_boas_vindas(shipment_data, db=None):
    """
    Envia mensagem de boas-vindas para um shipment novo.

    NOVA LÓGICA:
    - Primeiro tenta usar o código 'tracking' (transportadora)
    - Se não disponível ou sem eventos, tenta 'self_tracking' (Melhor Envio)
    - Envia mensagem se QUALQUER um dos códigos estiver disponível

    Args:
        shipment_data: Dados do shipment (dict com nome, telefone, tracking, self_tracking)
        db: Instância do banco de dados

    Returns:
        True se enviou com sucesso, False caso contrário
    """
    try:
        nome = shipment_data.get('nome', '')
        telefone = shipment_data.get('telefone', '')
        codigo_rastreio = shipment_data.get('tracking', '')  # Código da transportadora
        codigo_self_tracking = shipment_data.get('self_tracking', '')  # Código Melhor Envio

        if not telefone:
            print(f"[WELCOME] Shipment sem telefone, pulando")
            return False

        if not codigo_rastreio and not codigo_self_tracking:
            print(f"[WELCOME] Shipment sem nenhum código de rastreio (tracking ou self_tracking), pulando")
            return False

        # 🎯 NOVA LÓGICA: Tentar primeiro o tracking da transportadora, depois o self_tracking
        codigo_para_usar = None
        tipo_codigo = None

        # Tentativa 1: Verificar tracking da transportadora
        if codigo_rastreio:
            try:
                rastreio_check = extrair_rastreio_api(codigo_rastreio)
                is_error = not isinstance(rastreio_check, dict) or 'erro' in rastreio_check
                eventos = rastreio_check.get('eventos', []) if isinstance(rastreio_check, dict) else []

                if not is_error and eventos:
                    # Sucesso! Tracking da transportadora está disponível e tem eventos
                    codigo_para_usar = codigo_rastreio
                    tipo_codigo = 'tracking'
                    print(f"[WELCOME] ✅ Tracking da transportadora disponível: {codigo_rastreio}")
                else:
                    erro_tipo = rastreio_check.get('erro', 'UNKNOWN') if isinstance(rastreio_check, dict) else 'INVALID_DATA'
                    print(f"[WELCOME] ⚠️  Tracking da transportadora {codigo_rastreio} não disponível (erro: {erro_tipo}) ou sem eventos")

            except Exception as e:
                print(f"[WELCOME] ⚠️  Erro ao verificar tracking da transportadora {codigo_rastreio}: {e}")

        # Tentativa 2: Se tracking não funcionou, tentar self_tracking
        if not codigo_para_usar and codigo_self_tracking:
            print(f"[WELCOME] 🔄 Tentando self_tracking do Melhor Envio: {codigo_self_tracking}")
            try:
                rastreio_check = extrair_rastreio_api(codigo_self_tracking)
                is_error = not isinstance(rastreio_check, dict) or 'erro' in rastreio_check
                eventos = rastreio_check.get('eventos', []) if isinstance(rastreio_check, dict) else []

                if not is_error and eventos:
                    # Sucesso! Self tracking está disponível
                    codigo_para_usar = codigo_self_tracking
                    tipo_codigo = 'self_tracking'
                    print(f"[WELCOME] ✅ Self tracking do Melhor Envio disponível: {codigo_self_tracking}")
                else:
                    erro_tipo = rastreio_check.get('erro', 'UNKNOWN') if isinstance(rastreio_check, dict) else 'INVALID_DATA'
                    print(f"[WELCOME] ⚠️  Self tracking {codigo_self_tracking} não disponível (erro: {erro_tipo}) ou sem eventos")

            except Exception as e:
                print(f"[WELCOME] ⚠️  Erro ao verificar self_tracking {codigo_self_tracking}: {e}")

        # Verificar se conseguimos um código válido
        if not codigo_para_usar:
            print(f"[WELCOME] ❌ Nenhum código de rastreio disponível para envio")
            print(f"[WELCOME] ℹ️  Etiquetas recém-criadas podem levar algumas horas para serem indexadas")
            print(f"[WELCOME] ℹ️  Tentará novamente na próxima verificação automática")
            return False

        # Formatar mensagem usando o código que funcionou
        mensagem = formatar_mensagem_boas_vindas(nome, codigo_para_usar, db)

        # Enviar WhatsApp
        print(f"[WELCOME] 📤 Enviando boas-vindas para {telefone} (código {tipo_codigo}: {codigo_para_usar})")
        resultado = enviar_para_whatsapp(mensagem, telefone)

        print(f"[WELCOME] ✅ Boas-vindas enviada com sucesso para {telefone} usando {tipo_codigo}")
        return True

    except Exception as e:
        print(f"[WELCOME] ❌ Erro ao enviar boas-vindas: {e}")
        return False


def consultar_novos_shipments_welcome(db=None):
    """
    👋 CRON DE WELCOME - Envia mensagens de boas-vindas para novos shipments
    
    RESPONSABILIDADE:
    - Detectar shipments novos (não estão no banco OU sem welcome_message_sent)
    - Enviar mensagem de boas-vindas personalizada
    - Marcar welcome_message_sent = True
    
    ⚠️ NÃO É RESPONSÁVEL POR:
    - Monitorar mudanças de status (isso é feito pelo TRACKING CRON)
    - Consultar rastreio detalhado (apenas usa código para link)
    
    Executado a cada 10 minutos (configurável).
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
        welcome_sent_count = 0

        for shipment in shipments:
            shipment_id = shipment.get('id')
            if not shipment_id:
                continue

            # Extrair dados necessários
            to_data = shipment.get('to', {})
            nome = to_data.get('name', '')
            telefone = to_data.get('phone', '')
            codigo_rastreio = shipment.get('tracking', '')  # Código da transportadora
            codigo_self_tracking = shipment.get('self_tracking', '')  # Código próprio do Melhor Envio

            if not telefone:
                print(f"[WELCOME] Shipment {shipment_id} sem telefone do destinatário")
                continue

            # Verificar se existe entrada no banco
            key = f"etiqueta:{shipment_id}".encode('utf-8')
            existing_data = db.get(key)

            should_send_welcome = False

            if not existing_data:
                # Shipment NOVO - nunca visto antes
                should_send_welcome = True
                print(f"[WELCOME] Novo shipment detectado: {shipment_id}")
            else:
                # Verificar se já enviou mensagem de boas-vindas
                try:
                    old_data = json.loads(existing_data.decode('utf-8'))
                    welcome_sent = old_data.get('welcome_message_sent', False)

                    if not welcome_sent:
                        should_send_welcome = True
                        print(f"[WELCOME] Shipment {shipment_id} sem welcome_message_sent")
                except Exception as e:
                    print(f"[WELCOME] Erro ao ler dados para {shipment_id}: {e}")
                    # Se erro ao ler, assumir que não foi enviado
                    should_send_welcome = True

            # Enviar mensagem de boas-vindas se necessário
            if should_send_welcome:
                # Criar/atualizar dados no banco
                shipment_data = {
                    'nome': nome,
                    'telefone': telefone,
                    'tracking': codigo_rastreio,
                    'self_tracking': codigo_self_tracking,
                }

                # Enviar mensagem
                success = enviar_mensagem_boas_vindas(shipment_data, db)

                if success:
                    # Marcar como enviado
                    shipment_data['welcome_message_sent'] = True
                    shipment_data['welcome_sent_at'] = datetime.now().isoformat()

                    # Salvar no banco
                    try:
                        db.set(key, json.dumps(shipment_data, ensure_ascii=False).encode('utf-8'))
                        welcome_sent_count += 1
                        print(f"[WELCOME] ✅ Marcado welcome_message_sent para {shipment_id}")
                    except Exception as e:
                        print(f"[WELCOME] ❌ Erro ao salvar dados para {shipment_id}: {e}")
                else:
                    print(f"[WELCOME] ❌ Falha ao enviar boas-vindas para {shipment_id}")

                # Throttle entre envios
                time.sleep(random.uniform(2, 3))

            processed_count += 1

        print(f"[WELCOME_RESUMO] Processados: {processed_count} shipments, Boas-vindas enviadas: {welcome_sent_count}")

    else:
        raise HTTPException(status_code=response.status_code, detail=response.text)


async def consultar_novos_shipments_welcome_async(db=None):
    """
    Wrapper async para consultar_novos_shipments_welcome.
    Executa em um executor para não bloquear o event loop.
    """
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, consultar_novos_shipments_welcome, db)
        print(f"[WELCOME_CRON] Consulta de novos shipments executada em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        print(f"[WELCOME_CRON] Erro na consulta de novos shipments: {e}")


def iniciar_cronjob_boas_vindas(db=None):
    """
    Inicia o cronjob de boas-vindas que roda a cada 10 minutos.

    Este cronjob:
    - Executa a cada 10 minutos (intervalo fixo, configurável via WELCOME_INTERVAL_MINUTES no .env)
    - Respeita o horário de monitoramento configurado
    - Evita colisão com o cronjob principal (não executa se estiver muito próximo)
    - Envia mensagem de boas-vindas para shipments novos

    Returns:
        String com a próxima execução calculada
    """
    sched = get_scheduler()

    # Intervalo configurável via .env (padrão: 10 minutos)
    interval_minutes = int(os.getenv('WELCOME_INTERVAL_MINUTES', 10))

    # Remover job existente (se houver)
    try:
        existing = sched.get_job('welcome_shipments')
        if existing:
            sched.remove_job('welcome_shipments')
            print(f"[WELCOME_CRON] Job anterior removido")
    except Exception as e:
        print(f"[WELCOME_CRON] Não foi possível remover job anterior: {e}")

    # Criar trigger de intervalo simples
    trigger = IntervalTrigger(minutes=interval_minutes, timezone=TZ_UTC)

    # Job que executa as consultas - verifica horário e anti-colisão
    async def _welcome_job(job_db):
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

        print(f"[WELCOME_CRON] ⏰ Job disparado em {_fmt_local(now_utc)} (Brasília: {now_brasilia.strftime('%H:%M')})")
        print(f"[WELCOME_CRON] Range permitido: {start_h_brt:02d}:00 - {end_h_brt:02d}:00 (Brasília)")

        # 0. Verificar se está temporariamente pausado (execução forçada do cron principal)
        if is_welcome_cron_paused():
            print(f"[WELCOME_CRON] ⏸️  PAUSADO: Cronjob pausado temporariamente (execução forçada do principal)")
            return

        # 1. Verificar se está dentro do horário permitido
        if not (start_h_brt <= hour_brasilia < end_h_brt):
            print(f"[WELCOME_CRON] ⏭️  PULANDO: Hora atual {hour_brasilia:02d}:xx fora do range {start_h_brt:02d}:00-{end_h_brt:02d}:00")
            return

        # 2. Verificar anti-colisão com o cronjob principal
        try:
            monitor_job = sched.get_job('monitor_shipments')
            if monitor_job and monitor_job.next_run_time:
                next_monitor = monitor_job.next_run_time
                time_diff = abs((now_utc - next_monitor).total_seconds() / 60)  # diferença em minutos

                # Se estiver a menos de 10 minutos do próximo monitor, pular
                if time_diff < 10:
                    print(f"[WELCOME_CRON] ⏭️  PULANDO: Muito próximo do monitor principal (diferença: {time_diff:.1f} min)")
                    return
        except Exception as e:
            print(f"[WELCOME_CRON] ⚠️  Erro ao verificar anti-colisão: {e}")

        # 3. Executar consulta
        try:
            print(f"[WELCOME_CRON] ✅ Executando consulta de novos shipments...")
            await consultar_novos_shipments_welcome_async(job_db)
        except Exception as e:
            print(f"[WELCOME_CRON] ❌ Erro ao executar consulta: {e}")
            import traceback
            traceback.print_exc()

    try:
        sched.add_job(
            _welcome_job,
            trigger=trigger,
            args=[db],
            id='welcome_shipments',
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
        print(f"[WELCOME_CRON] Cronjob de boas-vindas iniciado (intervalo: {interval_minutes} min)")

        # Exibir próxima execução
        try:
            job = sched.get_job('welcome_shipments')
            if job and job.next_run_time:
                next_run_str = _fmt_local(job.next_run_time)
                print(f"[WELCOME_CRON] Próxima execução: {next_run_str}")
                return next_run_str
        except Exception as e:
            print(f"[WELCOME_CRON] Não foi possível obter próxima execução: {e}")

        return f"Em {interval_minutes} minutos"
    except Exception as e:
        print(f"[WELCOME_CRON] Erro ao iniciar cronjob: {e}")
        return f"Erro: {e}"


def parar_cronjob_boas_vindas():
    """Remove o cronjob de boas-vindas (mantém o scheduler vivo)."""
    try:
        sched = get_scheduler()
        if sched.get_job('welcome_shipments'):
            sched.remove_job('welcome_shipments')
            print("[WELCOME_CRON] Cronjob de boas-vindas parado (job removido)")
        else:
            print("[WELCOME_CRON] Nenhum job de boas-vindas para remover")
    except Exception as e:
        print(f"[WELCOME_CRON] Erro ao parar cronjob: {e}")


def pausar_welcome_cron_temporariamente(minutos: int = 20):
    """
    Pausa temporariamente o cronjob de boas-vindas.
    
    Args:
        minutos: Tempo em minutos para pausar o cronjob
    """
    global _welcome_cron_paused_until
    _welcome_cron_paused_until = datetime.now(TZ_UTC) + timedelta(minutes=minutos)
    logger.info(f"[WELCOME_CRON] Pausado temporariamente até {_welcome_cron_paused_until.isoformat()}")
    return _welcome_cron_paused_until


def is_welcome_cron_paused() -> bool:
    """Verifica se o cronjob de boas-vindas está pausado."""
    global _welcome_cron_paused_until
    if _welcome_cron_paused_until is None:
        return False
    
    now = datetime.now(TZ_UTC)
    if now < _welcome_cron_paused_until:
        return True
    else:
        # Pausa expirou, limpar
        _welcome_cron_paused_until = None
        return False


async def forcar_execucao_cron_principal(db=None):
    """
    Força a execução imediata do cronjob principal de monitoramento.
    Pausa o cronjob de boas-vindas por 20 minutos para evitar colisões.
    
    Returns:
        Dict com resultado da execução
    """
    cron_logger = get_cronjob_logger('monitor_shipments')
    cron_logger.info("=" * 80)
    cron_logger.info("EXECUÇÃO FORÇADA DO CRONJOB PRINCIPAL")
    cron_logger.info("=" * 80)
    
    try:
        # Pausar cronjob de boas-vindas
        paused_until = pausar_welcome_cron_temporariamente(20)
        cron_logger.info(f"Cronjob de boas-vindas pausado até {paused_until.isoformat()}")
        
        # Executar consulta de shipments
        cron_logger.info("Iniciando consulta forçada de shipments...")
        await consultar_shipments_async(db)
        
        cron_logger.info("=" * 80)
        cron_logger.info("EXECUÇÃO FORÇADA CONCLUÍDA COM SUCESSO")
        cron_logger.info("=" * 80)
        
        return {
            "success": True,
            "message": "Cronjob principal executado com sucesso",
            "welcome_cron_paused_until": paused_until.isoformat()
        }
    except Exception as e:
        cron_logger.error(f"Erro ao executar cronjob forçado: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }



