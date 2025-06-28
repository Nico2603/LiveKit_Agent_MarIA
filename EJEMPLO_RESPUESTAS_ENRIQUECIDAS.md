# Ejemplo Completo: Respuestas Enriquecidas de María

Este documento muestra un ejemplo real de cómo María puede usar todas las nuevas funcionalidades de respuestas enriquecidas en una conversación típica.

## Conversación de Ejemplo

### Situación: Usuario con ansiedad nocturna

**Usuario:** "María, tengo mucha ansiedad por las noches y no puedo dormir"

**María responde:**
```
Entiendo esa inquietud que sientes al llegar la noche. Es muy común que la mente se acelere cuando queremos descansar. Te voy a compartir una técnica muy efectiva para estos momentos:

[TARJETA: Técnica 4-7-8 para Dormir, Esta técnica calma tu sistema nervioso rápidamente, technique, Inhala por la nariz durante cuatro segundos|Retén la respiración por siete segundos|Exhala por la boca durante ocho segundos|Repite cuatro ciclos]

Te comparto una imagen que muestra el patrón visual:

[IMAGEN: Respiración 4-7-8, https://ejemplo.com/respiracion-478.jpg, Diagrama de respiración, Esta imagen muestra cómo seguir el ritmo de la técnica 4-7-8]

¿Te gustaría que practiquemos esta técnica juntos ahora?

[BOTON: Practicar respiración ahora, start_breathing_exercise, success, play]

También tengo un video guiado que puede ayudarte:

[SUGERIR_VIDEO: Meditación 4-7-8 para dormir, https://www.youtube.com/watch?v=YRPh_GaiL8s]

Si quieres explorar más técnicas, aquí tienes recursos adicionales:

[ENLACE: Guía completa sobre ansiedad nocturna, https://ejemplo.com/ansiedad-nocturna, Manual con técnicas específicas para la noche, guide]

[ENLACE: Ejercicios de relajación muscular, https://docs.google.com/document/ejemplo, Documento con rutinas paso a paso, resource]
```

### Lo que ve el usuario:

1. **Texto natural de María** (se convierte a voz)
2. **Tarjeta azul** con la técnica 4-7-8 y lista de pasos
3. **Imagen** del diagrama de respiración
4. **Botón verde "Practicar respiración ahora"** con icono de play
5. **Botón azul "Ver: Meditación 4-7-8 para dormir"** (creado automáticamente)
6. **Tarjeta informativa** sobre el video recomendado
7. **Botón morado "Guía completa sobre ansiedad nocturna"** con icono de guía
8. **Botón cian "Ver Documento"** para los ejercicios

### Finalización de sesión

**Usuario:** "Muchas gracias María, creo que con esto tengo suficiente por hoy"

**María responde:**
```
Me alegra mucho saber que te sientes equipado con estas herramientas. Has mostrado una actitud muy positiva para cuidar tu bienestar. Gracias por confiar en mí hoy, [nombre del usuario].
```

### Lo que se agrega automáticamente:

Cuando María usa una despedida natural, el sistema automáticamente agrega:

1. **Mensaje ampliado:** "...Si esta conversación te fue útil, puedes apoyar el proyecto con una contribución voluntaria."

2. **Imagen del QR de pago** con título y descripción

3. **Tarjeta informativa azul** con:
   - Título: "Apoyo Voluntario"
   - Contenido sobre cómo la contribución ayuda
   - Lista de beneficios del apoyo

## Funcionalidades Demostradas

### ✅ Respuestas Enriquecidas Manuales
- **Tarjetas**: Técnica con pasos estructurados
- **Imágenes**: Diagrama visual de apoyo
- **Botones**: Acción de práctica inmediata
- **Enlaces**: Recursos adicionales categorizados

### ✅ Automatizaciones Inteligentes
- **Botones de video**: Creados automáticamente para YouTube
- **Detección de enlaces**: URLs convertidas a botones automáticamente
- **QR de pago**: Aparece automáticamente al finalizar sesión
- **Compatibilidad**: Sistema anterior sigue funcionando

### ✅ Experiencia del Usuario
- **Sin URLs deletreadas**: Todo accesible via botones
- **Interfaz visual rica**: Colores, iconos y estructura clara
- **Interactividad**: Botones funcionales que abren enlaces
- **Profesionalismo**: QR de pago discreto y apropiado

### ✅ Acciones de Botones
- `start_breathing_exercise`: Botón de práctica
- `open_video:[URL]`: Botones de video automáticos
- `open_link:[URL]`: Botones de enlace automáticos

## Ventajas del Sistema

1. **Para María**: No necesita deletrear URLs ni mencionar mecánicas técnicas
2. **Para el usuario**: Experiencia visual e interactiva más rica
3. **Para el proyecto**: QR de pago integrado naturalmente
4. **Para desarrolladores**: Sistema extensible y compatible

## Código de Ejemplo Generado

```json
{
  "text": "Entiendo esa inquietud que sientes al llegar la noche...",
  "richContent": {
    "cards": [
      {
        "title": "Técnica 4-7-8 para Dormir",
        "content": "Esta técnica calma tu sistema nervioso rápidamente",
        "type": "technique",
        "items": [
          "Inhala por la nariz durante cuatro segundos",
          "Retén la respiración por siete segundos",
          "Exhala por la boca durante ocho segundos",
          "Repite cuatro ciclos"
        ]
      },
      {
        "title": "Video Recomendado",
        "content": "Te he preparado un video que puede ayudarte: Meditación 4-7-8 para dormir",
        "type": "info",
        "items": [
          "Presiona el botón para ver el video",
          "Se abrirá en una nueva pestaña",
          "Puedes pausar y volver cuando quieras"
        ]
      }
    ],
    "images": [
      {
        "title": "Respiración 4-7-8",
        "url": "https://ejemplo.com/respiracion-478.jpg",
        "alt": "Diagrama de respiración",
        "caption": "Esta imagen muestra cómo seguir el ritmo de la técnica 4-7-8"
      }
    ],
    "buttons": [
      {
        "title": "Practicar respiración ahora",
        "action": "start_breathing_exercise",
        "style": "success",
        "icon": "play"
      },
      {
        "title": "Ver: Meditación 4-7-8 para dormir",
        "action": "open_video:https://www.youtube.com/watch?v=YRPh_GaiL8s",
        "style": "primary",
        "icon": "play"
      },
      {
        "title": "Guía completa sobre ansiedad nocturna",
        "action": "open_link:https://ejemplo.com/ansiedad-nocturna",
        "style": "from-purple-500 to-purple-600",
        "icon": "guide"
      },
      {
        "title": "Ver Documento",
        "action": "open_link:https://docs.google.com/document/ejemplo",
        "style": "info",
        "icon": "info"
      }
    ],
    "suggestedVideo": {
      "title": "Meditación 4-7-8 para dormir",
      "url": "https://www.youtube.com/watch?v=YRPh_GaiL8s"
    }
  }
}
```

Este ejemplo demuestra cómo María puede ofrecer una experiencia completamente enriquecida sin comprometer la naturalidad de la conversación ni la experiencia de voz. 