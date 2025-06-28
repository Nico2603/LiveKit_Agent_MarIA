# Agente María para LiveKit

Agente de voz conversacional llamado María, especializado en manejo de ansiedad. Este agente utiliza tecnologías avanzadas de STT, LLM y TTS para proporcionar respuestas empáticas y asistencia profesional, con capacidades de respuestas enriquecidas multimedia.

## ✨ Características Principales

- **Conversación por voz en tiempo real** con transcripción STT (Deepgram)
- **Procesamiento inteligente** con modelos LLM avanzados (OpenAI)
- **Síntesis de voz natural** con TTS adaptativo (múltiples proveedores)
- **Respuestas enriquecidas multimedia** con tarjetas, imágenes, botones y enlaces interactivos
- **Especialización en ansiedad** con técnicas y recursos especializados
- **Sesiones persistentes** con historial y resúmenes automáticos
- **Sistema de contribución** con QR automático al finalizar sesiones
- **Detección automática de enlaces** que se convierten en botones interactivos

## 🎯 Sistema de Respuestas Enriquecidas

María cuenta con un sistema avanzado que permite crear experiencias interactivas:

### Funcionalidades Automáticas
- **QR de pago**: Se muestra automáticamente al finalizar sesiones
- **Botones de enlace**: URLs se convierten automáticamente en botones interactivos
- **Videos de YouTube**: Se crean botones "Ver Video" automáticamente

### Elementos Disponibles
- **Tarjetas informativas**: Para técnicas, consejos y ejercicios
- **Imágenes**: Con títulos y descripciones
- **Botones interactivos**: Para acciones específicas
- **Enlaces categorizados**: Para recursos externos
- **Videos sugeridos**: Con compatibilidad completa

Para más detalles, consulta [RESPUESTAS_ENRIQUECIDAS.md](./RESPUESTAS_ENRIQUECIDAS.md).

## 🚀 Requisitos Previos

- Python 3.9+
- Cuenta de LiveKit con credenciales
- Claves API para servicios integrados:
  - OpenAI (LLM)
  - Deepgram (STT)
  - Cartesia/Silero (TTS)

## 📦 Instalación

1. **Clonar el repositorio:**
   ```bash
   git clone <URL_DEL_REPOSITORIO>
   cd LiveKit_Agent_MarIA
   ```

2. **Crear y activar entorno virtual:**
   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # macOS/Linux
   source venv/bin/activate
   ```

3. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configurar variables de entorno:**
   Crea un archivo `.env` en la raíz del proyecto:
   ```env
   # LiveKit Configuration
   LIVEKIT_API_KEY="your_livekit_api_key"
   LIVEKIT_API_SECRET="your_livekit_api_secret"
   LIVEKIT_URL="your_livekit_url"

   # OpenAI Configuration
   OPENAI_API_KEY="your_openai_api_key"
   OPENAI_CHAT_MODEL="gpt-4o-mini"

   # Deepgram STT
   DEEPGRAM_API_KEY="your_deepgram_api_key"

   # Backend API
   BASE_API_URL="http://localhost:3000"
   
   # Optional: Additional TTS providers
   CARTESIA_API_KEY="your_cartesia_api_key"
   ```

## 🎮 Uso

Para iniciar el agente María:

```bash
python main.py
```

Esto conectará el agente al servidor LiveKit y estará listo para unirse a salas de conversación.

### Características del Agente
- **Saludo personalizado**: Genera mensajes de bienvenida variados
- **Conversación natural**: Responde de forma empática y especializada
- **Sesiones de 30 minutos**: Con finalización automática y QR de contribución
- **Historial persistente**: Guarda todas las conversaciones
- **Respuestas multimedia**: Crea contenido visual interactivo automáticamente

## 📁 Estructura del Proyecto

```
LiveKit_Agent_MarIA/
├── main.py                          # Punto de entrada principal
├── maria_agent.py                   # Lógica del agente y procesamiento
├── maria_system_prompt.txt          # Prompt especializado en ansiedad
├── text_utils.py                    # Utilidades de procesamiento de texto
├── emotion_detector.py              # Detección de emociones (experimental)
├── adaptive_tts_manager.py          # Gestión de TTS adaptativo
├── http_session_manager.py          # Manejo de sesiones HTTP
├── config.py                        # Configuración del sistema
├── throttler.py                     # Control de rate limiting
├── plugin_loader.py                 # Carga de plugins dinámicos
├── requirements.txt                 # Dependencias Python
├── RESPUESTAS_ENRIQUECIDAS.md      # Documentación del sistema multimedia
├── ADAPTIVE_VOICE_SYSTEM.md        # Documentación del sistema de voz
└── README.md                        # Este archivo
```

## 🎨 Personalización del Prompt

El comportamiento y personalidad de María se define en `maria_system_prompt.txt`. Este archivo incluye:

- **Especialización en ansiedad**: Técnicas y enfoques terapéuticos
- **Personalización dinámica**: Uso de variables como `{username}` y `{latest_summary}`
- **Tono empático**: Lenguaje especializado y profesional
- **Respuestas enriquecidas**: Instrucciones para usar elementos multimedia

## 🔧 Funcionalidades Avanzadas

### Sistema de Voz Adaptativo
- **Múltiples proveedores TTS**: Cartesia, Silero, OpenAI
- **Detección emocional**: Adapta el tono según el contexto
- **Control de velocidad**: Ajuste dinámico según la situación

### Gestión de Sesiones
- **Timeout de 30 minutos**: Previene sesiones muy largas
- **Resúmenes automáticos**: Para continuidad entre sesiones
- **Persistencia de datos**: Historial completo de conversaciones

### Integración con Backend
- **API REST**: Comunicación con aplicación web
- **Manejo de errores**: Reintentos automáticos y fallbacks
- **Throttling**: Control de rate limiting para APIs

## 🐛 Solución de Problemas

### Errores Comunes
1. **Error 401 en APIs**: Verificar claves API en `.env`
2. **Problemas de conexión**: Comprobar URL de LiveKit
3. **Errores de STT**: Validar configuración de Deepgram
4. **Problemas de TTS**: Verificar proveedores disponibles

### Logs y Depuración
El agente incluye logging detallado para facilitar la depuración. Los logs muestran:
- Procesamiento de mensajes
- Detección de respuestas enriquecidas
- Estado de sesiones
- Errores de API

## 📄 Documentación Adicional

- [RESPUESTAS_ENRIQUECIDAS.md](./RESPUESTAS_ENRIQUECIDAS.md): Sistema multimedia completo
- [ADAPTIVE_VOICE_SYSTEM.md](./ADAPTIVE_VOICE_SYSTEM.md): Sistema de voz adaptativo
- `maria_system_prompt.txt`: Prompt base del agente

## 🤝 Contribuciones

Este proyecto está diseñado para ayudar a personas con ansiedad. Las contribuciones son bienvenidas, especialmente:
- Mejoras en técnicas de manejo de ansiedad
- Optimizaciones de rendimiento
- Nuevas funcionalidades de respuestas enriquecidas
- Documentación y ejemplos

## 📞 Soporte

Para problemas técnicos o mejoras, revisa:
1. Los logs del agente para errores específicos
2. La documentación de respuestas enriquecidas
3. Las configuraciones de `.env`
4. El estado de las APIs externas