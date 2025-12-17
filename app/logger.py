"""
Sistema de Logging Centralizado - Melhor Envio
================================================
Módulo para logging estruturado com suporte a rotação de arquivos e múltiplos níveis.

Uso:
    from app.logger import get_logger
    
    logger = get_logger(__name__)
    logger.info("Mensagem informativa")
    logger.error("Erro ocorreu", exc_info=True)
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path


# Diretório para logs - usar /tmp se /app não estiver disponível
LOG_DIR_PREFERRED = Path("/app/logs")
LOG_DIR_FALLBACK = Path("/tmp/melhor_envio_logs")

# Tentar criar diretório preferencial, usar fallback se falhar
try:
    LOG_DIR = LOG_DIR_PREFERRED
    LOG_DIR.mkdir(parents=True, exist_ok=True)
except (PermissionError, FileNotFoundError):
    LOG_DIR = LOG_DIR_FALLBACK
    LOG_DIR.mkdir(parents=True, exist_ok=True)

# Formato de log estruturado
LOG_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)-20s | %(funcName)-25s | %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Nível de log padrão (configurável via ambiente)
DEFAULT_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

# Mapa de loggers criados (cache)
_loggers = {}


def get_logger(name: str, level: str = None) -> logging.Logger:
    """
    Retorna um logger configurado com handlers de arquivo e console.
    
    Args:
        name: Nome do logger (geralmente __name__ do módulo)
        level: Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
               Se None, usa o padrão do ambiente (LOG_LEVEL)
    
    Returns:
        Logger configurado
    
    Example:
        logger = get_logger(__name__)
        logger.info("Aplicação iniciada")
        logger.error("Erro crítico", exc_info=True)
    """
    # Retornar logger do cache se já existe
    if name in _loggers:
        return _loggers[name]
    
    # Criar novo logger
    logger = logging.getLogger(name)
    
    # Determinar nível
    log_level = level or DEFAULT_LEVEL
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    
    # Evitar propagação para root logger
    logger.propagate = False
    
    # Criar formatador
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    
    # Handler para arquivo geral (todos os logs)
    general_log_file = LOG_DIR / "melhor_envio.log"
    general_handler = RotatingFileHandler(
        general_log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    general_handler.setLevel(logging.DEBUG)
    general_handler.setFormatter(formatter)
    logger.addHandler(general_handler)
    
    # Handler para arquivo de erros (apenas ERROR e CRITICAL)
    error_log_file = LOG_DIR / "errors.log"
    error_handler = RotatingFileHandler(
        error_log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)
    
    # Handler para console (stdout) - apenas INFO e acima
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Adicionar ao cache
    _loggers[name] = logger
    
    return logger


def get_cronjob_logger(cronjob_name: str) -> logging.Logger:
    """
    Retorna logger especializado para cronjobs com arquivo dedicado.
    
    Args:
        cronjob_name: Nome do cronjob (ex: 'monitor_shipments', 'welcome_shipments')
    
    Returns:
        Logger configurado com arquivo dedicado para o cronjob
    """
    logger_name = f"cronjob.{cronjob_name}"
    
    # Retornar do cache se já existe
    if logger_name in _loggers:
        return _loggers[logger_name]
    
    # Criar logger
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    
    # Formatador
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    
    # Handler específico para o cronjob
    cronjob_log_file = LOG_DIR / f"cronjob_{cronjob_name}.log"
    cronjob_handler = RotatingFileHandler(
        cronjob_log_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding='utf-8'
    )
    cronjob_handler.setLevel(logging.DEBUG)
    cronjob_handler.setFormatter(formatter)
    logger.addHandler(cronjob_handler)
    
    # Handler para console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Adicionar também ao log geral
    general_log_file = LOG_DIR / "melhor_envio.log"
    general_handler = RotatingFileHandler(
        general_log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8'
    )
    general_handler.setLevel(logging.INFO)
    general_handler.setFormatter(formatter)
    logger.addHandler(general_handler)
    
    # Cache
    _loggers[logger_name] = logger
    
    return logger


def log_execution_time(logger: logging.Logger, operation: str):
    """
    Context manager para logar tempo de execução de operações.
    
    Usage:
        with log_execution_time(logger, "Consulta de shipments"):
            # operação demorada
            pass
    """
    from contextlib import contextmanager
    import time
    
    @contextmanager
    def _timer():
        start = time.time()
        logger.info(f"[INICIO] {operation}")
        try:
            yield
        except Exception as e:
            duration = time.time() - start
            logger.error(f"[ERRO] {operation} - Falhou após {duration:.2f}s: {e}", exc_info=True)
            raise
        else:
            duration = time.time() - start
            logger.info(f"[FIM] {operation} - Concluído em {duration:.2f}s")
    
    return _timer()


def get_log_files():
    """
    Retorna lista de arquivos de log disponíveis.
    
    Returns:
        Lista de dicts com informações dos arquivos de log
    """
    log_files = []
    
    if not LOG_DIR.exists():
        return log_files
    
    for log_file in LOG_DIR.glob("*.log"):
        try:
            stat = log_file.stat()
            log_files.append({
                'name': log_file.name,
                'path': str(log_file),
                'size': stat.st_size,
                'size_mb': round(stat.st_size / (1024 * 1024), 2),
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        except Exception:
            continue
    
    # Ordenar por data de modificação (mais recente primeiro)
    log_files.sort(key=lambda x: x['modified'], reverse=True)
    
    return log_files


def read_log_file(filename: str, lines: int = 100, level_filter: str = None):
    """
    Lê as últimas N linhas de um arquivo de log.
    
    Args:
        filename: Nome do arquivo (ex: 'melhor_envio.log')
        lines: Número de linhas para retornar (padrão: 100)
        level_filter: Filtro de nível (ex: 'ERROR', 'WARNING')
    
    Returns:
        Lista de linhas do log
    """
    log_file = LOG_DIR / filename
    
    if not log_file.exists():
        return []
    
    try:
        # Ler arquivo
        with open(log_file, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
        
        # Filtrar por nível se especificado
        if level_filter:
            all_lines = [line for line in all_lines if f"| {level_filter}" in line]
        
        # Retornar últimas N linhas
        return all_lines[-lines:]
    
    except Exception as e:
        return [f"Erro ao ler arquivo de log: {e}"]


# Logger padrão do módulo
logger = get_logger(__name__)
