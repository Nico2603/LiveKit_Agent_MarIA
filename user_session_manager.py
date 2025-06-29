"""
Gestor de sesiones de usuario para SaaS multi-tenant.
Maneja rate limiting, tracking de uso, y separación de recursos por usuario.
"""

import asyncio
import logging
from typing import Dict, Optional, Set, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict
import json

@dataclass
class UserSession:
    """Información de sesión de usuario"""
    user_id: str
    chat_session_id: str
    participant_identity: str
    started_at: datetime
    last_activity: datetime
    message_count: int = 0
    is_active: bool = True
    
    def update_activity(self):
        """Actualiza la última actividad del usuario"""
        self.last_activity = datetime.now()
    
    def increment_message_count(self):
        """Incrementa el contador de mensajes"""
        self.message_count += 1
        self.update_activity()

@dataclass
class UserQuota:
    """Cuotas y límites de usuario"""
    user_id: str
    daily_messages: int = 0
    concurrent_sessions: int = 0
    last_reset: datetime = field(default_factory=datetime.now)
    is_blocked: bool = False
    block_reason: Optional[str] = None

class UserSessionManager:
    """
    Gestor de sesiones de usuario para aplicaciones SaaS.
    Maneja rate limiting, tracking de uso, y separación de recursos.
    """
    
    def __init__(self, settings):
        self.settings = settings
        self.active_sessions: Dict[str, UserSession] = {}  # participant_identity -> UserSession
        self.user_quotas: Dict[str, UserQuota] = {}  # user_id -> UserQuota
        self.user_sessions_map: Dict[str, Set[str]] = defaultdict(set)  # user_id -> {participant_identities}
        self.cleanup_task: Optional[asyncio.Task] = None
        
        # Iniciar tarea de limpieza
        if self.settings.cleanup_inactive_sessions_minutes > 0:
            self.cleanup_task = asyncio.create_task(self._cleanup_inactive_sessions())
    
    async def register_user_session(self, user_id: str, chat_session_id: str, 
                                  participant_identity: str) -> Tuple[bool, Optional[str]]:
        """
        Registra una nueva sesión de usuario.
        
        Returns:
            Tuple[bool, Optional[str]]: (success, error_message)
        """
        try:
            # Verificar cuotas del usuario
            quota = self.get_user_quota(user_id)
            
            # Verificar si el usuario está bloqueado
            if quota.is_blocked:
                return False, f"Usuario bloqueado: {quota.block_reason}"
            
            # Verificar límite de sesiones concurrentes
            if quota.concurrent_sessions >= self.settings.max_concurrent_sessions_per_user:
                return False, f"Límite de sesiones concurrentes alcanzado ({self.settings.max_concurrent_sessions_per_user})"
            
            # Verificar límite de mensajes diarios
            if quota.daily_messages >= self.settings.max_daily_messages_per_user:
                return False, f"Límite de mensajes diarios alcanzado ({self.settings.max_daily_messages_per_user})"
            
            # Crear nueva sesión
            session = UserSession(
                user_id=user_id,
                chat_session_id=chat_session_id,
                participant_identity=participant_identity,
                started_at=datetime.now(),
                last_activity=datetime.now()
            )
            
            # Registrar sesión
            self.active_sessions[participant_identity] = session
            self.user_sessions_map[user_id].add(participant_identity)
            quota.concurrent_sessions += 1
            
            logging.info(f"🆕 Usuario {user_id} registrado: sesión {chat_session_id} ({participant_identity})")
            return True, None
            
        except Exception as e:
            logging.error(f"❌ Error registrando sesión de usuario {user_id}: {e}")
            return False, str(e)
    
    async def unregister_user_session(self, participant_identity: str) -> bool:
        """
        Desregistra una sesión de usuario.
        
        Returns:
            bool: True si se desregistró exitosamente
        """
        try:
            session = self.active_sessions.get(participant_identity)
            if not session:
                return False
            
            user_id = session.user_id
            
            # Remover de estructuras de datos
            del self.active_sessions[participant_identity]
            self.user_sessions_map[user_id].discard(participant_identity)
            
            # Actualizar cuotas
            quota = self.get_user_quota(user_id)
            quota.concurrent_sessions = max(0, quota.concurrent_sessions - 1)
            
            # Calcular duración de sesión
            duration = datetime.now() - session.started_at
            
            logging.info(f"🔚 Usuario {user_id} desregistrado: sesión {session.chat_session_id} "
                       f"(duración: {duration.total_seconds():.1f}s, mensajes: {session.message_count})")
            
            return True
            
        except Exception as e:
            logging.error(f"❌ Error desregistrando sesión {participant_identity}: {e}")
            return False
    
    def get_user_session(self, participant_identity: str) -> Optional[UserSession]:
        """Obtiene información de sesión de usuario"""
        return self.active_sessions.get(participant_identity)
    
    def get_user_quota(self, user_id: str) -> UserQuota:
        """Obtiene las cuotas de usuario, creando una nueva si no existe"""
        if user_id not in self.user_quotas:
            self.user_quotas[user_id] = UserQuota(user_id=user_id)
        return self.user_quotas[user_id]
    
    async def increment_user_message(self, participant_identity: str) -> Tuple[bool, Optional[str]]:
        """
        Incrementa el contador de mensajes de usuario.
        
        Returns:
            Tuple[bool, Optional[str]]: (allowed, error_message)
        """
        session = self.get_user_session(participant_identity)
        if not session:
            return False, "Sesión no encontrada"
        
        quota = self.get_user_quota(session.user_id)
        
        # Resetear contador diario si es necesario
        if self._should_reset_daily_quota(quota):
            quota.daily_messages = 0
            quota.last_reset = datetime.now()
        
        # Verificar límite de mensajes diarios
        if quota.daily_messages >= self.settings.max_daily_messages_per_user:
            return False, f"Límite de mensajes diarios alcanzado ({self.settings.max_daily_messages_per_user})"
        
        # Incrementar contadores
        session.increment_message_count()
        quota.daily_messages += 1
        
        return True, None
    
    def _should_reset_daily_quota(self, quota: UserQuota) -> bool:
        """Verifica si se debe resetear la cuota diaria"""
        now = datetime.now()
        return (now - quota.last_reset).days >= 1
    
    async def _cleanup_inactive_sessions(self):
        """Tarea de limpieza de sesiones inactivas"""
        cleanup_interval = 60  # Verificar cada minuto
        
        while True:
            try:
                await asyncio.sleep(cleanup_interval)
                
                now = datetime.now()
                inactive_threshold = timedelta(minutes=self.settings.cleanup_inactive_sessions_minutes)
                
                # Encontrar sesiones inactivas
                inactive_sessions = []
                for identity, session in self.active_sessions.items():
                    if now - session.last_activity > inactive_threshold:
                        inactive_sessions.append(identity)
                
                # Limpiar sesiones inactivas
                for identity in inactive_sessions:
                    await self.unregister_user_session(identity)
                    logging.info(f"🧹 Sesión inactiva limpiada: {identity}")
                
                if inactive_sessions:
                    logging.info(f"🧹 {len(inactive_sessions)} sesiones inactivas limpiadas")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"❌ Error en limpieza de sesiones: {e}")
    
    def get_user_stats(self, user_id: str) -> Dict:
        """Obtiene estadísticas de usuario"""
        quota = self.get_user_quota(user_id)
        active_sessions = len(self.user_sessions_map.get(user_id, set()))
        
        return {
            "user_id": user_id,
            "active_sessions": active_sessions,
            "daily_messages": quota.daily_messages,
            "max_concurrent_sessions": self.settings.max_concurrent_sessions_per_user,
            "max_daily_messages": self.settings.max_daily_messages_per_user,
            "is_blocked": quota.is_blocked,
            "block_reason": quota.block_reason,
            "last_reset": quota.last_reset.isoformat()
        }
    
    def get_system_stats(self) -> Dict:
        """Obtiene estadísticas del sistema"""
        total_active_sessions = len(self.active_sessions)
        total_users = len(self.user_quotas)
        
        return {
            "total_active_sessions": total_active_sessions,
            "total_users": total_users,
            "memory_usage": {
                "active_sessions": len(self.active_sessions),
                "user_quotas": len(self.user_quotas),
                "user_sessions_map": len(self.user_sessions_map)
            }
        }
    
    async def block_user(self, user_id: str, reason: str):
        """Bloquea un usuario"""
        quota = self.get_user_quota(user_id)
        quota.is_blocked = True
        quota.block_reason = reason
        
        # Desconectar todas las sesiones activas del usuario
        user_sessions = list(self.user_sessions_map.get(user_id, set()))
        for identity in user_sessions:
            await self.unregister_user_session(identity)
        
        logging.warning(f"🚫 Usuario {user_id} bloqueado: {reason}")
    
    async def unblock_user(self, user_id: str):
        """Desbloquea un usuario"""
        quota = self.get_user_quota(user_id)
        quota.is_blocked = False
        quota.block_reason = None
        
        logging.info(f"✅ Usuario {user_id} desbloqueado")
    
    async def close(self):
        """Cierra el gestor y limpia recursos"""
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        
        logging.info("🔒 UserSessionManager cerrado correctamente")

# Instancia global del gestor
user_session_manager: Optional[UserSessionManager] = None

def get_user_session_manager(settings) -> UserSessionManager:
    """Factory function para obtener la instancia global del gestor"""
    global user_session_manager
    if user_session_manager is None:
        user_session_manager = UserSessionManager(settings)
    return user_session_manager 