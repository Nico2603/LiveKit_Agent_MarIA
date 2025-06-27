"""
Módulo de carga dinámica de plugins para el agente María.
Permite configurar y cargar diferentes proveedores de STT, LLM, VAD y TTS de forma modular.
"""

import logging
from typing import Optional, Dict, Any, Tuple
from abc import ABC, abstractmethod

# Importar plugins de LiveKit
from livekit.agents import stt, llm, vad, tts
from livekit.plugins import deepgram, openai, silero, cartesia

class PluginConfig:
    """Configuración base para plugins."""
    
    def __init__(self, enabled: bool = True, **kwargs):
        self.enabled = enabled
        self.config = kwargs

class PluginRegistry:
    """
    Registro de plugins disponibles con configuración dinámica.
    Permite agregar, quitar y configurar plugins sin modificar el código principal.
    """
    
    def __init__(self):
        self._stt_providers = {}
        self._llm_providers = {}
        self._vad_providers = {}
        self._tts_providers = {}
        
        # Registrar proveedores por defecto
        self._register_default_providers()
    
    def _register_default_providers(self):
        """Registra los proveedores por defecto disponibles."""
        
        # STT Providers
        self._stt_providers['deepgram'] = {
            'class': deepgram.STT,
            'default_config': {
                'model': 'nova-2',
                'language': 'es',
                'interim_results': True,
                'smart_format': True,
                'punctuate': True,
                'utterance_end_ms': 1000,
                'vad_events': True,
                'endpointing': 300
            }
        }
        
        # LLM Providers
        self._llm_providers['openai'] = {
            'class': openai.LLM,
            'default_config': {
                'model': 'gpt-4o-mini'
            }
        }
        
        # VAD Providers
        self._vad_providers['silero'] = {
            'class': silero.VAD,
            'default_config': {
                'prefix_padding_duration': 0.2,
                'min_silence_duration': 1.5,
                'activation_threshold': 0.4,
                'min_speech_duration': 0.15
            }
        }
        
        # TTS Providers
        self._tts_providers['cartesia'] = {
            'class': cartesia.TTS,
            'default_config': {
                'model': 'sonic-2',
                'voice': '5c5ad5e7-1020-476b-8b91-fdcbe9cc313c',
                'language': 'es',
                'speed': -0.3,  # Más calmada por defecto
                'emotion': None
            }
        }
    
    def register_stt_provider(self, name: str, provider_class, default_config: Dict[str, Any]):
        """Registra un nuevo proveedor de STT."""
        self._stt_providers[name] = {
            'class': provider_class,
            'default_config': default_config
        }
        logging.info(f"📝 Proveedor STT '{name}' registrado")
    
    def register_llm_provider(self, name: str, provider_class, default_config: Dict[str, Any]):
        """Registra un nuevo proveedor de LLM."""
        self._llm_providers[name] = {
            'class': provider_class,
            'default_config': default_config
        }
        logging.info(f"🧠 Proveedor LLM '{name}' registrado")
    
    def register_vad_provider(self, name: str, provider_class, default_config: Dict[str, Any]):
        """Registra un nuevo proveedor de VAD."""
        self._vad_providers[name] = {
            'class': provider_class,
            'default_config': default_config
        }
        logging.info(f"🎤 Proveedor VAD '{name}' registrado")
    
    def register_tts_provider(self, name: str, provider_class, default_config: Dict[str, Any]):
        """Registra un nuevo proveedor de TTS."""
        self._tts_providers[name] = {
            'class': provider_class,
            'default_config': default_config
        }
        logging.info(f"🔊 Proveedor TTS '{name}' registrado")
    
    def get_available_providers(self) -> Dict[str, list]:
        """Obtiene la lista de proveedores disponibles por categoría."""
        return {
            'stt': list(self._stt_providers.keys()),
            'llm': list(self._llm_providers.keys()),
            'vad': list(self._vad_providers.keys()),
            'tts': list(self._tts_providers.keys())
        }
    
    def create_stt_plugin(self, provider: str, settings) -> Optional[stt.STT]:
        """Crea una instancia del plugin STT especificado."""
        if provider not in self._stt_providers:
            logging.error(f"❌ Proveedor STT '{provider}' no encontrado")
            return None
        
        try:
            provider_info = self._stt_providers[provider]
            config = provider_info['default_config'].copy()
            
            # Aplicar configuración específica según el proveedor
            if provider == 'deepgram':
                config.update({
                    'model': getattr(settings, 'deepgram_model', config['model']),
                    'language': 'es'
                })
            
            plugin_class = provider_info['class']
            return plugin_class(**config)
            
        except Exception as e:
            logging.error(f"❌ Error creando plugin STT '{provider}': {e}")
            return None
    
    def create_llm_plugin(self, provider: str, settings) -> Optional[llm.LLM]:
        """Crea una instancia del plugin LLM especificado."""
        if provider not in self._llm_providers:
            logging.error(f"❌ Proveedor LLM '{provider}' no encontrado")
            return None
        
        try:
            provider_info = self._llm_providers[provider]
            config = provider_info['default_config'].copy()
            
            # Aplicar configuración específica según el proveedor
            if provider == 'openai':
                config.update({
                    'model': getattr(settings, 'openai_model', config['model'])
                })
            
            plugin_class = provider_info['class']
            return plugin_class(**config)
            
        except Exception as e:
            logging.error(f"❌ Error creando plugin LLM '{provider}': {e}")
            return None
    
    def create_vad_plugin(self, provider: str, settings) -> Optional[vad.VAD]:
        """Crea una instancia del plugin VAD especificado."""
        if provider not in self._vad_providers:
            logging.error(f"❌ Proveedor VAD '{provider}' no encontrado")
            return None
        
        try:
            provider_info = self._vad_providers[provider]
            config = provider_info['default_config'].copy()
            
            plugin_class = provider_info['class']
            
            # Para Silero VAD, usar el método load
            if provider == 'silero':
                return plugin_class.load(**config)
            else:
                return plugin_class(**config)
                
        except Exception as e:
            logging.error(f"❌ Error creando plugin VAD '{provider}': {e}")
            return None
    
    def create_tts_plugin(self, provider: str, settings) -> Optional[tts.TTS]:
        """Crea una instancia del plugin TTS especificado."""
        if provider not in self._tts_providers:
            logging.error(f"❌ Proveedor TTS '{provider}' no encontrado")
            return None
        
        try:
            provider_info = self._tts_providers[provider]
            config = provider_info['default_config'].copy()
            
            # Aplicar configuración específica según el proveedor
            if provider == 'cartesia':
                config.update({
                    'api_key': getattr(settings, 'cartesia_api_key', ''),
                    'model': getattr(settings, 'cartesia_model', config['model']),
                    'voice': getattr(settings, 'cartesia_voice_id', config['voice']),
                    'language': getattr(settings, 'cartesia_language', config['language']),
                    'speed': getattr(settings, 'cartesia_speed', config['speed']),
                    'emotion': getattr(settings, 'cartesia_emotion', config['emotion'])
                })
            
            plugin_class = provider_info['class']
            return plugin_class(**config)
            
        except Exception as e:
            logging.error(f"❌ Error creando plugin TTS '{provider}': {e}")
            return None

