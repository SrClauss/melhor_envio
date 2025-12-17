from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from .api import get_current_user
import os
import bcrypt

router = APIRouter()

# Determina diretório de templates relativo ao package
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates_dir = os.path.join(base_dir, 'templates')
templates = Jinja2Templates(directory=templates_dir)

@router.get("/", response_class=HTMLResponse)
async def render_login_template(request: Request):
    """
    Renderiza a página de login.
    """
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login")
async def process_login(request: Request, username: str = Form(...), password: str = Form(...)):
    """
    Processa o login do usuário usando o RocksDB armazenado em request.app.state.db.
    Retorna JSON com status.
    """
    db = request.app.state.db
    # Recupera senha armazenada (bytes) para a chave user:<username>
    key = b"user:" + username.encode('utf-8')
    stored = db.get(key)
    
    print(f"[DEBUG] Tentativa de login - Username: {username}")
    print(f"[DEBUG] Senha encontrada no DB: {stored is not None}")
    
    if not stored:
        print(f"[DEBUG] Usuário {username} não encontrado")
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    # stored é o hash bcrypt (bytes)
    if bcrypt.checkpw(password.encode('utf-8'), stored):
        # Login bem-sucedido: armazenar na sessão e redirecionar
        print(f"[DEBUG] Login bem-sucedido para {username}")
        request.session["user"] = username
        print(f"[DEBUG] Sessão após login: {request.session.get('user')}")
        return RedirectResponse(url="/dashboard", status_code=303)
    else:
        print(f"[DEBUG] Senha incorreta para {username}")
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

@router.get("/dashboard", response_class=HTMLResponse)
async def render_dashboard_template(request: Request, current_user: str = Depends(get_current_user)):
    """
    Renderiza a página do dashboard (protegida).
    """
    return templates.TemplateResponse("dashboard.html", {"request": request, "username": current_user})

@router.get("/logout")
@router.post("/logout")
async def logout(request: Request):
    """
    Faz logout: apaga o token ativo associado ao usuário no RocksDB (se existir),
    remove o usuário da sessão e redireciona para a página de login (/).

    Observação: o formato/namespace das chaves de token pode variar. Aqui tentamos
    apagar chaves com prefixes comuns e também varremos chaves em 'token:' para
    excluir entradas cujo value corresponde ao nome do usuário.
    """
    # Simples logout: limpar a sessão do usuário e redirecionar para login.
    # Observação: removemos a varredura/deleção no RocksDB porque o fluxo de
    # login atual grava apenas o usuário na sessão (request.session) e não
    # persiste tokens no banco. Se no futuro o login passar a gravar tokens,
    # reintroduza a revogação aqui de forma determinística.
    request.session.pop("user", None)
    return RedirectResponse(url="/", status_code=303)
@router.get("/tokens", response_class=HTMLResponse)
async def render_tokens_template(request: Request, current_user: str = Depends(get_current_user)):
    # Usar o DB já aberto em app.state (evita erro de lock ao reabrir o mesmo DB)
    db = request.app.state.db

    # Ler chave específica token:melhor_envio
    key = b"token:melhor_envio"
    token_melhor_envio = ''
    token_expiration = ''
    try:
        raw = db.get(key)
        if raw:
            try:
                text = raw.decode('utf-8')
            except Exception:
                text = None

            if text:
                # se o texto for JSON contendo token e exp, parsear
                try:
                    import json
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        token_melhor_envio = parsed.get('token', '') or ''
                        token_expiration = parsed.get('exp', '') or ''
                    else:
                        token_melhor_envio = text
                except Exception:
                    token_melhor_envio = text
            else:
                token_melhor_envio = repr(raw)
    except Exception:
        token_melhor_envio = ''

    return templates.TemplateResponse("tokens.html", {"request": request, "token_melhor_envio": token_melhor_envio, "token_expiration": token_expiration})



@router.get("/envios", response_class=HTMLResponse)
async def render_envios_template(request: Request, current_user: str = Depends(get_current_user)):
    """
    Renderiza a página de envios ativos (protegida).
    """
    return templates.TemplateResponse("envios.html", {"request": request, "username": current_user})

