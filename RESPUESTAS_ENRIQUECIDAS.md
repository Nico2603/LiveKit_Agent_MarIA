# Sistema de Respuestas Enriquecidas de María

María cuenta con un sistema avanzado de respuestas enriquecidas que permite crear experiencias interactivas más allá del texto y voz. Este sistema está **completamente implementado** y funcional.

## 🎯 Funcionalidades Automáticas

### QR de Pago Automático
Al finalizar una sesión (después de 30 minutos o despedidas naturales), el sistema automáticamente agrega:
- **Mensaje ampliado**: "Si esta conversación te fue útil, puedes apoyar el proyecto con una contribución voluntaria."
- **Imagen QR**: Código QR para contribución desde `/img/QR.jpg`
- **Tarjeta informativa**: Explicación sobre el apoyo voluntario

### Detección Automática de Enlaces
El sistema detecta automáticamente URLs en el texto y crea botones interactivos:
- **YouTube**: Botón "Ver Video" (azul, icono play)
- **Google Docs**: Botón "Ver Documento" (cian, icono info)  
- **Otros enlaces**: Botón "Abrir Enlace" (gris, icono info)

**Ejemplo automático:**
```
María: "Te comparto este recurso: https://youtube.com/watch?v=ejemplo"
Resultado: "Te comparto este recurso: [enlace]" + Botón "Ver Video"
```

### Botones de Video Automáticos
Cuando se usa `[SUGERIR_VIDEO]`, se crean automáticamente:
- **Botón interactivo**: "Ver: [Título]" con icono play
- **Tarjeta explicativa**: Con instrucciones de uso
- **Compatibilidad**: Mantiene el sistema tradicional

## 📝 Etiquetas Manuales Disponibles

### 1. Imágenes
Muestra imágenes con título y descripción opcional.

**Formato:**
```
[IMAGEN: título, url, alt?, descripción?]
```

**Ejemplo:**
```
[IMAGEN: Técnica de respiración 4-7-8, https://ejemplo.com/respiracion.jpg, Diagrama de respiración, Esta imagen muestra los pasos para la técnica 4-7-8]
```

### 2. Enlaces
Crea botones de enlaces a recursos externos.

**Formato:**
```
[ENLACE: título, url, descripción?, tipo?]
```

**Tipos disponibles:**
- `article`: Artículos (azul, icono documento)
- `resource`: Recursos (verde, icono estrella)
- `guide`: Guías (morado, icono bombilla)
- `external`: Enlaces externos (gris, icono enlace) - **por defecto**

**Ejemplo:**
```
[ENLACE: Guía completa sobre ansiedad, https://example.com/guia-ansiedad, Una guía detallada sobre manejo de la ansiedad, guide]
```

### 3. Botones Interactivos
Crea botones que ejecutan acciones específicas.

**Formato:**
```
[BOTON: título, acción, estilo?, icono?]
```

**Estilos disponibles:**
- `primary`: Azul (por defecto)
- `secondary`: Gris
- `success`: Verde
- `warning`: Amarillo
- `info`: Cian

**Iconos disponibles:**
- `play`: Reproducir
- `check`: Verificación
- `info`: Información
- `activity`: Actividad

**Ejemplo:**
```
[BOTON: Iniciar ejercicio de respiración, start_breathing_exercise, success, play]
```

### 4. Tarjetas Informativas
Muestra información estructurada con listas opcionales.

**Formato:**
```
[TARJETA: título, contenido, tipo?, item1|item2|item3...]
```

**Tipos disponibles:**
- `tip`: Consejos (amarillo, bombilla)
- `technique`: Técnicas (azul, actividad)
- `exercise`: Ejercicios (verde, play)
- `info`: Información (cian, info) - **por defecto**
- `warning`: Advertencias (naranja, triángulo)

**Ejemplo:**
```
[TARJETA: Técnica 4-7-8 para Dormir, Esta técnica calma tu sistema nervioso rápidamente, technique, Inhala por la nariz durante 4 segundos|Retén la respiración por 7 segundos|Exhala por la boca durante 8 segundos|Repite 4 ciclos]
```

### 5. Videos (Compatibilidad)
Mantiene soporte para la etiqueta existente.

**Formato:**
```
[SUGERIR_VIDEO: título, url]
```

## 🚀 Ejemplo Completo de Uso

**Situación:** Usuario con ansiedad nocturna

