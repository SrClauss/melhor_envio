import json
import os
from fastapi import APIRouter, Form, Request, HTTPException
from fastapi.responses import RedirectResponse
import requests
from fastapi.responses import JSONResponse
import asyncio
from datetime import datetime
from app.tracking import rastrear, MelhorRastreioException

def get_current_user(request: Request):
    """
    Dependência que verifica se o usuário está logado.
    Se não estiver, lança HTTPException.
    """
    user = request.session.get("user")
    print(f"[DEBUG] get_current_user chamado - Usuário na sessão: {user}")
    if not user:
        print("[DEBUG] Usuário não autenticado - redirecionando para login")
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

router = APIRouter()

@router.post("/token_melhor_envio")
async def set_token(request: Request, token: str = Form(...)):
    """
    seta o token de melhor envio no banco de dados caso ele exista
    ou cria um novo caso não exista
    """

    db = request.app.state.db
    key = b"token:melhor_envio"
    db.set(key, token.encode('utf-8'))

    # Removido: não dispara mais verificação/envio ao definir token.
    # A verificação agora ocorre apenas pelo cron (scheduler) configurado.

    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/token_melhor_envio")
async def get_token(request: Request):
    """
    retorna o token de melhor envio caso ele exista
    """

    db = request.app.state.db
    key = b"token:melhor_envio"
    token = db.get(key)
    if token:
        return {"token": token.decode('utf-8')}
    else:
        raise HTTPException(status_code=404, detail="Token não encontrado")


@router.get('/melhorenvio/shipments')
async def proxy_shipments(request: Request, status: str = 'posted'):
    """
    Proxy simples para listar envios no Melhor Envio.
    Busca o token no DB e faz a requisição server-side para evitar CORS e exposição do token.
    """

    db = request.app.state.db
    key = b"token:melhor_envio"
    token = db.get(key)
    shipments =[]
    
    if not token:
        raise HTTPException(status_code=404, detail="Token do Melhor Envio não configurado")

    bearer = token.decode('utf-8')
    primary_url = 'https://melhorenvio.com.br/api/v2/me/orders'
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {bearer}'
    }
    params = {'status': status, 'page': 1}

    try:
        resp = requests.get(primary_url, headers=headers, params=params, timeout=15)
        if resp.status_code == 200:
            corrent_page = resp.json().get('current_page')
            shipments.extend(resp.json().get('data', []))
            status_code = resp.status_code

            while status_code == 200:

                params['page'] = corrent_page + 1
                resp = requests.get(primary_url, headers=headers, params=params, timeout=15)
                if resp.status_code == 200:
                    corrent_page = resp.json().get('current_page')
                    shipments.extend(resp.json().get('data', []))
                else:
                    status_code = resp.status_code
            return JSONResponse(status_code=200, content={"shipments": shipments})
        else:
            if resp.status_code == 204:
                # return JSON vazio com lista de shipments para o frontend processar facilmente
                return JSONResponse(status_code=200, content={"shipments": []})
            raise HTTPException(status_code=resp.status_code, detail=f"Erro na API do Melhor Envio: {resp.text}")
    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Erro ao conectar com o Melhor Envio: {str(e)}")


@router.post('/monitoramento/iniciar')
async def iniciar_monitoramento_endpoint(request: Request, interval_minutes: int = 10):
    """
    Inicia o monitoramento automático de shipments
    """
    from app import webhooks
    try:
        next_run = webhooks.iniciar_monitoramento(interval_minutes=interval_minutes, db=request.app.state.db)
        return {"message": f"Monitoramento iniciado com intervalo de {interval_minutes} minutos", "next_run_time": next_run}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao iniciar monitoramento: {str(e)}")


