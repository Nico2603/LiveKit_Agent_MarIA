# Guía de Despliegue en Render

## Variables de Entorno Requeridas

Configura las siguientes variables de entorno en Render:

### LiveKit (Requerido)
```
LIVEKIT_URL=wss://your-livekit-server.com
LIVEKIT_API_KEY=your_livekit_api_key  
LIVEKIT_API_SECRET=your_livekit_api_secret
LIVEKIT_AGENT_PORT=8000
```

### OpenAI (Requerido)
```
OPENAI_API_KEY=sk-your_openai_api_key
OPENAI_MODEL=gpt-4o-mini
```

### Cartesia TTS (Requerido)
```
CARTESIA_API_KEY=your_cartesia_api_key
CARTESIA_MODEL=sonic-spanish
CARTESIA_VOICE_ID=your_cartesia_voice_id
CARTESIA_LANGUAGE=es
CARTESIA_SPEED=1.0
```

### Deepgram STT (Requerido)
```
DEEPGRAM_API_KEY=your_deepgram_api_key
DEEPGRAM_MODEL=nova-2
```

### Backend API (Opcional)
```
API_BASE_URL=https://your-backend-api.com
```
*Si no se configura, usa por defecto: http://localhost:3000*

### Tavus Avatar (Opcional)
```
TAVUS_API_KEY=your_tavus_api_key
TAVUS_REPLICA_ID=your_tavus_replica_id
```

## Configuración en Render

1. Ve a tu servicio en Render
2. Navega a **Environment**
3. Agrega cada variable de entorno listada arriba
4. Guarda los cambios
5. El servicio se redesplegarà automáticamente

## Troubleshooting

### Error: "Field required [type=missing]"
- Verifica que todas las variables requeridas estén configuradas en Render
- Las variables opcionales pueden omitirse

### Error: "cannot import name 'tavus'"
- Este error es temporal y se resuelve automáticamente con el manejo de errores implementado
- El sistema funcionará sin Tavus si no está disponible

### Error: "ModuleNotFoundError: No module named 'pydantic_settings'"
- Asegúrate de que el requirements.txt incluya `pydantic-settings`
- Fuerza un nuevo build si es necesario 