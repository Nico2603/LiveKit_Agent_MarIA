"""
Módulo para el manejo global de sesiones HTTP y control de concurrencia.
Implementa pool de conexiones reutilizable y control de back-pressure.
"""

import asyncio
import logging
from typing import Optional
import aiohttp
from contextlib import asynccontextmanager


class HTTPSessionManager:
    """
    Gestor global de sesiones HTTP con pool de conexiones reutilizable.
    Implementa el patrón singleton para reutilizar conexiones.
    """
    
    _instance: Optional['HTTPSessionManager'] = None
    _session: Optional[aiohttp.ClientSession] = None
    _semaphore: Optional[asyncio.Semaphore] = None
    _data_channel_semaphore: Optional[asyncio.Semaphore] = None
    
    def __new__(cls) -> 'HTTPSessionManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def initialize(self, 
                        max_concurrent_requests: int = 50,
                        max_data_channel_concurrent: int = 10,
                        connector_limit: int = 100,
                        connector_limit_per_host: int = 30,
                        timeout_total: int = 30):
        """
        Inicializa el gestor de sesiones HTTP con configuración optimizada.
        
        Args:
            max_concurrent_requests: Máximo número de requests HTTP concurrentes
            max_data_channel_concurrent: Máximo número de operaciones DataChannel concurrentes
            connector_limit: Límite total de conexiones en el pool
            connector_limit_per_host: Límite de conexiones por host
            timeout_total: Timeout total para requests
        """
        if self._session is None:
            # Configurar connector con pool de conexiones optimizado
            connector = aiohttp.TCPConnector(
                limit=connector_limit,
                limit_per_host=connector_limit_per_host,
                keepalive_timeout=60,
                enable_cleanup_closed=True,
                force_close=False,
                ttl_dns_cache=300
            )
            
            # Configurar timeout
            timeout = aiohttp.ClientTimeout(
                total=timeout_total,
                connect=10,
                sock_read=10
            )
            
            # Crear sesión reutilizable
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    'User-Agent': 'MariaAgent/1.0',
                    'Connection': 'keep-alive'
                }
            )
            
            # Semáforos para control de concurrencia
            self._semaphore = asyncio.Semaphore(max_concurrent_requests)
            self._data_channel_semaphore = asyncio.Semaphore(max_data_channel_concurrent)
            
            logging.info(f"✅ HTTPSessionManager inicializado:")
            logging.info(f"   🔗 Pool de conexiones: {connector_limit} total, {connector_limit_per_host} por host")
            logging.info(f"   🚦 Concurrencia HTTP: {max_concurrent_requests}")
            logging.info(f"   📡 Concurrencia DataChannel: {max_data_channel_concurrent}")
            logging.info(f"   ⏱️ Timeout total: {timeout_total}s")
    
    @asynccontextmanager
    async def controlled_request(self, operation_name: str = "http_request"):
        """
        Context manager para controlar la concurrencia de requests HTTP.
        
        Args:
            operation_name: Nombre de la operación para logging
        """
        if self._semaphore is None:
            raise RuntimeError("HTTPSessionManager no ha sido inicializado")
        
        async with self._semaphore:
            logging.debug(f"🚀 {operation_name}: Ejecutando con semáforo HTTP")
            try:
                yield
            finally:
                logging.debug(f"✅ {operation_name}: Semáforo HTTP liberado")
    
    @asynccontextmanager
    async def controlled_data_channel(self, operation_name: str = "data_channel"):
        """
        Context manager para controlar la concurrencia de operaciones DataChannel.
        
        Args:
            operation_name: Nombre de la operación para logging
        """
        if self._data_channel_semaphore is None:
            raise RuntimeError("HTTPSessionManager no ha sido inicializado")
        
        async with self._data_channel_semaphore:
            logging.debug(f"📡 {operation_name}: Ejecutando con semáforo DataChannel")
            try:
                yield
            finally:
                logging.debug(f"✅ {operation_name}: Semáforo DataChannel liberado")
    
    @property
    def session(self) -> aiohttp.ClientSession:
        """
        Retorna la sesión HTTP global reutilizable.
        """
        if self._session is None:
            raise RuntimeError("HTTPSessionManager no ha sido inicializado")
        return self._session
    
    async def close(self):
        """
        Cierra la sesión HTTP y libera recursos.
        """
        if self._session is not None:
            await self._session.close()
            self._session = None
            self._semaphore = None
            self._data_channel_semaphore = None
            logging.info("🔒 HTTPSessionManager cerrado correctamente")


class TimeoutManager:
    """
    Gestor de timeouts y cancelación para operaciones asíncronas.
    """
    
    @staticmethod
    @asynccontextmanager
    async def timeout_shield(timeout_seconds: float, operation_name: str = "operation"):
        """
        Context manager que proporciona timeout con protección para operaciones críticas.
        
        Args:
            timeout_seconds: Tiempo límite en segundos
            operation_name: Nombre de la operación para logging
        """
        try:
            async with asyncio.timeout(timeout_seconds):
                logging.debug(f"⏰ {operation_name}: Iniciado con timeout de {timeout_seconds}s")
                yield
                logging.debug(f"✅ {operation_name}: Completado dentro del timeout")
        except asyncio.TimeoutError:
            logging.warning(f"⏰ {operation_name}: TIMEOUT después de {timeout_seconds}s")
            raise
        except asyncio.CancelledError:
            logging.warning(f"🚫 {operation_name}: CANCELADO")
            raise
        except Exception as e:
            logging.error(f"❌ {operation_name}: ERROR - {e}")
            raise
    
    @staticmethod
    async def cancel_safe_sleep(duration: float, operation_name: str = "sleep"):
        """
        Sleep que puede ser cancelado de forma segura.
        
        Args:
            duration: Duración del sleep en segundos
            operation_name: Nombre de la operación para logging
        """
        try:
            await asyncio.sleep(duration)
        except asyncio.CancelledError:
            logging.debug(f"🚫 {operation_name}: Sleep cancelado después de esperar")
            raise


# Instancia global del gestor
http_session_manager = HTTPSessionManager() 