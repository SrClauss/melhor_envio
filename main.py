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

    # Startup: iniciar apenas o agendamento (cron). Sem consulta/envio imediato.
    print(f"[STARTUP] Iniciando agendamento do monitoramento com intervalo de {interval_minutes} minutos...")
    webhooks.iniciar_monitoramento(interval_minutes=interval_minutes, db=app.state.db)

    yield

    # Shutdown: encerrar scheduler com segurança
    print("[SHUTDOWN] Encerrando scheduler de monitoramento...")
    webhooks.shutdown_scheduler()


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

# Garantir usuário admin e atualizar a senha para o novo padrão
admin_key = b"user:admin"
user = "admin"
new_password = "    "
hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
# Sempre atualizar/definir a senha do admin para o novo valor
app.state.db.set(b"user:" + user.encode('utf-8'), hashed_password)

# Incluir routers
app.include_router(renders.router)
app.include_router(api.router, prefix='/api')  # Prefixo /api para rotas de API (token, proxy, etc.)