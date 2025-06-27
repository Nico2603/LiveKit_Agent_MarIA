"""
Gestor dinámico de TTS para voz adaptativa de María.
Cambia los parámetros de voz según las emociones detectadas del usuario.
"""

import logging
from typing import Optional, Dict, Any, List
from livekit.plugins import cartesia
from livekit.agents import tts

from emotion_detector import EmotionDetector, VoiceProfile
from config import create_settings

class AdaptiveTTSManager:
    """
    Gestor que maneja la adaptación dinámica de la voz de María
    según las emociones detectadas del usuario.
    """
    
    def __init__(self, settings, base_tts_instance: Optional[tts.TTS] = None):
        """
        Inicializa el gestor de TTS adaptativo.
        
        Args:
            settings: Configuración del sistema
            base_tts_instance: Instancia base de TTS a usar como referencia
        """
        self.settings = settings
        self.logger = logging.getLogger(__name__)
        self.emotion_detector = EmotionDetector()
        
        # Instancia de TTS actual
        self._current_tts = base_tts_instance
        self._current_voice_profile = None
        self._last_detected_emotions = {}
        
        # Configuración base de Cartesia
        self.base_config = {
            'api_key': settings.cartesia_api_key,
            'model': settings.cartesia_model,
            'voice': settings.cartesia_voice_id,
            'language': settings.cartesia_language,
            'speed': settings.cartesia_speed,
            'emotion': settings.cartesia_emotion,
        }
        
        self.logger.info("🎭 AdaptiveTTSManager inicializado - Voz adaptativa habilitada")
    
    def get_adaptive_tts(self, user_text: str) -> tts.TTS:
        """
        Obtiene una instancia de TTS adaptada según las emociones detectadas en el texto del usuario.
        
        Args:
            user_text: Texto del usuario para analizar emociones
            
        Returns:
            Instancia de TTS con parámetros ajustados
        """
        if not self.settings.enable_adaptive_voice:
            # Si la voz adaptativa está deshabilitada, usar configuración base
            if not self._current_tts:
                self._current_tts = self._create_base_tts()
            return self._current_tts
        
        # Detectar emociones en el texto del usuario
        detected_emotions = self.emotion_detector.detect_emotions(user_text)
        
        # Obtener perfil de voz adaptativo
        voice_profile = self.emotion_detector.get_adaptive_voice_profile(detected_emotions)
        
        # Verificar si necesitamos crear una nueva instancia de TTS
        if self._should_update_tts(voice_profile, detected_emotions):
            self.logger.info(f"🎭 Adaptando voz: {voice_profile.voice_description}")
            self._current_tts = self._create_adaptive_tts(voice_profile)
            self._current_voice_profile = voice_profile
            self._last_detected_emotions = detected_emotions
        
        return self._current_tts
    
    def _should_update_tts(self, new_profile: VoiceProfile, new_emotions: Dict) -> bool:
        """
        Determina si se necesita actualizar la instancia de TTS.
        
        Args:
            new_profile: Nuevo perfil de voz
            new_emotions: Nuevas emociones detectadas
            
        Returns:
            True si se necesita actualizar la instancia de TTS
        """
        # Si es la primera vez o no hay TTS actual
        if not self._current_tts or not self._current_voice_profile:
            return True
        
        # Si el perfil de voz ha cambiado significativamente
        current_profile = self._current_voice_profile
        
        # Verificar cambios en velocidad (threshold de 0.1)
        speed_changed = abs(new_profile.speed - current_profile.speed) >= 0.1
        
        # Verificar cambios en emociones
        emotions_changed = new_profile.emotion != current_profile.emotion
        
        # Verificar si las emociones detectadas han cambiado
        emotions_different = new_emotions != self._last_detected_emotions
        
        should_update = speed_changed or emotions_changed or emotions_different
        
        if should_update:
            self.logger.debug(f"TTS necesita actualización: speed_changed={speed_changed}, "
                            f"emotions_changed={emotions_changed}, emotions_different={emotions_different}")
        
        return should_update
    
    def _create_base_tts(self) -> tts.TTS:
        """Crea una instancia de TTS con la configuración base."""
        return cartesia.TTS(**self.base_config)
    
    def _create_adaptive_tts(self, voice_profile: VoiceProfile) -> tts.TTS:
        """
        Crea una instancia de TTS adaptada según el perfil de voz.
        
        Args:
            voice_profile: Perfil de voz a aplicar
            
        Returns:
            Nueva instancia de TTS con parámetros adaptados
        """
        # Crear configuración adaptada
        adaptive_config = self.base_config.copy()
        
        # Ajustar velocidad
        adaptive_config['speed'] = voice_profile.speed
        
        # Ajustar emociones si están especificadas
        if voice_profile.emotion:
            adaptive_config['emotion'] = voice_profile.emotion
        
        self.logger.info(f"🎭 Creando TTS adaptativo - Velocidad: {voice_profile.speed}, "
                        f"Emociones: {voice_profile.emotion}")
        
        try:
            return cartesia.TTS(**adaptive_config)
        except Exception as e:
            self.logger.error(f"❌ Error creando TTS adaptativo: {e}")
            self.logger.info("🔄 Usando TTS base como respaldo")
            return self._create_base_tts()
    
    def get_current_voice_description(self) -> str:
        """
        Obtiene una descripción del perfil de voz actual.
        
        Returns:
            Descripción textual del perfil de voz actual
        """
        if self._current_voice_profile:
            return self._current_voice_profile.voice_description
        return "Voz empática y calmada por defecto"
    
    def get_emotion_summary(self) -> str:
        """
        Obtiene un resumen del estado emocional actual.
        
        Returns:
            Resumen del estado emocional detectado
        """
        if self._last_detected_emotions:
            return self.emotion_detector.get_context_summary(self._last_detected_emotions)
        return "Sin emociones detectadas"
    
    def reset_to_default(self):
        """Reinicia el TTS a la configuración por defecto."""
        self.logger.info("🔄 Reiniciando TTS a configuración por defecto")
        self._current_tts = self._create_base_tts()
        self._current_voice_profile = None
        self._last_detected_emotions = {}
    
    def force_voice_profile(self, voice_profile: VoiceProfile):
        """
        Fuerza el uso de un perfil de voz específico.
        
        Args:
            voice_profile: Perfil de voz a aplicar
        """
        self.logger.info(f"🎭 Forzando perfil de voz: {voice_profile.voice_description}")
        self._current_tts = self._create_adaptive_tts(voice_profile)
        self._current_voice_profile = voice_profile

# Función de utilidad para crear el gestor
def create_adaptive_tts_manager(settings=None) -> AdaptiveTTSManager:
    """
    Función de utilidad para crear un gestor de TTS adaptativo.
    
    Args:
        settings: Configuración del sistema (opcional)
        
    Returns:
        Instancia de AdaptiveTTSManager
    """
    if settings is None:
        settings = create_settings()
    
    return AdaptiveTTSManager(settings) 