from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware
from contextlib import asynccontextmanager
from app import renders, api, webhooks
import rocksdbpy
import bcrypt
import asyncio
import time


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ler configuração do interval_minutes do banco de dados
    interval_config = app.state.db.get(b"config:interval_minutes")
    if interval_config:
        try:
            interval_minutes = int(interval_config.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            interval_minutes = 30  # fallback para 30 se houver erro
    else:
        interval_minutes = 30  # padrão se não existir configuração

    # Startup: iniciar monitoramento automático e agendar atualização de envios em background
    print(f"[STARTUP] Iniciando monitoramento de shipments com intervalo de {interval_minutes} minutos...")
    webhooks.iniciar_monitoramento(interval_minutes=interval_minutes, db=app.state.db)

    # Agendar a atualização inicial sem bloquear o loop
    try:
        asyncio.create_task(webhooks.consultar_shipments_async(app.state.db))
    except Exception as e:
        print(f"[DEBUG] Erro ao agendar atualização inicial: {e}")

    yield

    # Shutdown: parar monitoramento
    print("[SHUTDOWN] Parando monitoramento de shipments...")
    webhooks.parar_monitoramento()


app = FastAPI(lifespan=lifespan)

# Adicionar middleware de sessões
app.add_middleware(SessionMiddleware, secret_key="chave-secreta-temporaria-12345")

# Handler para erro 401 - redirecionar para login
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    if exc.status_code == 401:
        return RedirectResponse(url="/", status_code=303)
    raise exc

# Servir arquivos estáticos
app.mount("/img", StaticFiles(directory="templates/img"), name="img")
app.mount("/css", StaticFiles(directory="templates/css"), name="css")

# Criar/abrir banco de dados RocksDB e armazenar em app.state para ser usado por routers
opts = rocksdbpy.Option()
opts.create_if_missing(True)


def abrir_banco_de_dados(max_retries: int = 8, base_sleep: float = 0.5):
    """Tenta abrir o banco de dados RocksDB com retries.

    Em ambiente de desenvolvimento o reloader do Uvicorn pode
    provocar múltiplos processos tentando abrir o DB simultaneamente
    (causando erro de LOCK). Aqui fazemos retries com backoff simples
    e mensagens de diagnóstico.
    """
    for tentativa in range(1, max_retries + 1):
        try:
            return rocksdbpy.open('database.db', opts)
        except Exception as e:
            msg = str(e)
            print(f"Tentativa {tentativa}: Falha ao abrir o banco de dados. Erro: {msg}")

            # Se for erro de LOCK, aguardar um pouco e tentar novamente
            if 'lock' in msg.lower() or 'resource temporarily unavailable' in msg.lower():
                sleep_for = base_sleep * tentativa
                print(f"Arquivo LOCK detectado — esperando {sleep_for:.1f}s antes de tentar novamente...")
                time.sleep(sleep_for)
                continue

            # Para outros erros, também espera um pouco e tenta novamente, mas é provável que falhe
            time.sleep(base_sleep)

    raise Exception(
        "Não foi possível abrir o banco de dados após várias tentativas. "
        "Se você estiver executando com --reload, pare o processo anterior ou rode sem reload. "
        "Se não houver outro processo usando o DB, verifique/remova o arquivo database.db/LOCK com cuidado."
    )

app.state.db = abrir_banco_de_dados()

# Garantir usuário admin existe
admin_key = b"user:admin"
if app.state.db.get(admin_key) is None:
    user = "admin"
    password = "admin"
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    app.state.db.set(b"user:" + user.encode('utf-8'), hashed_password)

# Incluir routers
app.include_router(renders.router)
app.include_router(api.router, prefix='/api')  # Prefixo /api para rotas de API (token, proxy, etc.)