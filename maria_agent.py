"""
Módulo principal del agente de voz María.
Contiene la lógica principal del agente, procesamiento de mensajes y manejo de eventos.
"""

import asyncio
import json
import uuid
import time
import logging
from typing import Optional, Dict, Any, Tuple
from pathlib import Path

import aiohttp
from livekit.agents import Agent, AgentSession, llm
from livekit.rtc import RemoteParticipant, Room

# Importar módulos locales
from config import SAVE_MESSAGE_MAX_RETRIES, SAVE_MESSAGE_RETRY_DELAY, DEFAULT_DATA_PUBLISH_TIMEOUT, PERFORMANCE_CONFIG
from throttler import message_throttler
from text_utils import clean_text_for_tts, detect_natural_closing_message, generate_welcome_message
from http_session_manager import http_session_manager, TimeoutManager

# Cargar la plantilla del prompt del sistema desde el archivo
try:
    PROMPT_FILE_PATH = Path(__file__).parent / "maria_system_prompt.txt"
    MARIA_SYSTEM_PROMPT_TEMPLATE = PROMPT_FILE_PATH.read_text(encoding="utf-8")
    # Validar contenido del prompt template
    if "{username}" not in MARIA_SYSTEM_PROMPT_TEMPLATE:
        logging.warning(
            f"El archivo de prompt {PROMPT_FILE_PATH} no contiene la llave {{username}}. "
            "Esto podría causar errores en la personalización del prompt."
        )
except FileNotFoundError:
    logging.error(f"Error: No se encontró el archivo de prompt en {PROMPT_FILE_PATH}. Usando un prompt de respaldo genérico.")
    MARIA_SYSTEM_PROMPT_TEMPLATE = "Eres una asistente virtual llamada María. Tu objetivo es ayudar con la ansiedad. Saluda al usuario {username}."
except Exception as e:
    logging.error(f"Error al cargar o validar el archivo de prompt {PROMPT_FILE_PATH}: {e}. Usando un prompt de respaldo genérico.", exc_info=True)
    MARIA_SYSTEM_PROMPT_TEMPLATE = "Eres una asistente virtual llamada María. Tu objetivo es ayudar con la ansiedad. Saluda al usuario {username}."

