from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from .api import get_current_user
import os
import rocksdbpy
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



