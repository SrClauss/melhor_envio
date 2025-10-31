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

    # Após definir o token, fazer uma busca inicial completa dos shipments
    try:
        from app import webhooks
        asyncio.create_task(webhooks.consultar_shipments_async(db))
        print("[TOKEN] Token definido - Iniciando busca inicial de shipments em background")
    except Exception as e:
        print(f"[TOKEN] Erro ao agendar busca inicial: {e}")

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
        webhooks.iniciar_monitoramento(interval_minutes=interval_minutes, db=request.app.state.db)
        return {"message": f"Monitoramento iniciado com intervalo de {interval_minutes} minutos"}
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
        return {
            "running": running,
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
    """
    if interval_minutes < 2 or interval_minutes > 60:
        raise HTTPException(status_code=400, detail="Intervalo deve ser entre 2 e 60 minutos")

    db = request.app.state.db
    key = b"config:interval_minutes"
    db.set(key, str(interval_minutes).encode('utf-8'))

    # Reiniciar o monitoramento com o novo intervalo
    try:
        from app import webhooks
        webhooks.parar_monitoramento()
        webhooks.iniciar_monitoramento(interval_minutes=interval_minutes, db=db)
        print(f"[CONFIG] Intervalo de monitoramento alterado para {interval_minutes} minutos")
    except Exception as e:
        print(f"[CONFIG] Erro ao reiniciar monitoramento: {e}")

    return {"message": f"Intervalo definido para {interval_minutes} minutos"}


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
    Valores esperados: start_hour e end_hour no formato HH:MM.
    """
    try:
        # Validar e converter os horários para o formato correto
        datetime.strptime(start_hour, '%H:%M')
        datetime.strptime(end_hour, '%H:%M')
    except ValueError:
        raise HTTPException(status_code=400, detail="Horas devem estar no formato HH:MM")

    db = request.app.state.db
    db.set(b"config:monitor_start_hour", start_hour.encode('utf-8'))
    db.set(b"config:monitor_end_hour", end_hour.encode('utf-8'))

    # Reiniciar o monitoramento para aplicar imediatamente (se ativo)
    try:
        from app import webhooks
        webhooks.parar_monitoramento()
        webhooks.iniciar_monitoramento(interval_minutes=int(db.get(b"config:interval_minutes") or b"30"), db=db)
    except Exception as e:
        print(f"[CONFIG] Erro ao reiniciar monitoramento após alterar horas: {e}")

    return {"message": f"Horas de monitoramento definidas: {start_hour} - {end_hour}"}


@router.get('/config/monitor_hours')
async def get_monitor_hours(request: Request):
    """Retorna as horas de monitoramento configuradas (start_hour, end_hour)."""
    db = request.app.state.db
    start = db.get(b"config:monitor_start_hour")
    end = db.get(b"config:monitor_end_hour")
    try:
        if start:
            start_hour = start.decode('utf-8')
            # Se for um número inteiro (formato antigo), converter para HH:MM
            try:
                int(start_hour)
                start_hour = f"{int(start_hour):02d}:00"
            except ValueError:
                pass  # Já está no formato HH:MM
        else:
            start_hour = os.getenv('MONITOR_START_HOUR', '06:00')
            
        if end:
            end_hour = end.decode('utf-8')
            # Se for um número inteiro (formato antigo), converter para HH:MM
            try:
                int(end_hour)
                end_hour = f"{int(end_hour):02d}:00"
            except ValueError:
                pass  # Já está no formato HH:MM
        else:
            end_hour = os.getenv('MONITOR_END_HOUR', '18:00')
    except Exception:
        start_hour, end_hour = '06:00', '18:00'

    return {"start_hour": start_hour, "end_hour": end_hour}


