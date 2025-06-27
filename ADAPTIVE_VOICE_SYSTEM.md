# Sistema de Voz Adaptativa para María

## Descripción General

El sistema de voz adaptativa de María permite que la voz del asistente virtual se adapte dinámicamente según las emociones detectadas en el texto del usuario. Esto crea una experiencia más empática y natural en las conversaciones sobre manejo de ansiedad.

## Características Principales

### 🎭 Detección de Emociones
- **11 tipos de emociones** detectadas automáticamente
- **4 niveles de intensidad** (Baja, Media, Alta, Crítica)
- **Análisis en tiempo real** del texto del usuario
- **Palabras clave y patrones** específicos para cada emoción

### 🔊 Adaptación de Voz
- **Velocidad variable** (-0.6 a -0.1) más pausada para calmar
- **Modulación emocional** usando los controles de Cartesia
- **Perfiles dinámicos** según el contexto emocional
- **Fallback automático** en caso de errores

### ⚡ Integración Transparente
- **Sin interrupciones** en el flujo normal de conversación
- **Configuración por defecto** más calmada (-0.3 vs 1.0)
- **Habilitación/deshabilitación** via configuración
- **Logging detallado** para debugging

## Emociones Detectadas

### Emociones Negativas (Requieren Mayor Empatía)

#### 🔴 Ansiedad
- **Patrones**: "ansiedad", "nervioso", "preocupado", "no puedo parar de pensar"
- **Respuesta de voz**: Muy pausada (-0.5), alta positividad + ligera tristeza
- **Objetivo**: Calmar y tranquilizar

#### 😢 Tristeza
- **Patrones**: "triste", "deprimido", "ganas de llorar", "sin ánimo"
- **Respuesta de voz**: Pausada (-0.4), positividad baja + tristeza alta
- **Objetivo**: Comprensión y esperanza

#### 😰 Miedo
- **Patrones**: "miedo", "terror", "pánico", "me aterra"
- **Respuesta de voz**: Muy pausada (-0.5), alta positividad
- **Objetivo**: Protección y tranquilidad

#### 😤 Estrés
- **Patrones**: "estresado", "agobiado", "presión", "no puedo más"
- **Respuesta de voz**: Pausada (-0.4), positividad ligera
- **Objetivo**: Serenidad y equilibrio

#### 😠 Frustración
- **Patrones**: "frustrado", "harto", "rabia", "no aguanto"
- **Respuesta de voz**: Pausada (-0.3), validante y comprensiva
- **Objetivo**: Validación y paciencia

#### 😵 Confusión
- **Patrones**: "confundido", "no entiendo", "perdido", "sin rumbo"
- **Respuesta de voz**: Pausada (-0.4), clarificadora
- **Objetivo**: Claridad y paciencia

#### 😱 Desesperación
- **Patrones**: "desesperado", "sin esperanza", "no hay solución"
- **Respuesta de voz**: Muy pausada (-0.6), muy empática pero esperanzadora
- **Objetivo**: Contención y esperanza

### Emociones Neutras/Positivas

#### ⚡ Urgencia
- **Patrones**: "urgente", "rápido", "ahora mismo", "inmediatamente"
- **Respuesta de voz**: Menos pausada (-0.2), equilibrada
- **Objetivo**: Atención eficiente sin ansiedad

#### 🌅 Esperanza
- **Patrones**: "esperanza", "mejorando", "progreso", "creo que puedo"
- **Respuesta de voz**: Ligeramente pausada (-0.2), alta positividad
- **Objetivo**: Aliento y motivación

#### 😌 Calma
- **Patrones**: "tranquilo", "en paz", "equilibrio", "me siento bien"
- **Respuesta de voz**: Naturalmente pausada (-0.1), neutral
- **Objetivo**: Mantener estabilidad

#### 😐 Neutral
- **Por defecto** cuando no se detectan emociones específicas
- **Respuesta de voz**: Pausada (-0.3), empática por defecto
- **Objetivo**: Calidez y empatía básica

## Configuración de Intensidad

### Factores de Intensidad
1. **Número de coincidencias** de patrones emocionales
2. **Presencia de intensificadores**: "muy", "mucho", "extremadamente"
3. **Indicadores de crisis**: "ayuda", "socorro", "no puedo más"

### Niveles de Respuesta
- **Baja**: Ajustes mínimos de voz
- **Media**: Modulación notable
- **Alta**: Cambios significativos de velocidad y emoción
- **Crítica**: Máxima adaptación empática

## Parámetros de Voz por Emoción

| Emoción | Velocidad | Emociones Cartesia | Descripción |
|---------|-----------|-------------------|-------------|
| Ansiedad Alta | -0.5 | positivity:high, sadness:low | Muy calmante |
| Ansiedad Media | -0.3 | positivity:low, sadness:low | Empática y serena |
| Tristeza | -0.4 | positivity:low, sadness:high | Comprensiva |
| Miedo | -0.5 | positivity:high | Protectora |
| Estrés | -0.4 | positivity:low | Serena |
| Frustración | -0.3 | positivity:low, sadness:low | Validante |
| Desesperación | -0.6 | positivity:high, sadness:high | Muy empática |
| Urgencia | -0.2 | positivity:low | Equilibrada |
| Confusión | -0.4 | positivity:low | Clara y paciente |
| Esperanza | -0.2 | positivity:high | Alentadora |
| Calma | -0.1 | positivity:low | Natural |
| Neutral | -0.3 | ninguna | Empática por defecto |

## Flujo del Sistema