class PluginLoader:
    """
    Cargador de plugins que gestiona la configuración y creación de instancias.
    """
    
    def __init__(self, plugin_config: Optional[Dict[str, Any]] = None):
        self.registry = PluginRegistry()
        self.config = plugin_config or self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Configuración por defecto para los plugins."""
        return {
            'stt': {
                'provider': 'deepgram',
                'enabled': True
            },
            'llm': {
                'provider': 'openai',
                'enabled': True
            },
            'vad': {
                'provider': 'silero',
                'enabled': True
            },
            'tts': {
                'provider': 'cartesia',
                'enabled': True
            }
        }
    
    def load_plugins(self, settings) -> Tuple[Optional[stt.STT], Optional[llm.LLM], Optional[vad.VAD], Optional[tts.TTS]]:
        """
        Carga todos los plugins configurados.
        
        Args:
            settings: Configuración de la aplicación
            
        Returns:
            Tupla con las instancias de los plugins (STT, LLM, VAD, TTS)
        """
        logging.info("🔧 Cargando plugins del agente...")
        
        # Cargar STT
        stt_plugin = None
        if self.config['stt']['enabled']:
            provider = self.config['stt']['provider']
            stt_plugin = self.registry.create_stt_plugin(provider, settings)
            if stt_plugin:
                logging.info(f"✅ Plugin STT cargado: {provider}")
            else:
                logging.error(f"❌ No se pudo cargar plugin STT: {provider}")
        
        # Cargar LLM
        llm_plugin = None
        if self.config['llm']['enabled']:
            provider = self.config['llm']['provider']
            llm_plugin = self.registry.create_llm_plugin(provider, settings)
            if llm_plugin:
                logging.info(f"✅ Plugin LLM cargado: {provider}")
            else:
                logging.error(f"❌ No se pudo cargar plugin LLM: {provider}")
        
        # Cargar VAD
        vad_plugin = None
        if self.config['vad']['enabled']:
            provider = self.config['vad']['provider']
            vad_plugin = self.registry.create_vad_plugin(provider, settings)
            if vad_plugin:
                logging.info(f"✅ Plugin VAD cargado: {provider}")
            else:
                logging.error(f"❌ No se pudo cargar plugin VAD: {provider}")
        
        # Cargar TTS
        tts_plugin = None
        if self.config['tts']['enabled']:
            provider = self.config['tts']['provider']
            tts_plugin = self.registry.create_tts_plugin(provider, settings)
            if tts_plugin:
                logging.info(f"✅ Plugin TTS cargado: {provider}")
            else:
                logging.error(f"❌ No se pudo cargar plugin TTS: {provider}")
        
        # Verificar que se cargaron todos los plugins críticos
        if not all([stt_plugin, llm_plugin, vad_plugin, tts_plugin]):
            missing = []
            if not stt_plugin: missing.append("STT")
            if not llm_plugin: missing.append("LLM")
            if not vad_plugin: missing.append("VAD")
            if not tts_plugin: missing.append("TTS")
            
            logging.warning(f"⚠️ Plugins faltantes: {', '.join(missing)}")
        else:
            logging.info("✅ Todos los plugins cargados exitosamente")
        
        return stt_plugin, llm_plugin, vad_plugin, tts_plugin
    
    def configure_provider(self, plugin_type: str, provider: str, enabled: bool = True):
        """
        Configura un proveedor específico para un tipo de plugin.
        
        Args:
            plugin_type: Tipo de plugin ('stt', 'llm', 'vad', 'tts')
            provider: Nombre del proveedor
            enabled: Si el plugin debe estar habilitado
        """
        if plugin_type not in self.config:
            logging.error(f"❌ Tipo de plugin desconocido: {plugin_type}")
            return
        
        self.config[plugin_type]['provider'] = provider
        self.config[plugin_type]['enabled'] = enabled
        
        logging.info(f"🔧 Configurado {plugin_type} → {provider} ({'habilitado' if enabled else 'deshabilitado'})")
    
    def get_plugin_status(self) -> Dict[str, Any]:
        """Obtiene el estado actual de la configuración de plugins."""
        available = self.registry.get_available_providers()
        
        status = {}
        for plugin_type in ['stt', 'llm', 'vad', 'tts']:
            config = self.config.get(plugin_type, {})
            status[plugin_type] = {
                'provider': config.get('provider', 'none'),
                'enabled': config.get('enabled', False),
                'available_providers': available.get(plugin_type, [])
            }
        
        return status

# Instancia global del cargador de plugins
plugin_loader = PluginLoader() 