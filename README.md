# CAWL - Asistente Local de Desarrollo

**CAWL** (Control & Action Web Loop) es un asistente local orientado a desarrollo de software. Ejecuta tareas con modelos abiertos via **Ollama** y trabaja sobre archivos reales del proyecto para producir cambios estructurados, claros y eficientes.

> v0.3.0 - Sin API keys. Sin costos por nube. Tu codigo se queda en tu maquina.

## Caracteristicas

| Feature | Descripcion |
|---|---|
| Shell interactiva | Terminal mejorada con historial, autocompletado, resumen de sesion y modos `verbose` / `compact` |
| Planner -> Executor | Descompone tareas en pasos ejecutables y luego los resuelve |
| Multi-agente | Orquestador con workers especializados, secuencial o en paralelo |
| Memoria por proyecto | Cada proyecto mantiene su propia memoria en `.cawl/memory.json` |
| Estado en tiempo real | Spinner en terminal y burbuja de estado en la UI |
| Selector de modelos | Detecta modelos locales de Ollama y permite elegir uno al iniciar |
| Confirmacion de comandos | Pide autorizacion antes de ejecutar comandos sensibles |
| Config flexible | Overrides por archivo, proyecto o variables de entorno |

## Filosofia

CAWL ya no usa una personalidad teatral. El agente esta enfocado en:

- Codigo bien estructurado
- Salidas claras y organizadas
- Cambios mantenibles
- Uso eficiente de herramientas
- Contexto real antes de responder

## Instalacion

Requisitos:

- Python 3.10+
- [Ollama](https://ollama.ai) instalado y corriendo

```bash
git clone <repo>
cd cawl_agent
pip install -e .
ollama pull qwen2.5-coder:7b
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

## Seleccion de modelos

Puedes elegir modelo al iniciar:

```bash
cawl run --select-model
cawl shell --select-model
cawl ui --select-model
cawl status --select-model
```

## Configuracion

Archivo base:

```yaml
executor:
  model: "qwen2.5-coder:7b"
  confirm_commands: true
  max_tool_iterations: 20
  max_history_chars: 12000
  max_history_turns: 4
  max_json_retries: 2
  command_timeout: 60
  streaming: true
  streaming_throttle_ms: 200

planner:
  model: "qwen2.5-coder:7b"

tools:
  max_read_size: 102400
  max_file_write_size: 1048576
```

Prioridad de configuracion:

1. Variables de entorno `CAWL_*`
2. `./.cawl/config.yaml` del proyecto
3. `~/.cawl/config.yaml`
4. `cawl/config/config.yaml`

## Arquitectura

```text
Usuario
  |
  v
Shell / CLI / UI
  |
  v
Planner -> Executor
  |
  v
Tool Registry
  |- read_file
  |- write_file
  |- list_files
  |- grep_search
  |- glob_files
  |- run_command
  |- search_web
```

## Estructura del proyecto

```text
cawl_agent/
|- cawl/
|  |- cli/
|  |  `- main.py
|  |- config/
|  |  |- config.py
|  |  `- config.yaml
|  |- core/
|  |  |- executor.py
|  |  |- llm_client.py
|  |  |- loop.py
|  |  |- multi_agent.py
|  |  |- ollama_models.py
|  |  |- planner.py
|  |  `- status.py
|  |- shell/
|  |  |- shell.py
|  |  |- completer.py
|  |  |- context.py
|  |  `- formatter.py
|  |- tools/
|  `- ui.py
|- tareas/
|- parametros/
`- README.md
```

## Seguridad

- `run_command` requiere confirmacion por defecto
- Hay timeout configurable para comandos
- El cache de herramientas esta aislado por proyecto activo
- Planner y executor reciben `project_path` y `model` explicitos

## Troubleshooting

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

## Roadmap

- [x] Shell interactiva unificada
- [x] Selector inicial de modelos locales
- [x] Cache aislado por proyecto
- [x] Planner y executor con contexto explicito
- [x] UI grafica
- [ ] Selector visual de modelo dentro de la UI
- [ ] Mejor render para bloques grandes y archivos
- [ ] Integracion mas profunda con Git
- [ ] Interfaz web opcional

## Licencia

MIT