**María responde:**
```
Entiendo esa inquietud que sientes al llegar la noche. Es muy común que la mente se acelere cuando queremos descansar. Te voy a compartir una técnica muy efectiva:

[TARJETA: Técnica 4-7-8 para Dormir, Esta técnica calma tu sistema nervioso rápidamente, technique, Inhala por la nariz durante cuatro segundos|Retén la respiración por siete segundos|Exhala por la boca durante ocho segundos|Repite cuatro ciclos]

Te comparto una imagen que muestra el patrón visual:

[IMAGEN: Respiración 4-7-8, https://ejemplo.com/respiracion-478.jpg, Diagrama de respiración, Esta imagen muestra cómo seguir el ritmo de la técnica 4-7-8]

¿Te gustaría que practiquemos esta técnica juntos ahora?

[BOTON: Practicar respiración ahora, start_breathing_exercise, success, play]

También tengo un video guiado que puede ayudarte:

[SUGERIR_VIDEO: Meditación 4-7-8 para dormir, https://www.youtube.com/watch?v=ejemplo]

Si quieres explorar más técnicas, aquí tienes recursos adicionales:

[ENLACE: Guía completa sobre ansiedad nocturna, https://ejemplo.com/ansiedad-nocturna, Manual con técnicas específicas para la noche, guide]
```

### Resultado Visual:
1. ✅ **Tarjeta azul** con técnica y lista de pasos
2. ✅ **Imagen** del diagrama de respiración
3. ✅ **Botón verde "Practicar respiración ahora"** con icono de play
4. ✅ **Botón azul "Ver: Meditación 4-7-8 para dormir"** (creado automáticamente)
5. ✅ **Tarjeta informativa** sobre el video recomendado
6. ✅ **Botón morado "Guía completa sobre ansiedad nocturna"** con icono de guía

## ⚠️ Respuesta con Advertencia

```
Es importante recordar que si sientes pensamientos de autolesión, debes buscar ayuda profesional inmediatamente.

[TARJETA: Busca ayuda profesional, Si tienes pensamientos de autolesión o suicidio, no estás solo y hay ayuda disponible, warning, Línea Nacional: 106|Policía: 123|Emergencias: 911|Bomberos: 119]

[BOTON: Contactar línea de crisis, contact_crisis_line, warning, info]

[ENLACE: Recursos de salud mental, https://ejemplo.com/recursos, Directorio de profesionales de salud mental, resource]
```

## 🔧 Acciones de Botones Soportadas

### Acciones Automáticas
- `open_video:[URL]`: Abre video en nueva pestaña
- `open_link:[URL]`: Abre enlace en nueva pestaña

### Acciones Personalizadas
- `start_breathing_exercise`: Iniciar ejercicio de respiración
- `schedule_reminder`: Programar recordatorio
- `show_more_techniques`: Mostrar más técnicas
- `contact_crisis_line`: Contactar línea de crisis

## 📋 Notas Técnicas Importantes

1. **Orden de procesamiento**: Las etiquetas se procesan en el orden que aparecen
2. **URLs válidas**: Todas las URLs deben empezar con `http` o `https`
3. **Separación**: Parámetros se separan por comas, items de listas por `|`
4. **Parámetros opcionales**: Se pueden omitir manteniendo las comas
5. **Compatibilidad total**: Mantiene compatibilidad con sistemas anteriores
6. **Sin límites**: No hay límite en cantidad de elementos por respuesta

## 🎨 Mejores Prácticas

- **No deletrees URLs**: El sistema crea botones automáticamente
- **Confía en la automatización**: El QR y botones se generan automáticamente
- **Combina elementos**: Usa diferentes tipos para respuestas más ricas
- **Sé específico**: Usa títulos descriptivos y acciones claras
- **Mantén cohesión**: El contenido enriquecido debe complementar el texto
- **Considera el contexto**: Usa el elemento más apropiado para cada situación
- **Accesibilidad**: Siempre incluye texto alternativo para imágenes

## 🔍 Ventajas del Sistema

1. **Para María**: No necesita deletrear URLs ni mencionar mecánicas técnicas
2. **Para el usuario**: Experiencia visual e interactiva más rica
3. **Para el proyecto**: QR de pago integrado naturalmente
4. **Para desarrolladores**: Sistema extensible y compatible

Este sistema convierte cada conversación en una experiencia multimedia rica y profesional, manteniendo la naturalidad de la interacción por voz. 