class MessageProcessor:
    """Procesador de mensajes para manejar diferentes tipos de contenido."""
    
    @staticmethod
    def process_closing_message(text: str, username: str) -> Tuple[str, bool]:
        """
        Procesa el texto de un mensaje para detectar y limpiar una señal de cierre de sesión.
        Busca la etiqueta [CIERRE_DE_SESION] en el texto, la remueve, y devuelve
        información sobre si se detectó esta señal.

        Args:
            text: El texto del mensaje.
            username: El nombre del usuario para detectar despedidas automáticas.

        Returns:
            Una tupla conteniendo el texto procesado (sin la etiqueta de cierre)
            y un booleano indicando si se detectó la señal de cierre.
        """
        is_closing_message = False
        
        # Detectar automáticamente despedidas naturales y añadir el tag internamente
        auto_detected_closing = detect_natural_closing_message(text, username)
        
        # Si ya contiene la etiqueta manual o se detectó automáticamente
        if "[CIERRE_DE_SESION]" in text or auto_detected_closing:
            is_closing_message = True
            
            if "[CIERRE_DE_SESION]" in text:
                logging.info(f"Se detectó señal manual [CIERRE_DE_SESION] en el texto: '{text}'")
                # Remover completamente la etiqueta y limpiar espacios
                text = text.replace("[CIERRE_DE_SESION]", "").strip()
            else:
                logging.info(f"Se detectó despedida automática en el texto: '{text}'")
            
            # Asegurar que hay texto válido para el TTS
            if not text or len(text.strip()) == 0:
                # Si el texto quedó vacío, usar un mensaje de despedida genérico
                text = f"Hasta pronto, {username}."
                logging.info(f"Texto vacío después de procesar cierre, usando despedida genérica: '{text}'")
            elif username != "Usuario" and username not in text:
                # Agregar el nombre del usuario si no está presente
                text = f"{text.rstrip('.')} {username}."
            
            logging.info(f"Texto final para TTS después de procesar cierre: '{text}'")
        
        return text, is_closing_message

    @staticmethod
    def process_video_suggestion(text: str) -> Tuple[str, Optional[Dict[str, str]]]:
        """
        Procesa el texto de un mensaje para detectar y extraer una sugerencia de video.
        Soporta ambos formatos: [SUGERIR_VIDEO: Título, URL] y [SUGERIR_VIDEO: Título|URL]

        Args:
            text: El texto del mensaje.

        Returns:
            Una tupla conteniendo el texto procesado (sin la etiqueta de video)
            y un diccionario con la información del video si se encontró, o None.
        """
        video_payload = None
        video_tag_start = "[SUGERIR_VIDEO:"
        if video_tag_start in text:
            try:
                start_index = text.find(video_tag_start)
                end_index = text.find("]", start_index)
                if start_index != -1 and end_index != -1:
                    video_info_str = text[start_index + len(video_tag_start):end_index].strip()
                    
                    # Soportar tanto el formato con | como con ,
                    if '|' in video_info_str:
                        parts = [p.strip() for p in video_info_str.split('|')]
                    else:
                        parts = [p.strip() for p in video_info_str.split(',')]
                    
                    if len(parts) >= 2:
                        video_title = parts[0].strip()
                        video_url = parts[1].strip()
                        
                        # Validar que la URL sea válida
                        if video_url.startswith('http'):
                            logging.info(f"Se detectó sugerencia de video: Título='{video_title}', URL='{video_url}'")
                            video_payload = {"title": video_title, "url": video_url}
                            processed_text = text[:start_index].strip() + " " + text[end_index+1:].strip()
                            text = processed_text.strip()
                        else:
                            logging.warning(f"URL de video inválida: {video_url}")
                    else:
                        logging.warning(f"Formato de video inválido: {video_info_str}")
            except Exception as e:
                logging.error(f"Error al procesar sugerencia de video: {e}", exc_info=True)
        return text, video_payload

