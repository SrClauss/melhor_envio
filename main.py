from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware
from app import renders, api
import rocksdbpy
import bcrypt

app = FastAPI()


# Rota de debug temporária: lista rotas registradas (path + methods)
@app.get("/__routes")
async def _debug_routes():
    routes = []
    for r in app.routes:
        methods = []
        # nem todos os objetos têm .methods (StaticFiles, Mount)
        if hasattr(r, 'methods') and r.methods:
            methods = list(r.methods)
        path = getattr(r, 'path', None) or getattr(r, 'route', None) or str(r)
        routes.append({"path": path, "methods": methods})
    return {"routes": routes}

# Adicionar middleware de sessões
app.add_middleware(SessionMiddleware, secret_key="chave-secreta-temporaria-12345")

# Handler para erro 401 - redirecionar para login
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    if exc.status_code == 401:
        return RedirectResponse(url="/", status_code=303)
    return exc

# Servir arquivos estáticos
app.mount("/img", StaticFiles(directory="templates/img"), name="img")
app.mount("/css", StaticFiles(directory="templates/css"), name="css")

# Criar/abrir banco de dados RocksDB e armazenar em app.state para ser usado por routers
opts = rocksdbpy.Option()
opts.create_if_missing(True)
app.state.db = rocksdbpy.open('database.db', opts)

# Garantir usuário admin existe
it = app.state.db.iterator(mode="start", key=b"user:")
try:
    if it.len() == 0:
        user = "admin"
        password = "admin"
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        app.state.db.put(b"user:" + user.encode('utf-8'), hashed_password)
finally:
    it.close()

# Incluir routers
app.include_router(renders.router)
app.include_router(api.router, prefix='/api')  # Prefixo /api para rotas de API (token, proxy, etc.)