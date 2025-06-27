import asyncio
import logging
import json
import re
import time
from typing import Optional, Dict, Any, Tuple

import aiohttp

from livekit.agents import (
    JobContext,
    WorkerOptions,
    cli,
    AgentSession,
    WorkerType,
    RoomOutputOptions,
    RoomInputOptions,
)
from livekit.rtc import RemoteParticipant, Room
from livekit.plugins import deepgram, openai, silero, cartesia
from livekit.agents import llm, stt, tts, vad

# Importar módulos locales refactorizados
from config import create_settings, PERFORMANCE_CONFIG
from throttler import message_throttler
from text_utils import generate_welcome_message, convert_numbers_to_text, clean_text_for_tts
from maria_agent import MariaVoiceAgent
from plugin_loader import plugin_loader
from http_session_manager import http_session_manager, TimeoutManager
from adaptive_tts_manager import create_adaptive_tts_manager

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Silenciar logs de livekit para reducir ruido en consola
logging.getLogger('livekit').setLevel(logging.CRITICAL)
logging.getLogger('livekit.agents').setLevel(logging.CRITICAL)
logging.getLogger('livekit.plugins').setLevel(logging.CRITICAL)
logging.getLogger('livekit.rtc').setLevel(logging.CRITICAL)
logging.getLogger('livekit.protocol').setLevel(logging.CRITICAL)
logging.getLogger('livekit.api').setLevel(logging.CRITICAL)
logging.getLogger('websockets').setLevel(logging.CRITICAL)
logging.getLogger('asyncio').setLevel(logging.CRITICAL)
logging.getLogger('aiohttp').setLevel(logging.CRITICAL)
logging.getLogger('urllib3').setLevel(logging.CRITICAL)

# Cargar configuración usando el factory method
settings = create_settings()

# Funciones utilitarias para el manejo de participantes y metadatos

def parse_participant_metadata(metadata_str: Optional[str]) -> Dict[str, Optional[str]]:
    """Parsea los metadatos del participante (JSON string) en un diccionario."""
    if not metadata_str:
        logging.warning("No se proporcionaron metadatos para el participante o están vacíos.")
        return {"userId": None, "username": None, "chatSessionId": None, "targetParticipantIdentity": None}

    try:
        metadata = json.loads(metadata_str)
        # Extraer valores y asegurar que son del tipo esperado o None
        user_id = metadata.get("userId")
        username = metadata.get("username")
        chat_session_id = metadata.get("chatSessionId")
        target_participant_identity = metadata.get("targetParticipantIdentity")

        # Validaciones de tipo (opcional pero recomendado para robustez)
        if user_id is not None and not isinstance(user_id, str):
            logging.warning(f"userId esperado como string, se recibió {type(user_id)}. Se usará None.")
            user_id = None
        if username is not None and not isinstance(username, str):
            logging.warning(f"username esperado como string, se recibió {type(username)}. Se usará None.")
            username = None
        if chat_session_id is not None and not isinstance(chat_session_id, str):
            logging.warning(f"chatSessionId esperado como string, se recibió {type(chat_session_id)}. Se usará None.")
            chat_session_id = None
        if target_participant_identity is not None and not isinstance(target_participant_identity, str):
            logging.warning(f"targetParticipantIdentity esperado como string, se recibió {type(target_participant_identity)}. Se usará None.")
            target_participant_identity = None

        return {
            "userId": user_id,
            "username": username,
            "chatSessionId": chat_session_id,
            "targetParticipantIdentity": target_participant_identity,
        }
    except json.JSONDecodeError:
        logging.error(f"Error al decodificar metadatos JSON del participante: {metadata_str}")
        return {"userId": None, "username": None, "chatSessionId": None, "targetParticipantIdentity": None}
    except Exception as e:
        logging.error(f"Error inesperado al parsear metadatos del participante: {e}", exc_info=True)
        return {"userId": None, "username": None, "chatSessionId": None, "targetParticipantIdentity": None}