class MariaVoiceAgent(Agent):
    """
    Agente de voz principal para María.
    Maneja la conversación, procesamiento de mensajes y comunicación con el frontend.
    """
    
    def __init__(self,
                 http_session: aiohttp.ClientSession,
                 base_url: str,
                 target_participant: RemoteParticipant,
                 chat_session_id: Optional[str] = None,
                 username: str = "Usuario",
                 local_agent_identity: Optional[str] = None,
                 adaptive_tts_manager=None,
                 **kwargs):
        """
        Inicializa el agente de voz Maria.

        Args:
            http_session: Sesión aiohttp para realizar solicitudes HTTP.
            base_url: URL base para las API del backend.
            target_participant: El participante remoto al que este agente está atendiendo.
            chat_session_id: ID de la sesión de chat actual.
            username: Nombre del usuario.
            local_agent_identity: Identidad del agente local para filtrar mensajes.
            **kwargs: Argumentos adicionales para la clase base Agent.
        """

        system_prompt = MARIA_SYSTEM_PROMPT_TEMPLATE.format(
            username=username if username and username != "Usuario" else "Usuario",
            latest_summary="No hay información previa relevante."
        ).strip()

        # Los plugins se configuran en AgentSession, por lo que no se pasan a super()
        super().__init__(instructions=system_prompt, **kwargs)

        self._http_session = http_session
        self._base_url = base_url
        self._chat_session_id = chat_session_id
        self._username = username
        self._local_agent_identity = local_agent_identity
        self._ai_message_meta: Dict[str, Dict[str, Any]] = {}
        self._initial_greeting_text: Optional[str] = None
        self.target_participant = target_participant
        self._agent_session: Optional[AgentSession] = None
        self._room: Optional[Room] = None
        self.adaptive_tts_manager = adaptive_tts_manager  # Gestor de TTS adaptativo
        self._last_user_message: str = ""  # Almacenar último mensaje del usuario para análisis emocional

        logging.info(f"MariaVoiceAgent inicializada → chatSessionId: {self._chat_session_id}, Usuario: {self._username}, Atendiendo: {self.target_participant.identity}")
        
        if self.adaptive_tts_manager:
            logging.info("🎭 Sistema de voz adaptativa habilitado en MariaVoiceAgent")
        else:
            logging.info("⚠️ Sistema de voz adaptativa NO disponible en MariaVoiceAgent")

    def set_session(self, session: AgentSession, room: Room):
        """Método para asignar la AgentSession y Room después de su creación."""
        self._agent_session = session
        self._room = room
        logging.info("✅ AgentSession y Room asignados, callbacks conectados")

        # Conectar callbacks del agente a la sesión
        def on_conversation_item_added_wrapper(item):
            asyncio.create_task(self._on_conversation_item_added(item))
        
        def on_tts_playback_started_wrapper(event):
            asyncio.create_task(self.on_tts_playback_started(event))
        
        def on_tts_playback_finished_wrapper(event):
            asyncio.create_task(self.on_tts_playback_finished(event))

        session.on("llm_conversation_item_added", on_conversation_item_added_wrapper)
        session.on("tts_playback_started", on_tts_playback_started_wrapper)
        session.on("tts_playback_finished", on_tts_playback_finished_wrapper)

    def register_data_received_event(self):
        """Registra el evento data_received después de que la sesión esté completamente inicializada."""
        if self._room and hasattr(self, '_agent_session') and self._agent_session:
            def on_data_received_wrapper(data_packet):
                # El DataPacket contiene: data, kind, participant, topic
                asyncio.create_task(self._handle_frontend_data(data_packet.data, data_packet.participant))
            
            self._room.on("data_received", on_data_received_wrapper)
            logging.info("✅ Evento data_received registrado exitosamente en el room")
        else:
            logging.warning("❌ No se pudo registrar evento data_received: room o agent_session no disponible")

    async def _send_custom_data(self, data_type: str, data_payload: Dict[str, Any]):
        """
        Envía datos personalizados al frontend a través de un DataChannel.
        Implementa control de back-pressure y timeouts mejorados.

        Args:
            data_type: El tipo de mensaje a enviar (ej. "tts_started", "user_transcription_result").
            data_payload: El contenido del mensaje.
        """
        # Usar control de concurrencia para DataChannel
        async with http_session_manager.controlled_data_channel(f"send_{data_type}"):
            # Usar timeout mejorado con TimeoutManager
            async with TimeoutManager.timeout_shield(
                PERFORMANCE_CONFIG['data_channel_timeout'], 
                f"DataChannel_{data_type}"
            ):
                try:
                    # Log más detallado para debug
                    logging.info(f"🔧 _send_custom_data iniciado: type='{data_type}', payload={data_payload}")
                    
                    # Verificar estado de la room
                    logging.debug(f"🔍 Estado self._room: {self._room is not None}")
                    logging.debug(f"🔍 Estado self._room.local_participant: {self._room.local_participant is not None if self._room else 'N/A'}")
                    
                    if self._room and self._room.local_participant:
                         
                        logging.info("✅ Room y local_participant están disponibles")
                        
                        # Enviar en formato directo
                        message_data = {
                            "type": data_type,
                            **data_payload  # Expandir directamente el payload
                        }
                        logging.debug(f"📦 Mensaje preparado para envío: {message_data}")
                        
                        # Serializar a JSON
                        json_message = json.dumps(message_data)
                        logging.debug(f"📄 JSON serializado (primeros 200 chars): {json_message[:200]}")
                        
                        logging.info(f"🚀 Enviando via DataChannel (timeout: {PERFORMANCE_CONFIG['data_channel_timeout']}s)...")
                        
                        # Usar timeout interno adicional como respaldo
                        await asyncio.wait_for(
                            self._room.local_participant.publish_data(json_message),
                            timeout=PERFORMANCE_CONFIG['data_channel_timeout'] - 1  # 1s menos para permitir manejo interno
                        )
                        
                        logging.info(f"✅ Mensaje '{data_type}' enviado exitosamente via DataChannel")
                    else:
                         logging.warning("No se pudo enviar custom data: room no está disponible.")
                         
                except asyncio.TimeoutError:
                    logging.error(f"❌ TIMEOUT al enviar DataChannel: type={data_type}, timeout={PERFORMANCE_CONFIG['data_channel_timeout']}s")
                    raise
                except Exception as e:
                    logging.error(f"❌ EXCEPCIÓN al enviar DataChannel: {e}", exc_info=True)
                    raise

    async def _handle_frontend_data(self, payload: bytes, participant: 'livekit.RemoteParticipant'):
        """Maneja los DataChannels enviados desde el frontend."""
        # Usar la identidad del agente local almacenada para ignorar mensajes propios
        if participant and self._local_agent_identity and participant.identity == self._local_agent_identity:
             if message_throttler.should_log(f"ignore_own_message_{participant.identity}", 'default'):
                 logging.debug(f"Ignorando mensaje del propio agente: {participant.identity}")
             return

        try:
            data_str = payload.decode('utf-8')
            message_data = json.loads(data_str)
            
            # Solo log detallado para mensajes importantes
            participant_name = participant.identity if participant else 'N/A'
            if message_throttler.should_log(f"datachannel_received_{participant_name}", 'default'):
                logging.debug(f"DataChannel recibido: Participante='{participant_name}', Payload='{data_str[:100]}...'")

            # Extraer tipo de mensaje
            message_type = message_data.get("type")

            # Manejar mensajes de texto del usuario
            if message_type == "submit_user_text":
                user_text = message_data.get("text")
                logging.info(f"📨 Mensaje de usuario recibido: submit_user_text")
                
                # Verificar que tenemos AgentSession activa antes de procesar
                if not hasattr(self, '_agent_session') or not self._agent_session:
                    logging.error("❌ _agent_session no está disponible. No se puede procesar el mensaje.")
                    return
                
                if user_text:
                    logging.info(f"✅ Procesando mensaje de usuario: '{user_text[:50]}...'")
                    await self._send_user_transcript_and_save(user_text)
                    
                    # Verificar que la sesión del agente está corriendo antes de generar respuesta
                    try:
                        logging.info(f"🤖 Generando respuesta para: '{user_text[:50]}...'")
                        self._agent_session.generate_reply(user_input=user_text)
                    except RuntimeError as e:
                        if "AgentSession isn't running" in str(e):
                            logging.error(f"❌ La AgentSession no está ejecutándose. Error: {e}")
                            logging.info("🔄 Intentando reiniciar la AgentSession...")
                            # Aquí podrías implementar lógica de reinicio si es necesario
                        else:
                            logging.error(f"❌ Error RuntimeError en generate_reply: {e}")
                    except Exception as e:
                        logging.error(f"❌ Error inesperado en generate_reply: {e}", exc_info=True)
                else:
                    logging.warning(f"❌ Mensaje vacío del participante: {participant_name}")
                return

            # Eventos directos con throttling
            if message_type:
                if message_throttler.should_log(f'direct_event_{message_type}', 'default'):
                    logging.info(f"📨 Evento directo: tipo='{message_type}'")
                return

            # Mensajes desconocidos con throttling
            if message_throttler.should_log('unknown_message_format', 'default'):
                logging.info(f"ℹ️ Mensaje formato desconocido recibido")

        except json.JSONDecodeError:
            if message_throttler.should_log('json_decode_error', 'default'):
                logging.warning(f"❌ Error decodificando JSON del DataChannel: {payload.decode('utf-8', errors='ignore')[:100]}...")
        except Exception as e:
            logging.error(f"❌ Error procesando DataChannel: {e}", exc_info=True)

    async def _save_message(self, content: str, sender: str, message_id: Optional[str] = None, is_sensitive: bool = False):
        """
        Guarda un mensaje en el backend mediante una solicitud HTTP POST.
        Implementa una lógica de reintentos con backoff exponencial para errores de servidor.

        Args:
            content: El contenido del mensaje.
            sender: El remitente del mensaje ("user" o "assistant").
            message_id: ID único del mensaje. Si es None, se generará uno.
            is_sensitive: Si el contenido del mensaje es sensible y no debe loguearse completo.
        """
        if not self._chat_session_id:
            logging.warning("chat_session_id no está disponible, no se puede guardar el mensaje.")
            return

        if not message_id:
            message_id = f"{sender}-{uuid.uuid4()}"

        payload = {
            "id": message_id,
            "chatSessionId": self._chat_session_id,
            "sender": sender,
            "content": content,
        }

        log_content_display = "[CONTENIDO SENSIBLE OMITIDO]" if is_sensitive else content[:100] + ("..." if len(content) > 100 else "")
        logging.info(f"Intentando guardar mensaje: ID={message_id}, chatSessionId={self._chat_session_id}, sender={sender}, content='{log_content_display}'")

        attempts = 0
        while attempts < SAVE_MESSAGE_MAX_RETRIES:
            attempts += 1
            
            # Usar control de concurrencia HTTP
            async with http_session_manager.controlled_request(f"save_message_{attempts}"):
                # Usar timeout con gestión mejorada
                async with TimeoutManager.timeout_shield(
                    PERFORMANCE_CONFIG['message_save_timeout'], 
                    f"save_message_{message_id}_{attempts}"
                ):
                    try:
                        async with self._http_session.post(f"{self._base_url}/api/messages", json=payload) as resp:
                            if resp.status == 201:
                                logging.info(f"Mensaje (ID: {message_id}) guardado exitosamente en intento {attempts}.")
                                return

                            error_text = await resp.text()
                            if resp.status >= 500: # Errores de servidor, reintentables
                                logging.warning(f"Intento {attempts}/{SAVE_MESSAGE_MAX_RETRIES} fallido al guardar mensaje (ID: {message_id}). Status: {resp.status}. Error: {error_text}")
                                if attempts == SAVE_MESSAGE_MAX_RETRIES:
                                    logging.error(f"Error final del servidor ({resp.status}) al guardar mensaje (ID: {message_id}) después de {SAVE_MESSAGE_MAX_RETRIES} intentos: {error_text}")
                                    return
                                await TimeoutManager.cancel_safe_sleep(SAVE_MESSAGE_RETRY_DELAY * (2**(attempts - 1)), f"retry_delay_{attempts}")
                            else: # Errores de cliente (4xx) u otros no reintentables por código de estado
                                logging.error(f"Error no reintentable del cliente ({resp.status}) al guardar mensaje (ID: {message_id}): {error_text}")
                                return

                    except aiohttp.ClientError as e_http: # Errores de red/conexión de aiohttp
                        logging.warning(f"Excepción de red en intento {attempts}/{SAVE_MESSAGE_MAX_RETRIES} al guardar mensaje (ID: {message_id}): {e_http}")
                        if attempts == SAVE_MESSAGE_MAX_RETRIES:
                            logging.error(f"Excepción final de red al guardar mensaje (ID: {message_id}) después de {SAVE_MESSAGE_MAX_RETRIES} intentos: {e_http}", exc_info=True)
                            return
                        await TimeoutManager.cancel_safe_sleep(SAVE_MESSAGE_RETRY_DELAY * (2**(attempts - 1)), f"retry_delay_{attempts}")

                    except Exception as e: # Otras excepciones inesperadas durante el POST
                        logging.error(f"Excepción inesperada en intento {attempts} al guardar mensaje (ID: {message_id}): {e}", exc_info=True)
                        return

        logging.error(f"Todos los {SAVE_MESSAGE_MAX_RETRIES} intentos para guardar el mensaje (ID: {message_id}) fallaron.")

    async def _send_user_transcript_and_save(self, user_text: str):
        """Guarda el mensaje del usuario y lo envía al frontend."""
        logging.info(f"Usuario ({self._username}) transcribió/envió: '{user_text}'")
        
        # Almacenar el último mensaje del usuario para análisis emocional
        self._last_user_message = user_text
        
        # 🎭 ANÁLISIS DE EMOCIONES: Detectar el estado emocional del usuario
        if self.adaptive_tts_manager:
            try:
                detected_emotions = self.adaptive_tts_manager.emotion_detector.detect_emotions(user_text)
                emotion_summary = self.adaptive_tts_manager.emotion_detector.get_context_summary(detected_emotions)
                logging.info(f"🎭 {emotion_summary}")
                
                # Preparar el TTS adaptativo para la próxima respuesta
                voice_profile = self.adaptive_tts_manager.emotion_detector.get_adaptive_voice_profile(detected_emotions)
                logging.info(f"🎭 Perfil de voz preparado: {voice_profile.voice_description}")
                
            except Exception as e:
                logging.error(f"❌ Error en análisis de emociones: {e}", exc_info=True)
        
        await self._save_message(user_text, "user")
        await self._send_custom_data("user_transcription_result", {"transcript": user_text})

    async def _on_conversation_item_added(self, item: llm.ChatMessage):
        """
        Callback que se ejecuta cuando se añade un nuevo item a la conversación por el LLM.
        Procesa la respuesta del asistente, la guarda, y gestiona la reproducción de TTS.

        Args:
            item: El mensaje de chat añadido a la conversación.
        """
        if item.role == llm.ChatRole.ASSISTANT and item.content:
            ai_original_response_text = item.content
            if not ai_original_response_text:
                logging.warning(f"Mensaje de asistente (ID: {item.id}) recibido sin contenido.")
                return

            ai_message_id = str(item.id) if item.id else f"assistant-{uuid.uuid4()}"
            logging.info(f"Assistant message added (ID: {ai_message_id}): '{ai_original_response_text}'")

            # Procesar el texto para eliminar videos y detectar despedidas
            processed_text, video_payload = MessageProcessor.process_video_suggestion(ai_original_response_text)
            processed_text, is_closing_message = MessageProcessor.process_closing_message(processed_text, self._username)
            
            # El texto procesado es lo que se mostrará en el chat
            # Crear una versión limpia para TTS
            processed_text_for_tts = clean_text_for_tts(processed_text)
            
            # Verificar si es saludo inicial
            is_initial_greeting = self._initial_greeting_text is None
            
            if is_initial_greeting:
                logging.info(f"🎯 PRIMER SALUDO DETECTADO - Almacenando texto TTS base")
                self._initial_greeting_text = processed_text_for_tts

            # Log de verificación de consistencia texto-voz
            logging.info(f"💬 TEXTO EXACTO para mostrar en chat: '{processed_text}'")
            logging.info(f"🔊 TEXTO EXACTO para convertir a voz: '{processed_text_for_tts}'")
            if processed_text != processed_text_for_tts:
                logging.info(f"🔍 DIFERENCIAS TTS detectadas:")
                logging.info(f"   📝 Chat: {len(processed_text)} caracteres")
                logging.info(f"   🎤 Voz: {len(processed_text_for_tts)} caracteres")
            else:
                logging.info(f"✅ TEXTO IDÉNTICO para chat y voz - {len(processed_text)} caracteres")

            await self._save_message(ai_original_response_text, "assistant", message_id=ai_message_id)

            # Almacenar metadatos para los manejadores de eventos TTS
            self._ai_message_meta[ai_message_id] = {
                "is_closing_message": is_closing_message,
            }

            if is_initial_greeting:
                logging.info(f"📢 Enviando saludo inicial (ID: {ai_message_id}): '{processed_text}'")
            else:
                logging.info(f"💬 Enviando respuesta del asistente (ID: {ai_message_id}): '{processed_text[:100]}...'")

            # IMPORTANTE: Enviar ai_response_generated ANTES del TTS para que aparezca el texto en el chat
            video_data = video_payload if video_payload else None
            logging.info(f"💬 Enviando evento ai_response_generated con texto para chat")
            
            await self._send_custom_data("ai_response_generated", {
                "id": ai_message_id,
                "text": processed_text,  # El texto procesado que se mostrará en el chat
                "suggestedVideo": video_data,
                "isInitialGreeting": is_initial_greeting
            })

            metadata_for_speak_call = {
                "messageId": ai_message_id,
                "is_closing_message": is_closing_message
            }

            # 🎭 APLICAR VOZ ADAPTATIVA: Usar TTS dinámico basado en emociones detectadas
            if self.adaptive_tts_manager:
                try:
                    # Obtener TTS adaptativo basado en el texto del usuario más reciente
                    logging.info(f"🎭 Obteniendo TTS adaptativo para respuesta...")
                    adaptive_tts = self.adaptive_tts_manager.get_adaptive_tts(self._last_user_message)
                    
                    # Aplicar el TTS adaptativo al agent session si es posible
                    if hasattr(self._agent_session, '_tts'):
                        original_tts = self._agent_session._tts
                        self._agent_session._tts = adaptive_tts
                        logging.info(f"🎭 TTS adaptativo aplicado temporalmente para este mensaje")
                        
                        # Reproducir con TTS adaptativo
                        logging.info(f"🔊 Reproduciendo TTS ADAPTATIVO para mensaje (ID: {ai_message_id})")
                        await self._agent_session.speak(processed_text_for_tts, metadata=metadata_for_speak_call)
                        
                        # Restaurar TTS original después del speak
                        self._agent_session._tts = original_tts
                        
                    else:
                        # Fallback si no se puede modificar el TTS del session
                        logging.info(f"🔊 Reproduciendo TTS (fallback normal) para mensaje (ID: {ai_message_id})")
                        await self._agent_session.speak(processed_text_for_tts, metadata=metadata_for_speak_call)
                        
                except Exception as e:
                    logging.error(f"❌ Error aplicando TTS adaptativo: {e}", exc_info=True)
                    # Fallback a TTS normal
                    logging.info(f"🔊 Reproduciendo TTS (fallback por error) para mensaje (ID: {ai_message_id})")
                    await self._agent_session.speak(processed_text_for_tts, metadata=metadata_for_speak_call)
            else:
                # TTS normal cuando no hay sistema adaptativo
                logging.info(f"🔊 Reproduciendo TTS para mensaje (ID: {ai_message_id}): '{processed_text_for_tts[:100]}...'")
                await self._agent_session.speak(processed_text_for_tts, metadata=metadata_for_speak_call)

    async def on_tts_playback_started(self, event: Any):
        """Callback cuando el TTS comienza a reproducirse."""
        ai_message_id = getattr(event, 'item_id', None)
        if ai_message_id:
            if message_throttler.should_log(f'tts_started_{ai_message_id}', 'tts_events'):
                logging.debug(f"TTS Playback Started for item_id: {ai_message_id}")
            await self._send_custom_data("tts_started", {"messageId": ai_message_id})
        else:
            logging.warning("on_tts_playback_started: event.item_id is missing.")

    async def on_tts_playback_finished(self, event: Any):
        """Callback cuando el TTS termina de reproducirse."""
        ai_message_id = getattr(event, 'item_id', None)
        if ai_message_id:
            if message_throttler.should_log(f'tts_finished_{ai_message_id}', 'tts_events'):
                logging.debug(f"TTS Playback Finished for item_id: {ai_message_id}")

            is_closing_message = None
            event_metadata = getattr(event, 'metadata', None)
            # Intentar obtener is_closing_message desde event.metadata (poblado por nuestra llamada a speak)
            if event_metadata and "is_closing_message" in event_metadata:
                is_closing_message = event_metadata["is_closing_message"]

            # Fallback a _ai_message_meta si no está en event.metadata
            if is_closing_message is None:
                message_meta = self._ai_message_meta.get(ai_message_id)
                if message_meta:
                    is_closing_message = message_meta.get("is_closing_message", False)
                else:
                    is_closing_message = False # Default si no se encuentra
                    if message_throttler.should_log(f'missing_meta_{ai_message_id}', 'default'):
                        logging.warning(f"No se encontró metadata para {ai_message_id} en _ai_message_meta.")

            await self._send_custom_data("tts_ended", {
                "messageId": ai_message_id,
                "isClosing": is_closing_message if isinstance(is_closing_message, bool) else False
            })
        else:
            logging.warning("on_tts_playback_finished: event.item_id is missing.")

    async def generate_initial_greeting(self):
        """
        Genera y envía el saludo inicial del agente.
        """
        logging.info("🚀 INICIANDO SECUENCIA DE SALUDO INICIAL...")
        
        # Esperar un poco para que todo el sistema se estabilice
        logging.info("⏳ Esperando estabilización del sistema (3 segundos)...")
        await asyncio.sleep(3)
        
        # Generar saludo aleatorio de múltiples opciones
        logging.info("📝 Generando mensaje de bienvenida...")
        immediate_greeting = generate_welcome_message(self._username)
        logging.info(f"💬 Saludo generado: '{immediate_greeting}'")
        
        # Limpiar el saludo para TTS
        immediate_greeting_clean = clean_text_for_tts(immediate_greeting)
        logging.info(f"🧹 Saludo limpio para TTS: '{immediate_greeting_clean}'")
        
        # Crear mensaje del saludo inmediato
        immediate_greeting_id = f"immediate-greeting-{int(time.time() * 1000)}"
        logging.info(f"🆔 ID del saludo inicial: '{immediate_greeting_id}'")
        
        # Marcar como saludo inicial procesado
        self._initial_greeting_text = immediate_greeting_clean
        
        # Preparar payload
        saludo_payload = {
            "id": immediate_greeting_id,
            "text": immediate_greeting,
            "isInitialGreeting": True
        }
        logging.info(f"📦 Payload del saludo: {saludo_payload}")
        
        # Enviar al frontend
        try:
            logging.info("🚀 Enviando saludo inicial al frontend...")
            await self._send_custom_data("ai_response_generated", saludo_payload)
            logging.info("✅ Saludo enviado al frontend exitosamente")
            
            # 🎭 Generar TTS con voz adaptativa para saludo inicial (usar perfil calmado)
            logging.info(f"🔊 Iniciando TTS para que María pronuncie el saludo")
            
            if self.adaptive_tts_manager:
                try:
                    # Para el saludo inicial, usar un perfil neutro y calmado
                    from emotion_detector import VoiceProfile
                    calm_profile = VoiceProfile(
                        speed=-0.4,  # Más pausada para el saludo inicial
                        emotion=["positivity:low"],  # Ligeramente positiva y acogedora
                        voice_description="Voz cálida y acogedora para saludo inicial"
                    )
                    
                    logging.info(f"🎭 Aplicando perfil especial para saludo inicial: {calm_profile.voice_description}")
                    adaptive_tts = self.adaptive_tts_manager._create_adaptive_tts(calm_profile)
                    
                    # Aplicar TTS adaptativo temporalmente
                    if hasattr(self._agent_session, '_tts'):
                        original_tts = self._agent_session._tts
                        self._agent_session._tts = adaptive_tts
                        
                        await self._agent_session.say(immediate_greeting_clean, allow_interruptions=True)
                        
                        # Restaurar TTS original
                        self._agent_session._tts = original_tts
                        logging.info("✅ María está hablando con voz adaptativa - TTS iniciado exitosamente")
                    else:
                        await self._agent_session.say(immediate_greeting_clean, allow_interruptions=True)
                        logging.info("✅ María está hablando (fallback) - TTS iniciado exitosamente")
                        
                except Exception as e:
                    logging.error(f"❌ Error aplicando TTS adaptativo en saludo: {e}", exc_info=True)
                    await self._agent_session.say(immediate_greeting_clean, allow_interruptions=True)
                    logging.info("✅ María está hablando (fallback por error) - TTS iniciado exitosamente")
            else:
                await self._agent_session.say(immediate_greeting_clean, allow_interruptions=True)
                logging.info("✅ María está hablando - TTS iniciado exitosamente")
            
        except Exception as e:
            logging.error(f"❌ Error enviando saludo inicial: {e}", exc_info=True)
        
        logging.info("✅ Saludo inicial procesado completamente") 