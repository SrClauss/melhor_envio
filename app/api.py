from fastapi import APIRouter, Form, Request, HTTPException
from fastapi.responses import RedirectResponse
import bcrypt

import requests
from fastapi.responses import JSONResponse

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

@router.post("/token_melhor_envio")
async def set_token(request: Request, token: str = Form(...)):
    """
    seta o token de melhor envio no banco de dados caso ele exista
    ou cria um novo caso não exista
    """

    db = request.app.state.db
    key = b"token:melhor_envio"
    db.set(key, token.encode('utf-8'))

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


        
            
   
          