async def _setup_plugins(job: JobContext) -> Tuple[Optional[stt.STT], Optional[llm.LLM], Optional[vad.VAD], Optional[tts.TTS]]:
    """
    Configura y devuelve los plugins STT, LLM, VAD y TTS.

    Args:
        job: El contexto del job actual, potencialmente usado para configuración avanzada de plugins.

    Returns:
        Una tupla con las instancias de los plugins (STT, LLM, VAD, TTS).
        Retorna Nones si hay un error crítico durante la configuración.

    Raises:
        Puede propagar excepciones si las variables de entorno requeridas por los plugins
        (ej. claves API) no están configuradas.
    """
    try:
        logging.info("🔧 Configurando plugins del agente...")
        
        # Configuración simplificada de Deepgram STT sin parámetros no soportados
        stt_plugin = deepgram.STT(
            model=settings.deepgram_model, 
            language="es", 
            interim_results=True,
            smart_format=True,
            punctuate=True
        )
        
        llm_plugin = openai.LLM(model=settings.openai_model)
        
        vad_plugin = silero.VAD.load(
            prefix_padding_duration=0.2,    # 200ms para capturar inicio completo
            min_silence_duration=1.5,       # 1500ms - más tiempo para pausas naturales
            activation_threshold=0.4,       # Más sensible para detectar voz suave
            min_speech_duration=0.15        # 150ms - detectar palabras más cortas
            # sample_rate y force_cpu usarán los valores por defecto (16000 y True respectivamente)
        )

        # Crear gestor de TTS adaptativo
        adaptive_tts_manager = create_adaptive_tts_manager(settings)
        
        # TTS base para casos donde no se use la voz adaptativa
        tts_cartesia_plugin = cartesia.TTS(
            api_key=settings.cartesia_api_key,
            model=settings.cartesia_model,
            voice=settings.cartesia_voice_id, # Cambiado de voice_id a voice
            language=settings.cartesia_language,
            speed=settings.cartesia_speed,
            emotion=settings.cartesia_emotion,
        )

        logging.info(f"✅ Plugins configurados: STT({settings.deepgram_model}), LLM({settings.openai_model}), VAD(Silero), TTS({settings.cartesia_model})")
        logging.info(f"🎭 Sistema de voz adaptativa: {'Habilitado' if settings.enable_adaptive_voice else 'Deshabilitado'}")
        return stt_plugin, llm_plugin, vad_plugin, tts_cartesia_plugin, adaptive_tts_manager
    except Exception as e_plugins:
        logging.error(f"❌ Error crítico configurando plugins: {e_plugins}", exc_info=True)
        return None, None, None, None, None

async def find_target_participant_in_room(room: Room, identity_str: str, timeout: float = 60.0) -> Optional[RemoteParticipant]:
    # Si ya está en la sala:
    for p in room.participants.values():
        if p.identity == identity_str:
            return p

    # Si no, esperar a que se conecte
    future = asyncio.get_event_loop().create_future()

    def on_participant_connected_handler(new_p: RemoteParticipant, *args): # La firma puede variar, *args para flexibilidad
        # El SDK livekit-rtc pasa RemoteParticipant directamente para PARTICIPANT_CONNECTED
        if new_p.identity == identity_str and not future.done():
            future.set_result(new_p)

    # Suscribirse al evento. El evento 'participant_connected' es de Room, no de RoomEvent.
    room.on("participant_connected", on_participant_connected_handler)

    try:
        # Esperar con timeout
        return await asyncio.wait_for(future, timeout)
    except asyncio.TimeoutError:
        logging.warning(f"Timeout esperando al participante con ID '{identity_str}'")
        return None
    finally:
        # Limpiar el listener
        room.off("participant_connected", on_participant_connected_handler)