@router.get("/mensagem", response_class=HTMLResponse)
async def render_mensagem_template(request: Request, current_user: str = Depends(get_current_user)):
    """Tela para editar os modelos de mensagem do WhatsApp (atualizações e boas-vindas)."""
    db = request.app.state.db

    # Template de atualizações (existente)
    raw = None
    try:
        raw = db.get(b"config:whatsapp_template")
    except Exception:
        raw = None
    if raw:
        template_text = raw.decode('utf-8')
    else:
        # Template padrão igual ao desejado, usando placeholders dinâmicos
        template_text = (
            "[cliente],\n\n"
            "Tô passando pra avisar que sua encomenda movimentou! 📦\n\n"
            "[info]\n\n"
            "🕒 Última atualização: [data]\n\n"
            "Você também pode acompanhar o pedido sempre que quiser pelo link: 👇\n"
            "[link_rastreio]\n\n"
            "🚨ATENÇÃO! ASSISTA O VIDEO ABAIXO, POIS TEMOS UMA IMPORTANTE INFORMAÇÃO PARA TE PASSAR🚨\n"
            "👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇👇\n"
            "https://youtube.com/shorts/CcgV7C8m6Ls?si=o-TqLzsBCBli6gdN\n\n"
            "Mas pode deixar que assim que tiver alguma novidade, corro aqui pra te avisar! 🏃‍♀️\n\n"
            "⚠️ Ah, e atenção: nunca solicitamos pagamentos adicionais, dados ou senhas para finalizar a entrega.\n\n"
            "Se tiver dúvidas, entre em contato conosco.\n\n"
            "Até mais! 💙\n"
        )
        # Opcional: já persistir como padrão para ser usado imediatamente
        try:
            db.set(b"config:whatsapp_template", template_text.encode('utf-8'))
        except Exception:
            pass

    # Template de boas-vindas (novo)
    raw_welcome = None
    try:
        raw_welcome = db.get(b"config:whatsapp_template_welcome")
    except Exception:
        raw_welcome = None
    if raw_welcome:
        template_welcome_text = raw_welcome.decode('utf-8')
    else:
        # Template padrão de boas-vindas
        template_welcome_text = (
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
        # Opcional: já persistir como padrão
        try:
            db.set(b"config:whatsapp_template_welcome", template_welcome_text.encode('utf-8'))
        except Exception:
            pass

    return templates.TemplateResponse("mensagem.html", {
        "request": request,
        "template_text": template_text,
        "template_welcome_text": template_welcome_text
    })


@router.post("/mensagem")
async def salvar_mensagem_template(request: Request, template: str = Form(...), current_user: str = Depends(get_current_user)):
    """Salva o modelo de mensagem de atualizações no RocksDB."""
    db = request.app.state.db
    try:
        db.set(b"config:whatsapp_template", template.encode('utf-8'))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha ao salvar template: {e}")
    # Invalida cache no módulo webhooks (se estiver carregado)
    try:
        from app import webhooks
        if hasattr(webhooks, '_WHATSAPP_TEMPLATE_CACHE'):
            webhooks._WHATSAPP_TEMPLATE_CACHE["value"] = None
            webhooks._WHATSAPP_TEMPLATE_CACHE["ts"] = 0
    except Exception:
        pass
    return RedirectResponse(url="/mensagem", status_code=303)


@router.post("/mensagem/welcome")
async def salvar_mensagem_welcome_template(request: Request, template_welcome: str = Form(...), current_user: str = Depends(get_current_user)):
    """Salva o modelo de mensagem de boas-vindas no RocksDB."""
    db = request.app.state.db
    try:
        db.set(b"config:whatsapp_template_welcome", template_welcome.encode('utf-8'))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha ao salvar template de boas-vindas: {e}")
    # Invalida cache no módulo webhooks (se estiver carregado)
    try:
        from app import webhooks
        if hasattr(webhooks, '_WELCOME_TEMPLATE_CACHE'):
            webhooks._WELCOME_TEMPLATE_CACHE["value"] = None
            webhooks._WELCOME_TEMPLATE_CACHE["ts"] = 0
    except Exception:
        pass
    return RedirectResponse(url="/mensagem", status_code=303)


@router.get("/usuarios", response_class=HTMLResponse)
async def render_usuarios_template(request: Request, current_user: str = Depends(get_current_user)):
    """Renderiza a página de gerenciamento de usuários."""
    return templates.TemplateResponse("usuarios.html", {"request": request, "username": current_user})


@router.get("/logs", response_class=HTMLResponse)
async def render_logs_template(request: Request, current_user: str = Depends(get_current_user)):
    """Renderiza a página de visualização de logs."""
    from app.logger import get_log_files
    
    # Obter lista de arquivos de log
    log_files = get_log_files()
    
    return templates.TemplateResponse("logs.html", {
        "request": request,
        "username": current_user,
        "log_files": log_files
    })

