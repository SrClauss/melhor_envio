import json
import os
from fastapi import APIRouter, Form, Request, HTTPException
from fastapi.responses import RedirectResponse
import requests
from fastapi.responses import JSONResponse
import asyncio
from datetime import datetime

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