### 1. Detección
```
Usuario envía mensaje
    ↓
Análisis emocional automático
    ↓
Clasificación de emoción dominante
    ↓
Determinación de intensidad
```

### 2. Adaptación
```
Generación de perfil de voz
    ↓
Creación de instancia TTS adaptativa
    ↓
Aplicación temporal al AgentSession
    ↓
Reproducción con voz adaptada
```

### 3. Restauración
```
Finalización del mensaje
    ↓
Restauración del TTS original
    ↓
Preparación para próximo análisis
```

## Configuración

### Variables de Entorno
```bash
# Habilitar/deshabilitar voz adaptativa
ENABLE_ADAPTIVE_VOICE=true

# Velocidad base más calmada
CARTESIA_SPEED=-0.3

# Otros parámetros de Cartesia
CARTESIA_MODEL=sonic-2
CARTESIA_VOICE_ID=5c5ad5e7-1020-476b-8b91-fdcbe9cc313c
CARTESIA_LANGUAGE=es
```

### Configuración en Código
```python
# En config.py
enable_adaptive_voice: bool = Field(True, env='ENABLE_ADAPTIVE_VOICE')
cartesia_speed: float = Field(-0.3, env='CARTESIA_SPEED')  # Más calmada
```

## Ejemplos de Uso

### Ejemplo 1: Ansiedad Intensa
**Usuario**: "Estoy muy ansioso, mi mente no para de pensar y tengo mucho miedo"

**Detección**:
- Emoción: Ansiedad
- Intensidad: Alta (múltiples patrones + intensificador "muy")

**Respuesta**:
- Velocidad: -0.5 (muy pausada)
- Emoción: positivity:high, sadness:low
- Descripción: "Voz muy empática y calmante"

### Ejemplo 2: Tristeza Moderada
**Usuario**: "Me siento triste hoy, sin muchas ganas de hacer nada"

**Detección**:
- Emoción: Tristeza
- Intensidad: Media

**Respuesta**:
- Velocidad: -0.4 (pausada y comprensiva)
- Emoción: positivity:low, sadness:high
- Descripción: "Voz cálida y comprensiva"

### Ejemplo 3: Progreso Positivo
**Usuario**: "Siento que estoy mejorando, tengo más esperanza"

**Detección**:
- Emoción: Esperanza
- Intensidad: Media

**Respuesta**:
- Velocidad: -0.2 (ligeramente pausada pero energizada)
- Emoción: positivity:high
- Descripción: "Voz alentadora y esperanzadora"

## Beneficios del Sistema

### Para el Usuario
- **Mayor sensación de comprensión** y empatía
- **Reducción de ansiedad** por velocidad pausada
- **Respuesta emocional apropiada** al contexto
- **Experiencia más humana** y natural

### Para el Terapeuta/Profesional
- **Análisis automático** del estado emocional
- **Logs detallados** del progreso emocional
- **Adaptación sin intervención manual**
- **Consistencia en la respuesta empática**

## Logging y Monitoreo

### Logs de Detección Emocional
```
🎭 Estado emocional detectado: Ansiedad (Alta)
🎭 Perfil de voz preparado: Voz muy empática y calmante para ansiedad intensa
```

### Logs de Aplicación TTS
```
🎭 Obteniendo TTS adaptativo para respuesta...
🎭 TTS adaptativo aplicado temporalmente para este mensaje
🔊 Reproduciendo TTS ADAPTATIVO para mensaje (ID: 12345)
```

### Logs de Configuración
```
🎭 AdaptiveTTSManager inicializado - Voz adaptativa habilitada
🎭 Sistema de voz adaptativa: Habilitado
🎭 Sistema de voz adaptativa habilitado en MariaVoiceAgent
```

## Troubleshooting

### Problemas Comunes

#### 1. Voz Adaptativa No Funciona
- Verificar `ENABLE_ADAPTIVE_VOICE=true`
- Comprobar logs de inicialización
- Verificar que adaptive_tts_manager no sea None

#### 2. Detección Incorrecta de Emociones
- Revisar patrones en `emotion_detector.py`
- Ajustar umbrales de intensidad
- Agregar nuevos patrones específicos

#### 3. Errores de TTS
- El sistema tiene fallback automático
- Verificar configuración de Cartesia
- Comprobar conectividad API

### Debug y Testing
```python
# Probar detección manual
detector = EmotionDetector()
emotions = detector.detect_emotions("Estoy muy ansioso")
profile = detector.get_adaptive_voice_profile(emotions)
print(f"Perfil: {profile}")
```

## Extensibilidad

### Agregar Nuevas Emociones
1. Añadir enum en `EmotionType`
2. Definir patrones en `emotion_patterns`
3. Configurar respuesta en `get_adaptive_voice_profile`

### Ajustar Respuestas de Voz
1. Modificar velocidades en perfiles
2. Cambiar emociones de Cartesia
3. Ajustar umbrales de intensidad

### Integrar Análisis Avanzado
- Usar modelos de ML para detección
- Analizar historial de conversación
- Implementar aprendizaje de preferencias

## Conclusión

El sistema de voz adaptativa transforma a María en un asistente verdaderamente empático que responde no solo al contenido de lo que dice el usuario, sino también a cómo lo dice y el estado emocional que refleja. Esto crea una experiencia más humana y efectiva para el manejo de la ansiedad.

La implementación es robusta, con fallbacks automáticos y logging detallado, asegurando que la funcionalidad principal nunca se vea comprometida mientras proporciona una experiencia mejorada cuando todo funciona correctamente. 