async def find_first_remote(room: Room, local_identity: str, timeout: float = 60.0) -> Optional[RemoteParticipant]:
    """
    Espera al primer RemoteParticipant que se conecte a la sala y cuya identidad
    no coincida con la identidad local proporcionada.

    Args:
        room: La instancia de la sala de LiveKit.
        local_identity: La identidad del participante local, para excluirlo.
        timeout: Tiempo máximo en segundos para esperar al participante.

    Returns:
        El primer RemoteParticipant encontrado, o None si se agota el tiempo.
    """
    # Listener
    fut = asyncio.get_event_loop().create_future()
    def on_join(p: RemoteParticipant, *args):
        if p.identity != local_identity and not fut.done():
            fut.set_result(p)

    room.on("participant_connected", on_join)
    try:
        return await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        room.off("participant_connected", on_join)

async def job_entrypoint(job: JobContext):
    """
    Punto de entrada principal para el job del agente de LiveKit.
    Este método es llamado por el worker de LiveKit cuando se asigna un nuevo job (sala).

    Configura el agente, los plugins, maneja la conexión a la sala,
    encuentra al participante remoto y arranca la sesión del agente.

    Args:
        job: El contexto del job proporcionado por LiveKit, que incluye
             información de la sala y metadatos.
    """
    logging.info(f"Iniciando job_entrypoint para la sala: {job.room.name}")
    logging.info(f"Metadata del Job (job.job.metadata): {job.job.metadata}")
    
    # Conectar al JobContext (gestionado por LiveKit)
    try:
        await job.connect()
        logging.info(f"Conectado exitosamente a la sala: {job.room.name}")
    except Exception as e_connect:
        logging.critical(f"Error al conectar con job.connect(): {e_connect}", exc_info=True)
        return

    # Obtener la identidad local primero
    local_id = job.room.local_participant.identity
    logging.info(f"Agente local identity: {local_id}")

    # CORREGIDO: Acceder a la metadata desde el participante remoto (usuario), no del local (agente)
    # Auto-descubrimiento del participante remoto y obtención de metadatos
    participants = list(job.room.remote_participants.values())
    candidates = [p for p in participants if p.identity != local_id]
    target_remote_participant: Optional[RemoteParticipant] = None
    participant_metadata = None
    
    if candidates:
        # Si ya hay participantes remotos, usar el primero
        target_remote_participant = candidates[0]
        participant_metadata = getattr(target_remote_participant, 'metadata', None)
        logging.info(f"Auto-descubrimiento: elegido participante {target_remote_participant.identity}")
        logging.info(f"Metadata del participante remoto {target_remote_participant.identity}: {participant_metadata}")
    else:
        # Si no hay participantes remotos aún, esperar al primero
        logging.info(f"No se encontraron participantes remotos existentes. Esperando al primero en conectarse (distinto de {local_id})...")
        target_remote_participant = await find_first_remote(job.room, local_id)
        if not target_remote_participant:
            logging.error("No llegó ningún usuario remoto; abortando.")
            await job.disconnect() # Desconectar si no hay participante
            return
        participant_metadata = getattr(target_remote_participant, 'metadata', None)
        logging.info(f"Auto-descubrimiento por espera: elegido participante {target_remote_participant.identity}")
        logging.info(f"Metadata del participante remoto {target_remote_participant.identity}: {participant_metadata}")
    
    # Parsear metadata del participante para obtener chat_session_id, username, etc.
    parsed_metadata = parse_participant_metadata(participant_metadata)
    chat_session_id = parsed_metadata.get("chatSessionId")
    username = parsed_metadata.get("username", "Usuario") # Default a "Usuario" si no se provee

    # CORREGIR: Si no hay username en metadata, extraer del participant.identity
    if not username or username == "Usuario":
        # Extraer nombre del participant.identity (formato: "Nombre_sessionId")
        participant_identity = target_remote_participant.identity
        if participant_identity and "_" in participant_identity:
            extracted_name = participant_identity.split("_")[0]
            # Reemplazar guiones bajos con espacios para nombres compuestos
            extracted_name = extracted_name.replace("_", " ")
            username = extracted_name
            logging.info(f"Nombre de usuario extraído de participant.identity: '{username}'")
        elif participant_identity:
            username = participant_identity
            logging.info(f"Usando participant.identity completo como nombre: '{username}'")

    # NUEVO: Extraer solo el primer nombre para una conversación más natural
    if username and username != "Usuario":
        # Dividir por espacios y tomar solo la primera palabra (primer nombre)
        first_name = username.split()[0].strip()
        if first_name:
            username = first_name
            logging.info(f"Usando solo el primer nombre para conversación natural: '{username}'")

    # MODIFICACIÓN PARA MODO DEV SIN METADATA FLAG
    # Si no se encontró chatSessionId (lo que ocurre si participant_metadata es None o no lo contiene),
    # asignamos un valor por defecto. Esto es útil para desarrollo local con `python main.py dev`
    # sin necesidad de pasar el flag --metadata.
    if not chat_session_id:
        default_dev_session_id = "dev_default_chat_session_id_123"
        logging.warning(
            f"chatSessionId no se encontró en la metadata del participante (participant.metadata era '{participant_metadata}'). "
            f"Asignando valor por defecto para desarrollo: '{default_dev_session_id}'."
        )
        chat_session_id = default_dev_session_id
        # Ya no necesitamos asignar username por defecto aquí porque ya lo extrajimos arriba

    if not chat_session_id:
        logging.critical("chatSessionId no encontrado en la metadata y no se pudo establecer un valor por defecto. Abortando.")
        return

    # Obtener Room SID de forma asíncrona
    room_sid = await job.room.sid
    logging.info(f"JobContext - Room ID: {room_sid}, Room Name: {job.room.name}")
    logging.info(f"ChatSessionId: {chat_session_id}, Username: {username if username else '(No especificado)'}") # Asegurar que username no sea None en el log

    # Configurar plugins y sistema de voz adaptativa
    stt_plugin, llm_plugin, vad_plugin, tts_plugin, adaptive_tts_manager = await _setup_plugins(job) # job puede ser necesario para contexto de plugins
    if not all([stt_plugin, llm_plugin, vad_plugin, tts_plugin, adaptive_tts_manager]):
        logging.critical("Faltan uno o más plugins esenciales o el gestor TTS adaptativo. Abortando.")
        return

    # Inicializar el gestor de sesiones HTTP global
    await http_session_manager.initialize(
        max_concurrent_requests=PERFORMANCE_CONFIG['max_concurrent_requests'],
        max_data_channel_concurrent=PERFORMANCE_CONFIG['max_data_channel_concurrent'],
        connector_limit=PERFORMANCE_CONFIG['connector_limit'],
        connector_limit_per_host=PERFORMANCE_CONFIG['connector_limit_per_host'],
        timeout_total=PERFORMANCE_CONFIG['http_timeout_total']
    )
    
    try:
        # Crear AgentSession y pasarle los plugins
        logging.info("Creando AgentSession con los plugins configurados...")
        agent_session = AgentSession(
            stt=stt_plugin,
            llm=llm_plugin,
            tts=tts_plugin,
            vad=vad_plugin,
            # context=job # Podría ser necesario si AgentSession lo usa internamente
        )
        logging.info("AgentSession creada.")

        # Evento para manejar el fin de la sesión y mantener el job vivo
        session_ended_event = asyncio.Event()

        def on_session_end_handler(payload: Any): # payload podría contener info de la razón del cierre
            logging.info(f"Evento 'session_ended' recibido. Payload: {payload}")
            session_ended_event.set()

        agent_session.on("session_ended", on_session_end_handler)

        # Tavus removido - usando avatar CSS en frontend
        logging.info("🎭 Usando avatar CSS visual en frontend (Tavus removido)")

        # Configurar RoomInputOptions y RoomOutputOptions como especificaste
        room_input_options = RoomInputOptions(
            text_enabled=True,    # habilita el canal de texto
            audio_enabled=True,    # habilita el micrófono para STT
            video_enabled=False    # no envías video desde tu cámara
        )
        room_output_options = RoomOutputOptions(
            transcription_enabled=True,  # suscribe la pista de texto
            audio_enabled=True            # suscribe la pista de audio TTS
        )
        logging.info(f"RoomInputOptions configurado: audio_enabled={room_input_options.audio_enabled}, video_enabled={room_input_options.video_enabled}, text_enabled={room_input_options.text_enabled}")
        logging.info(f"RoomOutputOptions configurado: audio_enabled={room_output_options.audio_enabled}, transcription_enabled={room_output_options.transcription_enabled}")

        # Inicializar el agente principal (MariaVoiceAgent)
        agent = MariaVoiceAgent(
            http_session=http_session_manager.session,
            base_url=settings.api_base_url, # Usar settings #
            target_participant=target_remote_participant,
            chat_session_id=chat_session_id,
            username=username,
            local_agent_identity=local_id,  # AGREGADO: Pasar la identidad del agente local
            adaptive_tts_manager=adaptive_tts_manager,  # AGREGADO: Pasar el gestor de TTS adaptativo
        )

        # AGREGADO: Asignar la sesión al agente para que pueda acceder a los métodos de TTS
        agent.set_session(agent_session, job.room)

        # Iniciar la lógica del agente a través de AgentSession
        logging.info(
            "Iniciando MariaVoiceAgent a través de AgentSession para el participante: %s",
            target_remote_participant.identity,
        )
        try:
            logging.info("🔄 Iniciando agent_session.start()...")
            await agent_session.start(
                agent=agent,
                room=job.room,
                room_input_options=room_input_options, # Añadido
                room_output_options=room_output_options, # Modificado/Añadido
            )
            logging.info("✅ agent_session.start() completado exitosamente")
            
            # AGREGADO: Registrar evento data_received después de que la sesión esté completamente inicializada
            logging.info("AgentSession iniciada exitosamente. Registrando evento data_received...")
            agent.register_data_received_event()
            logging.info("✅ Evento data_received registrado")
            
            # AGREGADO: Generar saludo inicial automáticamente
            logging.info("🚀 INICIANDO SECUENCIA DE SALUDO INICIAL...")
            
            # Esperar un poco para que todo el sistema se estabilice
            logging.info("⏳ Esperando estabilización del sistema (3 segundos)...")
            await asyncio.sleep(3)  # Aumentar de 2 a 3 segundos
            
            # CRÍTICO: Forzar el saludo inicial incluso si agent_session.start() falló parcialmente
            logging.info("🎯 FORZANDO SALUDO INICIAL INMEDIATO...")
            
            # Verificar que la conexión esté estable antes de generar el saludo
            logging.info(f"🔍 Verificando estado del job.room: {job.room is not None}")
            logging.info(f"🔍 Verificando estado del job.room.local_participant: {job.room.local_participant is not None if job.room else 'N/A'}")
            
            # SIEMPRE intentar generar el saludo, incluso si hay problemas menores
            logging.info(f"✅ Generando saludo inicial para '{username}' (forzado)")
            
            # Generar saludo aleatorio de múltiples opciones
            logging.info("📝 Generando mensaje de bienvenida...")
            immediate_greeting = generate_welcome_message(username)
            logging.info(f"💬 Saludo generado: '{immediate_greeting}'")
            
            # Limpiar el saludo para TTS
            immediate_greeting_clean = clean_text_for_tts(immediate_greeting)
            logging.info(f"🧹 Saludo limpio para TTS: '{immediate_greeting_clean}'")
            
            # Crear mensaje del saludo inmediato
            immediate_greeting_id = f"immediate-greeting-{int(time.time() * 1000)}"
            logging.info(f"🆔 ID del saludo inicial: '{immediate_greeting_id}'")
            
            # Verificar que tenemos room disponible antes de enviar
            logging.info(f"🔍 Verificando estado del agent._room: {agent._room is not None}")
            logging.info(f"🔍 Verificando estado del agent._room.local_participant: {agent._room.local_participant is not None if agent._room else 'N/A'}")
            
            # FORZAR envío del saludo inicial independientemente del estado
            logging.info("🚀 FORZANDO ENVÍO DE SALUDO INICIAL...")
            
            # Enviar inmediatamente el saludo al frontend
            logging.info(f"📢 ENVIANDO SALUDO INMEDIATO AL FRONTEND...")
            logging.info(f"🆔 ID: '{immediate_greeting_id}'")
            logging.info(f"💬 TEXTO EXACTO que se mostrará en el chat: '{immediate_greeting}'")
            logging.info(f"🔊 TEXTO EXACTO que se convertirá a voz: '{immediate_greeting_clean}'")
            logging.info(f"🔍 Diferencias de limpieza TTS: Original={len(immediate_greeting)} chars, Limpio={len(immediate_greeting_clean)} chars")
            
            # Preparar payload
            saludo_payload = {
                "id": immediate_greeting_id,
                "text": immediate_greeting,
                "isInitialGreeting": True
            }
            logging.info(f"📦 Payload del saludo: {saludo_payload}")
            
            # Enviar al frontend
            try:
                logging.info("🚀 Llamando a agent._send_custom_data...")
                await agent._send_custom_data("ai_response_generated", saludo_payload)
                logging.info("✅ agent._send_custom_data completado exitosamente")
            except Exception as e:
                logging.error(f"❌ Error en agent._send_custom_data: {e}", exc_info=True)
                
                # FALLBACK: Intentar envío directo al room
                try:
                    logging.info("🔄 Intentando envío directo al room como fallback...")
                    import json
                    data_str = json.dumps({
                        "type": "ai_response_generated",
                        "payload": saludo_payload
                    })
                    data_bytes = data_str.encode('utf-8')
                    
                    if job.room and job.room.local_participant:
                        await job.room.local_participant.publish_data(data_bytes)
                        logging.info("✅ Fallback: Saludo enviado directamente al room")
                    else:
                        logging.error("❌ Fallback falló: No hay room disponible")
                        
                except Exception as e2:
                    logging.error(f"❌ Fallback también falló: {e2}", exc_info=True)
            
            # Marcar como saludo inicial procesado
            agent._initial_greeting_text = immediate_greeting_clean
            
            # Generar TTS real para que María hable
            logging.info(f"🔊 Iniciando TTS para que María pronuncie el saludo")
            try:
                # Usar el método say del agent_session directamente con texto limpio
                await agent_session.say(immediate_greeting_clean, allow_interruptions=True)
                logging.info("✅ María está hablando - TTS iniciado exitosamente")
                
            except Exception as e:
                logging.warning(f"⚠️ Error con agent_session.say: {e}, intentando método alternativo")
                
                try:
                    # Método alternativo: usar el TTS directamente
                    if hasattr(agent_session, 'tts') and agent_session.tts:
                        tts_audio = agent_session.tts.synthesize(immediate_greeting_clean)
                        # El audio se manejará automáticamente por el sistema
                        logging.info("✅ TTS alternativo iniciado correctamente")
                    else:
                        # Si no tenemos TTS disponible, usar eventos manuales
                        raise Exception("No hay TTS disponible")
                
                except Exception as e2:
                    logging.warning(f"⚠️ Error con TTS alternativo: {e2}, usando fallback manual")
                    
                    # Fallback final: eventos manuales
                    await agent._send_custom_data("tts_started", {"messageId": immediate_greeting_id})
                    logging.info("🔊 Simulando TTS con eventos manuales")
                    
                    # Tiempo estimado para pronunciar el saludo
                    await asyncio.sleep(10)  # Tiempo suficiente para el saludo completo
                    
                    await agent._send_custom_data("tts_ended", {
                        "messageId": immediate_greeting_id,
                        "isClosing": False
                    })
                    logging.info("🔇 TTS manual completado")
            
            logging.info("✅ Saludo inicial procesado completamente")
            
            # MECANISMO DE REENVÍO: Asegurar que el saludo llegue al frontend
            logging.info("🔄 Iniciando mecanismo de reenvío del saludo inicial...")
            max_retries = 3  # Reducir de 5 a 3 intentos
            retry_interval = 2  # Reducir de 3 a 2 segundos
            
            for retry in range(max_retries):
                await asyncio.sleep(retry_interval)
                
                logging.info(f"🔄 Reenvío #{retry + 1} del saludo inicial...")
                try:
                    await agent._send_custom_data("ai_response_generated", saludo_payload)
                    logging.info(f"✅ Reenvío #{retry + 1} completado")
                    
                except Exception as e:
                    logging.warning(f"⚠️ Reenvío #{retry + 1} falló: {e}")
            
            logging.info("🏁 Mecanismo de reenvío completado")
            
            # Mantener el job vivo hasta que la sesión del agente termine
            logging.info("🔄 AgentSession.start() completado. Esperando a que el evento 'session_ended' se active...")
            await session_ended_event.wait()
            logging.info("🏁 Evento 'session_ended' activado. El job_entrypoint continuará para finalizar.")

        except Exception as e:
            logging.critical(
                "Error crítico durante agent_session.start(): %s",
                e,
                exc_info=True,
            )
        finally:
            logging.info(
                "MariaVoiceAgent (y su AgentSession) ha terminado o encontrado un error. job_entrypoint finalizando."
            )
            
            # Mostrar estadísticas de throttling para diagnóstico
            if hasattr(message_throttler, 'event_counters') and message_throttler.event_counters:
                logging.info("📊 Resumen de eventos durante la sesión:")
                for event_key, count in message_throttler.event_counters.items():
                    if count > 10:  # Solo mostrar eventos frecuentes
                        logging.info(f"   {event_key}: {count} eventos")
            
            # En lugar de ctx.shutdown(), usamos job.disconnect() para cerrar la conexión del job actual.
            # Esto es más limpio y específico para el contexto del job.
            # ctx.shutdown() podría usarse si quisiéramos cerrar todo el worker, no sólo este job.
            logging.info("Desconectando el Job de LiveKit...")
            job.shutdown(reason="Dev mode complete") # Cambio a shutdown
            logging.info("Job desconectado.")
    finally:
        # Cerrar el gestor HTTP global al final del job
        await http_session_manager.close()



if __name__ == "__main__":
    logging.info("Configurando WorkerOptions y ejecutando la aplicación CLI...")
    
    logging.info(f"Configuración de LiveKit cargada. URL: {settings.livekit_url[:20]}... (verificación crítica ya hecha por AppSettings)") #

    opts = WorkerOptions(
        entrypoint_fnc=job_entrypoint,
        worker_type=WorkerType.ROOM,
        port=settings.livekit_agent_port # Usar settings #
    )

    try:
        logging.info("Iniciando cli.run_app(opts)...")
        cli.run_app(opts)
    except ValueError as e_settings: # Capturar el ValueError de AppSettings
        logging.critical(f"Error de configuración: {e_settings}")
    except KeyboardInterrupt:
        logging.info("Proceso interrumpido por el usuario (Ctrl+C) durante cli.run_app. Finalizando...")
    except Exception as e:
        logging.critical(f"Error crítico irrecuperable al ejecutar cli.run_app: {e}", exc_info=True)
    finally:
        logging.info("Proceso principal del worker (cli.run_app) finalizado.")