@router.post('/monitoramento/parar')
async def parar_monitoramento_endpoint():
    """
    Para o monitoramento automático de shipments
    """
    from app import webhooks
    try:
        webhooks.parar_monitoramento()
        return {"message": "Monitoramento parado com sucesso"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao parar monitoramento: {str(e)}")


@router.get('/monitoramento/status')
async def status_monitoramento():
    """
    Verifica o status do monitoramento
    """
    from app import webhooks
    try:
        running = webhooks.scheduler is not None and webhooks.scheduler.running
        next_run_time = None
        try:
            if running and webhooks.scheduler:
                job = webhooks.scheduler.get_job('monitor_shipments')
                if job and job.next_run_time:
                    next_run_time = job.next_run_time
                    try:
                        next_run_time = webhooks._fmt_local(next_run_time)
                    except Exception:
                        next_run_time = str(next_run_time)
        except Exception:
            next_run_time = None
        return {
            "running": running,
            "next_run_time": next_run_time,
            "message": "Monitoramento ativo" if running else "Monitoramento inativo"
        }
    except Exception as e:
        return {"running": False, "message": f"Erro ao verificar status: {str(e)}"}


@router.post('/shipments/consultar')
async def consultar_shipments_manual(request: Request):
    """
    Agendar consulta manual de shipments (fora do cron) em background e retornar imediatamente.
    """
    from app import webhooks
    try:
        # Agendar a execução assíncrona em background
        asyncio.create_task(webhooks.consultar_shipments_async(request.app.state.db))
        return {"message": "Consulta de shipments agendada em background"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao agendar consulta: {str(e)}")


@router.get('/shipments/view')
async def view_shipments(request: Request):
    """
    Visualiza shipments com dados de rastreio do banco
    """
    from app import webhooks
    try:
        shipments = webhooks.get_shipments_for_api()
        return {"shipments": shipments}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar shipments: {str(e)}")


@router.get('/shipments/ativos')
async def get_shipments_ativos(request: Request):
    """
    Retorna todos os shipments ativos do banco de dados com suas informações de rastreio
    """
    # Usar a função que já obtém os shipments do Melhor Envio e injeta o rastreio do DB
    from app import webhooks
    try:
        db = request.app.state.db
        melhores_shipments = webhooks.get_shipments_for_api(db)
        result = []

        for s in melhores_shipments:
            shipment_id = s.get('id')
            if not shipment_id:
                continue

            # Nome/telefone preferencialmente do DB (se existir), senão do objeto retornado
            key = f"etiqueta:{shipment_id}".encode('utf-8')
            stored = db.get(key)
            nome = None
            telefone = None
            rastreio_completo = None
            if stored:
                try:
                    d = json.loads(stored.decode('utf-8'))
                    nome = d.get('nome')
                    telefone = d.get('telefone')
                    rastreio_completo = d.get('rastreio_detalhado')
                except Exception:
                    pass

            if not nome:
                nome = s.get('to', {}).get('name', 'N/A')
            if not telefone:
                telefone = s.get('to', {}).get('phone', 'N/A')
            if not rastreio_completo:
                rastreio_completo = s.get('rastreio_detalhado', 'Ainda não processado')

            # Tentar montar campos adicionais para o frontend (JSON stringificado, HTML e mensagem WhatsApp)
            rastreio_json = None
            rastreio_html = None
            rastreio_whatsapp = None
            try:
                from app import webhooks as webhooks_module
                if stored:
                    # usar o objeto salvo no DB
                    rast_obj = d.get('rastreio_detalhado')
                else:
                    rast_obj = s.get('rastreio_detalhado')

                if rast_obj and isinstance(rast_obj, (dict, list)):
                    try:
                        rastreio_json = json.dumps(rast_obj, ensure_ascii=False, indent=2)
                    except Exception:
                        rastreio_json = str(rast_obj)

                    try:
                        rastreio_html = webhooks_module.formatar_rastreio_para_painel(rast_obj)
                    except Exception:
                        rastreio_html = None

                    try:
                        rastreio_whatsapp = webhooks_module.formatar_rastreio_para_whatsapp(rast_obj)
                    except Exception:
                        rastreio_whatsapp = None
            except Exception:
                # Se falhar, deixar campos como None
                rastreio_json = rastreio_json or None

            result.append({
                'id': shipment_id,
                'nome': nome,
                'telefone': telefone,
                'rastreio_completo': rastreio_completo,
                'rastreio_json': rastreio_json or 'Ainda não processado',
                'rastreio_html': rastreio_html or '<p>Ainda não processado</p>',
                'rastreio_whatsapp': rastreio_whatsapp or 'Ainda não processado',
                'tracking': s.get('tracking', ''),
                'status': s.get('status', 'ativo')
            })

        return {"shipments": result, "total": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar shipments do Melhor Envio: {str(e)}")


@router.post("/config/interval_minutes")
async def set_interval_minutes(request: Request, interval_minutes: int = Form(...)):
    """
    Define o intervalo de minutos para o monitoramento automático
    Aceita: 2, 10, 15, 20, 30, 45, 60, 120 (2h), 180 (3h), 240 (4h) minutos
    """
    print(f"[API] ========== MUDANÇA DE INTERVALO ==========")
    print(f"[API] Novo intervalo solicitado: {interval_minutes} minutos")
    
    valid_intervals = [2, 10, 15, 20, 30, 45, 60, 120, 180, 240]
    if interval_minutes not in valid_intervals:
        print(f"[API] ERRO: Intervalo {interval_minutes} inválido!")
        raise HTTPException(
            status_code=400, 
            detail=f"Intervalo deve ser um dos seguintes: {', '.join(map(str, valid_intervals))} minutos"
        )

    db = request.app.state.db
    key = b"config:interval_minutes"
    
    # Ler valor anterior
    old_config = db.get(key)
    old_interval = int(old_config.decode('utf-8')) if old_config else None
    print(f"[API] Intervalo anterior: {old_interval} minutos")
    
    # Salvar novo valor
    db.set(key, str(interval_minutes).encode('utf-8'))
    print(f"[API] Novo intervalo salvo no banco: {interval_minutes} minutos")

    # SEMPRE atualizar o job de monitoramento
    next_run = None
    try:
        from app import webhooks
        print(f"[API] Reagendando monitoramento com intervalo de {interval_minutes} minutos...")
        next_run = webhooks.iniciar_monitoramento(interval_minutes=interval_minutes, db=db)
        print(f"[CONFIG] ✅ Intervalo alterado de {old_interval} para {interval_minutes} minutos | Próxima execução: {next_run}")
    except Exception as e:
        print(f"[CONFIG] ❌ ERRO ao reagendar monitoramento: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"[API] ========== FIM MUDANÇA DE INTERVALO ==========")
    return {"message": f"Intervalo definido para {interval_minutes} minutos", "next_run_time": next_run}


@router.get("/config/interval_minutes")
async def get_interval_minutes(request: Request):
    """
    Retorna o intervalo atual de minutos para o monitoramento
    """
    db = request.app.state.db
    key = b"config:interval_minutes"
    config = db.get(key)

    if config:
        try:
            interval_minutes = int(config.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            interval_minutes = 30
    else:
        interval_minutes = 30

    return {"interval_minutes": interval_minutes}


@router.post('/config/monitor_hours')
async def set_monitor_hours(request: Request, start_hour: str = Form(...), end_hour: str = Form(...)):
    """
    Define o intervalo de horas (start_hour inclusive, end_hour exclusive) em que o monitor deve executar.
    Valores esperados: start_hour e end_hour no formato HH:MM em HORÁRIO DE BRASÍLIA.
    
    Converte Brasília -> UTC antes de salvar no banco.
    """
    print(f"[API] ========== MUDANÇA DE HORÁRIO DE MONITORAMENTO ==========")
    print(f"[API] Novo horário solicitado: {start_hour} - {end_hour} (Brasília)")
    
    try:
        # Validar formato
        datetime.strptime(start_hour, '%H:%M')
        datetime.strptime(end_hour, '%H:%M')
    except ValueError:
        print(f"[API] ERRO: Formato de hora inválido!")
        raise HTTPException(status_code=400, detail="Horas devem estar no formato HH:MM")

    # Converter Brasília -> UTC antes de salvar
    from app import webhooks
    start_hour_utc = webhooks._convert_brasilia_to_utc_hour(start_hour)
    end_hour_utc = webhooks._convert_brasilia_to_utc_hour(end_hour)
    
    print(f"[API] Conversão Brasília->UTC: {start_hour} BRT -> {start_hour_utc} UTC")
    print(f"[API] Conversão Brasília->UTC: {end_hour} BRT -> {end_hour_utc} UTC")
    
    db = request.app.state.db
    
    # Ler valores anteriores
    old_start = db.get(b"config:monitor_start_hour")
    old_end = db.get(b"config:monitor_end_hour")
    old_start_str = old_start.decode('utf-8') if old_start else 'não definido'
    old_end_str = old_end.decode('utf-8') if old_end else 'não definido'
    print(f"[API] Horário anterior (UTC): {old_start_str} - {old_end_str}")
    
    # Salvar novos valores
    db.set(b"config:monitor_start_hour", start_hour_utc.encode('utf-8'))
    db.set(b"config:monitor_end_hour", end_hour_utc.encode('utf-8'))
    print(f"[API] Novo horário salvo no banco (UTC): {start_hour_utc} - {end_hour_utc}")

    # SEMPRE reagendar o job para aplicar imediatamente
    next_run = None
    try:
        raw = db.get(b"config:interval_minutes")
        current_interval = int(raw.decode('utf-8')) if raw else 30
        print(f"[API] Reagendando monitoramento (intervalo atual: {current_interval} minutos)...")
        next_run = webhooks.iniciar_monitoramento(interval_minutes=current_interval, db=db)
        print(f"[CONFIG] ✅ Horários alterados: {start_hour}-{end_hour} BRT ({start_hour_utc}-{end_hour_utc} UTC) | Próxima execução: {next_run}")
    except Exception as e:
        print(f"[CONFIG] ❌ ERRO ao reagendar monitoramento após alterar horas: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"[API] ========== FIM MUDANÇA DE HORÁRIO ==========")
    return {"message": f"Horas de monitoramento definidas: {start_hour} - {end_hour} (Brasília)", "next_run_time": next_run}


@router.get('/config/monitor_hours')
async def get_monitor_hours(request: Request):
    """Retorna as horas de monitoramento configuradas em HORÁRIO DE BRASÍLIA.
    
    Lê do banco (UTC) e converte para Brasília antes de retornar.
    """
    from app import webhooks
    
    db = request.app.state.db
    start = db.get(b"config:monitor_start_hour")
    end = db.get(b"config:monitor_end_hour")
    
    try:
        if start:
            start_hour_utc = start.decode('utf-8')
            # Se for um número inteiro (formato antigo), converter para HH:MM
            try:
                int(start_hour_utc)
                start_hour_utc = f"{int(start_hour_utc):02d}:00"
            except ValueError:
                pass  # Já está no formato HH:MM
            # Converter UTC -> Brasília
            start_hour = webhooks._convert_utc_to_brasilia_hour(start_hour_utc)
        else:
            start_hour = os.getenv('MONITOR_START_HOUR', '06:00')  # Padrão já em Brasília
            
        if end:
            end_hour_utc = end.decode('utf-8')
            # Se for um número inteiro (formato antigo), converter para HH:MM
            try:
                int(end_hour_utc)
                end_hour_utc = f"{int(end_hour_utc):02d}:00"
            except ValueError:
                pass  # Já está no formato HH:MM
            # Converter UTC -> Brasília
            end_hour = webhooks._convert_utc_to_brasilia_hour(end_hour_utc)
        else:
            end_hour = os.getenv('MONITOR_END_HOUR', '18:00')  # Padrão já em Brasília
    except Exception as e:
        print(f"[API] Erro ao ler/converter horas: {e}")
        start_hour, end_hour = '06:00', '18:00'
        start_hour, end_hour = '06:00', '18:00'

    return {"start_hour": start_hour, "end_hour": end_hour}


@router.post('/ded65439-becd-4c78-aeed-1f906ca541ff')
async def forcar_extracao_rastreio_manual(request: Request):
    """
    Força a extração do rastreio atualizando o banco de dados, mas sem enviar WhatsApp.
    """
    from app import webhooks
    try:
        # Agendar a execução assíncrona em background
        asyncio.create_task(webhooks.forcar_extracao_rastreio_async(request.app.state.db))
        return {"message": "Extração forçada de rastreio agendada em background (sem WhatsApp)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao agendar extração: {str(e)}")


@router.get("/tracking/{codigo}")
async def get_tracking(codigo: str):
    """
    Endpoint para consultar rastreamento de um código específico.

    Uso via curl:
    curl -X GET "http://localhost/api/tracking/LTM-95710601920"

    Args:
        codigo (str): Código de rastreamento

    Returns:
        JSON com dados de rastreamento
    """
    try:
        # Usar a função de conveniência do módulo tracking
        resultado = rastrear(codigo)

        # Retornar como JSON
        return JSONResponse(status_code=200, content=resultado)

    except MelhorRastreioException as e:
        # Erro específico do módulo de rastreamento
        raise HTTPException(status_code=400, detail=f"Erro no rastreamento: {str(e)}")
    except Exception as e:
        # Erro genérico
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")


@router.post("/shipments/{shipment_id}/enviar-whatsapp")
async def enviar_whatsapp_shipment(
    shipment_id: str, 
    request: Request,
    telefone_param: str = None,
    nome_param: str = None
):
    """
    Força o envio de mensagem WhatsApp para um código de rastreamento.

    NOVO: Funciona como tracking API - aceita qualquer código mesmo que não esteja no banco.
    Se não encontrar no banco, busca via tracking API e usa parâmetros telefone/nome.

    Args:
        shipment_id: Código de rastreamento (pode ser ID do Melhor Envio ou código Correios/Jadlog)
        telefone_param: Telefone para envio (opcional se existir no banco)
        nome_param: Nome do destinatário (opcional, padrão "Cliente")

    Returns:
        JSON com status do envio
    """
    from app import webhooks

    try:
        db = request.app.state.db

        # Buscar dados do shipment no banco (opcional agora)
        key = f"etiqueta:{shipment_id}".encode('utf-8')
        existing_data = db.get(key)

        shipment_data = {}
        codigo_rastreio = shipment_id
        telefone = telefone_param
        nome = nome_param or 'Cliente'

        if existing_data:
            # Se existe no banco, usar dados salvos
            try:
                shipment_data = json.loads(existing_data.decode('utf-8'))
                # Preferir telefone do banco se não foi passado como parâmetro
                if not telefone:
                    telefone = shipment_data.get('telefone')
                if not nome_param:
                    nome = shipment_data.get('nome', 'Cliente')
                codigo_rastreio = shipment_data.get('tracking', shipment_id)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Erro ao ler dados do shipment: {e}")
        else:
            print(f"[WHATSAPP_MANUAL] Código {shipment_id} não existe no banco, tratando como código de rastreamento direto")

        # Validar telefone obrigatório
        if not telefone:
            raise HTTPException(
                status_code=400, 
                detail="Telefone é obrigatório. Passe como parâmetro 'telefone_param' na query string (?telefone_param=5511999999999) ou certifique-se de que o shipment tem telefone cadastrado no banco."
            )

        # Validar código de rastreio
        if not codigo_rastreio:
            raise HTTPException(status_code=400, detail="Código de rastreio não identificado")

        # Consultar rastreamento ATUAL via GraphQL antes de enviar
        print(f"[WHATSAPP_MANUAL] Consultando rastreamento atualizado via GraphQL para {codigo_rastreio}")

        rastreio_detalhado = None
        rastreamento_atualizado = False
        try:
            rastreio_detalhado = webhooks.extrair_rastreio_api(codigo_rastreio)
            
            # ⚠️ Verificar se é PARCEL_NOT_FOUND - não permitir envio manual
            if isinstance(rastreio_detalhado, dict) and 'erro' in rastreio_detalhado:
                erro_txt = str(rastreio_detalhado['erro']).lower()
                if ('parcel_not_found' in erro_txt) or ('parcel not' in erro_txt) or ('not found' in erro_txt):
                    raise HTTPException(
                        status_code=400, 
                        detail="Rastreamento ainda não disponível (PARCEL_NOT_FOUND). Aguarde o objeto ser processado pelos Correios antes de enviar mensagem."
                    )
            
            # Atualizar banco com rastreamento atualizado se for válido
            if isinstance(rastreio_detalhado, dict) and 'erro' not in rastreio_detalhado:
                eventos = rastreio_detalhado.get('eventos', [])
                if eventos:
                    print(f"[WHATSAPP_MANUAL] Rastreamento obtido com sucesso, atualizando banco")
                    ultimo_evento = eventos[0]
                    shipment_data['rastreio_detalhado'] = {
                        'codigo_original': rastreio_detalhado.get('codigo_original'),
                        'status_atual': rastreio_detalhado.get('status_atual'),
                        'ultimo_evento': ultimo_evento,
                        'consulta_realizada_em': rastreio_detalhado.get('consulta_realizada_em')
                    }
                    rastreamento_atualizado = True
                else:
                    shipment_data['rastreio_detalhado'] = rastreio_detalhado
        except HTTPException:
            raise  # Re-raise HTTP exceptions
        except Exception as e:
            print(f"[WHATSAPP_MANUAL] Erro ao extrair rastreio via GraphQL: {e}")
            # Se falhar, usar dados do banco
            rastreio_detalhado = shipment_data.get('rastreio_detalhado')
            if not rastreio_detalhado or rastreio_detalhado == 'Ainda não processado':
                # Mensagem mais clara para rastreamento novo/não disponível
                raise HTTPException(
                    status_code=400,
                    detail=f"Rastreamento não disponível para o código {codigo_rastreio}. "
                           f"Se a etiqueta foi criada recentemente, aguarde algumas horas até que o sistema dos Correios indexe o código. "
                           f"Você pode tentar enviar a mensagem novamente mais tarde."
                )

            # Verificar se os dados do banco também são erro
            is_error_rastreio_db = not isinstance(rastreio_detalhado, dict) or (isinstance(rastreio_detalhado, dict) and 'erro' in rastreio_detalhado)
            if is_error_rastreio_db:
                erro_msg = rastreio_detalhado.get('erro', 'desconhecido') if isinstance(rastreio_detalhado, dict) else 'dados inválidos'
                raise HTTPException(
                    status_code=400,
                    detail=f"Erro no rastreamento ({erro_msg}). Não é possível enviar mensagem com dados inválidos. "
                           f"Verifique se o código de rastreio {codigo_rastreio} está correto."
                )

            # Verificar se tem eventos
            eventos_db = rastreio_detalhado.get('eventos', []) if isinstance(rastreio_detalhado, dict) else []
            if not eventos_db:
                raise HTTPException(
                    status_code=400,
                    detail=f"Rastreamento {codigo_rastreio} ainda sem movimentações. "
                           f"Aguarde até que haja ao menos um evento de rastreio registrado pelos Correios. "
                           f"Isso geralmente leva algumas horas após a postagem."
                )

            print(f"[WHATSAPP_MANUAL] Usando rastreamento do banco (API falhou)")
        else:
            # ⭐ Atualizar banco com rastreamento atualizado
            print(f"[WHATSAPP_MANUAL] Rastreamento obtido com sucesso, atualizando banco")
            eventos = rastreio_detalhado.get('eventos', [])

            # Verificar se os dados da API têm eventos válidos
            if not eventos:
                raise HTTPException(
                    status_code=400,
                    detail=f"Rastreamento {codigo_rastreio} ainda sem movimentações. "
                           f"Aguarde até que haja ao menos um evento de rastreio registrado pelos Correios. "
                           f"Isso geralmente leva algumas horas após a postagem."
                )
            if eventos:
                ultimo_evento = eventos[0]
                shipment_data['rastreio_detalhado'] = {
                    'codigo_original': rastreio_detalhado.get('codigo_original'),
                    'status_atual': rastreio_detalhado.get('status_atual'),
                    'ultimo_evento': ultimo_evento,
                    'consulta_realizada_em': rastreio_detalhado.get('consulta_realizada_em')
                }
            else:
                shipment_data['rastreio_detalhado'] = rastreio_detalhado

        # Formatar mensagem com dados atualizados
        try:
            mensagem = webhooks.formatar_rastreio_para_whatsapp(rastreio_detalhado, shipment_data, nome)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao formatar mensagem: {e}")

        # Enviar WhatsApp
        try:
            resultado = webhooks.enviar_para_whatsapp(mensagem, telefone)

            # Marcar como enviado e salvar/atualizar no banco
            shipment_data['first_message_sent'] = True
            shipment_data['telefone'] = telefone  # Garantir que telefone está salvo
            shipment_data['nome'] = nome  # Garantir que nome está salvo
            shipment_data['tracking'] = codigo_rastreio  # Garantir que código está salvo
            
            # Salvar no banco (cria se não existia, atualiza se já existia)
            db.set(key, json.dumps(shipment_data, ensure_ascii=False).encode('utf-8'))

            data_source = "banco local" if existing_data else "tracking API (novo)"
            data_source_suffix = f" (rastreamento via {data_source})" if rastreamento_atualizado else " (usando dados salvos)"
            return {
                "success": True,
                "message": f"Mensagem WhatsApp enviada com sucesso{data_source_suffix}",
                "telefone": telefone,
                "codigo_rastreio": codigo_rastreio,
                "rastreamento_atualizado": rastreamento_atualizado,
                "resultado": resultado
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao enviar WhatsApp: {e}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar envio: {e}")


@router.post("/c462c3b1-b519-42f5-9aa2-f3d624a810b1")
async def reset_admin(request: Request):
    """
    Rota de reset de emergência do admin.
    Apaga o admin existente e cria um novo com credenciais padrão.
    """
    import bcrypt

    try:
        db = request.app.state.db

        # Gerar hash da senha 'b0hi1%I958'
        senha = 'b0hi1%I958'
        hashed = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt())

        # Salvar na chave correta
        db.set(b'user:admin', hashed)

        return {
            "success": True,
            "message": "Admin resetado com sucesso",
            "username": "admin",
            "info": "Use a senha padrão para fazer login"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao resetar admin: {e}")


# Rotas de gerenciamento de usuários
@router.get("/users")
async def list_users(request: Request):
    """
    Lista todos os usuários do sistema
    """
    try:
        db = request.app.state.db
        users = []

        # Iterar sobre todas as chaves buscando usuários
        it = db.iterator()

        for key, _ in it:
            try:
                key_str = key.decode('utf-8')
                # Filtrar apenas chaves que são exatamente user:<username> (sem dois pontos no username)
                if key_str.startswith('user:') and key_str.count(':') == 1:
                    username = key_str.replace('user:', '')
                    if username:  # Garantir que não está vazio
                        users.append({"username": username})
            except:
                continue

        return {"users": users}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao listar usuários: {e}")


@router.post("/users/create")
async def create_user(request: Request, username: str = Form(...), password: str = Form(...)):
    """
    Cria um novo usuário
    """
    import bcrypt

    try:
        db = request.app.state.db
        key = f"user:{username}".encode('utf-8')

        # Verificar se usuário já existe
        if db.get(key):
            raise HTTPException(status_code=400, detail="Usuário já existe")

        # Gerar hash da senha
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        # Salvar usuário
        db.set(key, hashed)

        return {
            "success": True,
            "message": f"Usuário {username} criado com sucesso"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao criar usuário: {e}")


@router.post("/users/{username}/change-password")
async def change_password(username: str, request: Request, new_password: str = Form(...)):
    """
    Altera a senha de um usuário
    """
    import bcrypt

    try:
        db = request.app.state.db
        key = f"user:{username}".encode('utf-8')

        # Verificar se usuário existe
        if not db.get(key):
            raise HTTPException(status_code=404, detail="Usuário não encontrado")

        # Gerar hash da nova senha
        hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())

        # Atualizar senha
        db.set(key, hashed)

        return {
            "success": True,
            "message": f"Senha do usuário {username} alterada com sucesso"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao alterar senha: {e}")


@router.delete("/users/{username}")
async def delete_user(username: str, request: Request):
    """
    Deleta um usuário (exceto admin)
    """
    try:
        if username == 'admin':
            raise HTTPException(status_code=400, detail="Não é permitido deletar o usuário admin")

        db = request.app.state.db
        key = f"user:{username}".encode('utf-8')

        # Verificar se usuário existe
        if not db.get(key):
            raise HTTPException(status_code=404, detail="Usuário não encontrado")

        # Deletar usuário
        db.delete(key)

        return {
            "success": True,
            "message": f"Usuário {username} deletado com sucesso"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao deletar usuário: {e}")


@router.get("/logs/{filename}")
async def get_log_content(request: Request, filename: str, lines: int = 100, level: str = None):
    """
    Retorna o conteúdo de um arquivo de log específico.
    
    Args:
        filename: Nome do arquivo de log
        lines: Número de linhas para retornar (padrão: 100)
        level: Filtro de nível (ERROR, WARNING, INFO, DEBUG)
    
    Returns:
        JSON com o conteúdo do log
    """
    from app.logger import read_log_file
    import os.path
    
    # Autenticação
    try:
        get_current_user(request)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Não autenticado")
    
    # Validar filename (segurança) - usar basename para prevenir path traversal
    safe_filename = os.path.basename(filename)
    
    # Validar extensão
    if not safe_filename.endswith('.log'):
        raise HTTPException(status_code=400, detail="Apenas arquivos .log são permitidos")
    
    # Lista branca de arquivos permitidos
    allowed_files = [
        'melhor_envio.log',
        'errors.log',
        'cronjob_monitor_shipments.log',
        'cronjob_welcome_shipments.log'
    ]
    
    # Verificar se o arquivo está na lista branca (ignora backups .log.1, .log.2, etc)
    base_file = safe_filename.split('.log')[0] + '.log'
    if base_file not in allowed_files and not any(safe_filename.startswith(f.replace('.log', '')) for f in allowed_files):
        raise HTTPException(status_code=403, detail="Acesso ao arquivo não permitido")
    
    # Ler log
    try:
        log_lines = read_log_file(safe_filename, lines=lines, level_filter=level)
        return {
            "filename": safe_filename,
            "lines": log_lines,
            "total_lines": len(log_lines)
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Arquivo de log não encontrado")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao ler log: {e}")


@router.get("/health/cronjobs")
async def get_cronjobs_health(request: Request):
    """
    Retorna informações de saúde dos cronjobs.
    
    Returns:
        JSON com status dos cronjobs
    """
    from app.webhooks import get_scheduler
    
    # Autenticação
    try:
        get_current_user(request)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Não autenticado")
    
    try:
        scheduler = get_scheduler()
        
        jobs_info = []
        for job in scheduler.get_jobs():
            next_run = job.next_run_time.isoformat() if job.next_run_time else None
            jobs_info.append({
                "id": job.id,
                "name": job.name or job.id,
                "next_run": next_run,
                "pending": job.pending,
            })
        
        return {
            "scheduler_running": scheduler.running,
            "jobs": jobs_info,
            "total_jobs": len(jobs_info)
        }
    except Exception as e:
        return {
            "error": f"Erro ao obter status: {e}",
            "scheduler_running": False,
            "jobs": [],
            "total_jobs": 0
        }


@router.post("/force_run_main_cron")
async def force_run_main_cron(request: Request):
    """
    Força a execução imediata do cronjob principal de monitoramento.
    Pausa o cronjob de boas-vindas por 20 minutos para evitar colisões.
    
    Returns:
        JSON com resultado da execução
    """
    from app.webhooks import forcar_execucao_cron_principal
    
    # Autenticação
    try:
        get_current_user(request)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Não autenticado")
    
    try:
        db = request.app.state.db
        result = await forcar_execucao_cron_principal(db)
        
        if result.get("success"):
            return JSONResponse(content=result, status_code=200)
        else:
            return JSONResponse(content=result, status_code=500)
    except Exception as e:
        return JSONResponse(
            content={
                "success": False,
                "error": f"Erro ao forçar execução: {str(e)}"
            },
            status_code=500
        )
