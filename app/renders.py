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



