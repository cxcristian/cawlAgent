# CAWL - Local Agent System

**CAWL** (Control & Action Web Loop) es un sistema de agente local diseñado para ejecutar tareas complejas siguiendo una arquitectura profesional de **Planner / Executor**.

## Filosofía del Proyecto

CAWL está diseñado bajo la premisa de que los modelos locales (como **Qwen2.5-Coder**) tienen una inteligencia limitada comparada con gigantes como Claude 3.5 Sonnet o GPT-4o, pero ofrecen la ventaja de ser **gratuitos, privados y sin límites de tokens**.

El flujo de trabajo ideal para CAWL es:
1.  **IA Maestro (Superior)**: Una IA como Claude o GPT-4 diseña una lista de tareas detalladas (en formato `.md`).
2.  **CAWL (Agente Local)**: Recibe estas tareas y las ejecuta paso a paso en tu máquina local, razonando sobre qué herramientas usar para lograr el objetivo sin preocuparse por el consumo de créditos de API.

## Instalación Global

Para poder ejecutar `cawl` desde cualquier terminal de tu sistema:

1.  Asegúrate de tener Python 3.8+ instalado.
2.  Clona este repositorio o descarga los archivos.
3.  En la carpeta raíz del proyecto, ejecuta:
    ```bash
    pip install -e .
    ```

Esto instalará las dependencias necesarias (`pyyaml`, `requests`) y registrará el comando `cawl` globalmente.

## Uso

### 1. Inicializar un Proyecto
Ve a la carpeta de tu nuevo proyecto y ejecuta:
```bash
cawl init
```
Esto creará una carpeta `.cawl/` donde se guardará la memoria y el contexto de ese proyecto específico, evitando que choque con otros.

### 2. Planificar una Tarea
Si quieres ver qué pasos va a seguir el agente antes de ejecutarlos:
```bash
cawl plan --task camino/a/tu_tarea.md
```

### 3. Ejecutar una Tarea
Para que el agente se ponga manos a la obra:
```bash
cawl run --task camino/a/tu_tarea.md
```

## Configuración

El archivo de configuración se encuentra en `cawl/config/config.yaml`. Por defecto, está configurado para usar:
- **Modelo**: `qwen2.5-coder:7b` (vía Ollama).
- **Endpoint**: `http://localhost:11434/api`.

Asegúrate de tener **Ollama** instalado y corriendo. El agente requiere el modelo `qwen2.5-coder:7b`. Puedes descargarlo automáticamente con:
```bash
cawl pull
```

O manualmente con Ollama:
```bash
ollama run qwen2.5-coder:7b
```

## Estructura de Tareas (.md)
El agente lee archivos Markdown simples. Ejemplo:
```markdown
# Objetivo: Limpiar archivos temporales
1. Listar los archivos en la carpeta actual.
2. Crear una carpeta llamada 'backup'.
3. Mover todos los archivos .log a 'backup'.
```

## Aislamiento de Contexto
CAWL detecta automáticamente el contexto basándose en el directorio actual. Toda la "memoria" del agente (qué ha hecho, qué errores ha tenido) se persiste en el archivo `.cawl/memory.json` local del proyecto actual.
