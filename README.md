# CAWL - Asistente Local de Desarrollo

**CAWL** (Control & Action Web Loop) es un asistente local orientado a desarrollo de software. Ejecuta tareas con modelos abiertos via **Ollama** y trabaja sobre archivos reales del proyecto para producir cambios estructurados, claros y eficientes.

> v0.3.0 - Sin API keys. Sin costos por nube. Tu codigo se queda en tu maquina.

## Características

| Feature | Descripción |
|---|---|
| Shell interactiva | Terminal con historial, autocompletado, resumen de sesión y modos `verbose` / `compact` |
| Planner → Executor | Descompone tareas en pasos ejecutables y los resuelve uno por uno |
| Multi-agente | Orquestador con workers especializados, secuencial o en paralelo |
| Confirmación avanzada | 4 modos de ejecución (interactive, trusted, dry-run, safe-only) + riesgo clasificado por comando |
| Tool loop compartido | CLI, Shell y UI usan el mismo núcleo de ejecución de herramientas |
| Memoria por proyecto | Cada proyecto mantiene su propia memoria en `.cawl/memory.json` |
| Estado en tiempo real | Spinner en terminal y burbuja animada en la UI |
| Selector de modelos | Detecta modelos locales de Ollama y permite elegir al iniciar |
| Seguridad por capas | Sanitización de comandos, timeouts configurables, kill tree en timeouts |
| Config flexible | Overrides por archivo de proyecto, usuario, o variables de entorno |

## Filosofía

CAWL está enfocado en:

- Codigo bien estructurado
- Salidas claras y organizadas
- Cambios mantenibles
- Uso eficiente de herramientas
- Contexto real antes de responder

## Instalación

Requisitos:

- Python 3.10+
- [Ollama](https://ollama.ai) instalado y corriendo

```bash
git clone <repo>
cd cawl_agent
pip install -e .
ollama pull qwen2.5-coder:7b
ollama pull huihui_ai/qwen3-abliterated:8b
cawl status
```

## Flujo recomendado

```bash
cd mi_proyecto
cawl init
```

Luego:

1. Completa `parametros/contexto.md`
2. Crea una tarea en `tareas/`
3. Ejecuta `cawl run --task tareas/mi_tarea.md`

## Comandos

### Shell interactiva principal

```bash
cawl run
```

Abre la shell principal con:

- Historial persistente
- Tab completion
- Prompt con proyecto, modelo y cantidad de archivos en contexto
- Toolbar inferior con atajos
- Comandos de control de sesion

Comandos utiles:

| Comando | Accion |
|---|---|
| `/help` | Mostrar ayuda |
| `/status` | Verificar Ollama y el modelo activo |
| `/session` | Mostrar resumen de sesion |
| `/models` | Listar modelos locales |
| `/context` | Ver archivos en contexto |
| `/add <file>` | Agregar archivo al contexto |
| `/remove <file>` | Remover archivo del contexto |
| `/clear-context` | Limpiar contexto |
| `/verbose on|off` | Alternar salida detallada |
| `/compact on|off` | Alternar salida compacta |
| `/model pick` | Elegir un modelo local |
| `/project <path>` | Cambiar proyecto activo |
| `/clear` | Limpiar historial del chat |
| `/reset` | Limpiar chat y contexto |
| `/quit` | Salir |

Atajos:

- `Enter` envia
- `Ctrl+J` inserta nueva linea
- `Tab` autocompleta
- `Up / Down` recorre historial

### Alias interactivo

```bash
cawl shell
```

Abre la misma experiencia interactiva que `cawl run`.

### Consulta unica

```bash
cawl run -c "analiza la estructura del proyecto"
```

### Ejecutar tarea

```bash
cawl run --task tareas/mi_tarea.md
```

### Ver plan sin ejecutar

```bash
cawl plan --task tareas/mi_tarea.md
```

### Watch mode

```bash
cawl watch --task tareas/mi_tarea.md
```

### Multi-agente

```bash
cawl multi -c "refactoriza auth.py y documenta cambios" --workers coder,reviewer,documenter
```

### UI grafica

```bash
cawl ui
```

## Selección de modelos

Puedes elegir modelo al iniciar:

```bash
cawl run --select-model
cawl shell --select-model
cawl ui --select-model
cawl status --select-model
```

## Configuración

Archivo base (`cawl/config/config.yaml`):

```yaml
executor:
  model: "qwen2.5-coder:7b"
  confirm_commands: true
  max_tool_iterations: 20
  max_history_chars: 12000
  max_history_turns: 4
  max_json_retries: 2
  command_timeout: 60
  llm_timeout: 300
  llm_max_retries: 3
  llm_retry_delay: 2
  streaming: true
  streaming_throttle_ms: 200

planner:
  model: "qwen2.5-coder:7b"

tools:
  max_read_size: 102400
  max_file_write_size: 1048576

confirmation:
  execution_mode: interactive
```

Prioridad de configuración (de mayor a menor):

1. Variables de entorno `CAWL_*`
2. `./.cawl/config.yaml` del proyecto
3. `~/.cawl/config.yaml`
4. `cawl/config/config.yaml`

## Arquitectura

```text
Usuario
  |
  v
Shell / CLI / UI ──── Shared Tool Loop (tool_loop.py)
  |                        |
  v                        v
Planner → Executor    Confirmation System
  |                   (confirmation.py + command_risk.py)
  |                    └─ interactive / trusted / dry-run / safe-only
  v
Tool Registry
  ├─ file_tools (read, write, list, grep, glob, mkdir)
  ├─ system_tools (run_command — sanitizado, timeout, kill tree)
  └─ web_tools (search_web)
        |
        v
   Ollama API → Modelos locales
```

## Estructura del proyecto

```text
cawl_agent/
├── cawl/
│   ├── __init__.py
│   ├── ui.py                      # Interfaz gráfica PyQt5
│   ├── cli/
│   │   └── main.py                # CLI, argparser, agent loop
│   ├── config/
│   │   ├── config.py              # Cargador de config 4 capas
│   │   └── config.yaml            # Valores por defecto
│   ├── core/
│   │   ├── executor.py            # Plan step executor
│   │   ├── llm_client.py          # Cliente Ollama API
│   │   ├── loop.py                # Plan → execute loop
│   │   ├── tool_loop.py           # Tool loop compartido (CLI/Shell/UI)
│   │   ├── multi_agent.py         # Orquestador + workers
│   │   ├── confirmation.py        # Confirmación con 4 modos
│   │   ├── command_risk.py        # Clasificador de riesgo
│   │   ├── ollama_models.py       # Descubrimiento de modelos
│   │   ├── planner.py             # Descomposición de tareas
│   │   └── status.py              # Emisor pub/sub en tiempo real
│   ├── memory/
│   │   ├── global_memory.py       # Memoria entre proyectos
│   │   └── project_memory.py      # Memoria por proyecto
│   ├── shell/
│   │   ├── shell.py               # Shell interactiva (prompt_toolkit)
│   │   ├── completer.py           # Tab-completion
│   │   ├── context.py             # Gestor de contexto
│   │   └── formatter.py           # Formateo de salida
│   ├── tasks/
│   │   └── parser.py              # Parser de archivos .md
│   └── tools/
│       ├── registry.py            # Registro y descripción de tools
│       ├── file_tools.py          # read, write, list, grep, glob, mkdir
│       ├── system_tools.py        # run_command (sanitizado)
│       └── web_tools.py           # search_web (DuckDuckGo)
├── tareas/                        # Archivos de tarea .md
├── parametros/                    # Contexto y parámetros del proyecto
└── README.md
```

## Seguridad

- **Confirmación obligatoria**: `run_command` requiere autorización por defecto (modo `interactive`)
- **4 modos de ejecución**: `interactive` (preguntar), `trusted` (confiar), `dry-run` (simular), `safe-only` (solo bajo riesgo)
- **Clasificación de riesgo**: cada comando se clasifica como LOW, MEDIUM, HIGH o CRITICAL según su operación
- **Sanitización**: se bloquean patrones peligrosos (`$(`, `` ` ``, `${`) antes de ejecutar cualquier comando
- **Timeouts configurables**: comandos (60s), planner (300s), `ollama pull` (600s)
- **Kill process tree**: al expirar el timeout, se mata el proceso y todos sus hijos (`taskkill /T /F` en Windows, `os.killpg` en Unix)
- **Aislamiento por proyecto**: caché de herramientas y configuración separados por proyecto activo
- **Contexto explícito**: planner y executor reciben `project_path` y `model` de forma explícita, sin depender de estado global

## Solución de problemas

### Ollama no responde

```bash
ollama serve
cawl status
```

### Modelo no encontrado

```bash
cawl pull
```

### Shell lenta o con demasiado historial

Usa:

```text
/clear
/reset
/compact on
```

## Hoja de ruta

- [x] Shell interactiva unificada
- [x] Selector inicial de modelos locales
- [x] Caché aislado por proyecto
- [x] Planner y executor con contexto explícito
- [x] UI gráfica
- [x] Confirmación de comandos con modos de ejecución
- [x] Sistema de riesgo clasificado por comando
- [x] Tool loop unificado (eliminada duplicación CLI/Shell/UI)
- [x] Sanitización de comandos peligrosos
- [x] Kill process tree en timeouts
- [ ] Selector visual de modelo dentro de la UI
- [ ] Integración más profunda con Git
- [ ] Interfaz web opcional

## Licencia

MIT
