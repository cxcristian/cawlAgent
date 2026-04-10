# 🤖 CAWL — Agente Local Inteligente

**CAWL** (Control & Action Web Loop) es un sistema de agente autónomo que ejecuta tareas complejas en tu máquina local usando modelos de lenguaje abiertos vía **Ollama** (Qwen, Llama, Mistral, etc.).

> **v0.3.0** — Sin API keys. Sin costos. Tu código nunca sale de tu máquina.

---

## ✨ Características

| Feature | Descripción |
|---|---|
| 🧠 **Planner → Executor** | Las tareas se descomponen automáticamente en pasos ejecutables |
| 🤖 **Multi-Agente** | Orquestador + Workers especializados, secuencial o en paralelo |
| 💾 **Memoria por Proyecto** | Cada proyecto tiene su `.cawl/memory.json` aislado |
| ⚡ **Status en Tiempo Real** | Spinner animado en terminal y burbuja de progreso en UI |
| 🔄 **Retry Automático** | Re-prompt al modelo si devuelve JSON inválido (hasta 2 intentos) |
| ⏱️ **Timeout en Comandos** | `run_command` se mata automáticamente después de 60s |
| 🌐 **Búsqueda Web** | Herramienta `search_web` vía DuckDuckGo, sin API key |
| 👁️ **Modo Watch** | Re-ejecuta una tarea automáticamente cada vez que guardas el `.md` |
| 🖥️ **GUI incluida** | Chat con tema oscuro, árbol de archivos y progreso en tiempo real |
| 🔒 **Confirmación de seguridad** | Confirmación antes de ejecutar comandos de shell |

---

## 🏗️ Arquitectura

```
Usuario
  │
  ▼
┌─────────────────────────────────────────┐
│            CawlAgent / REPL             │  ← terminal o GUI
│   chat_with_tools_loop()                │
│   _trim_history() (max 12k chars)       │
└──────────────┬──────────────────────────┘
               │
       ┌───────▼───────┐
       │  StatusEmitter │  ← pub/sub thread-safe
       │  (status.py)   │     spinner terminal
       └───────┬────────┘     burbuja UI
               │
    ┌──────────▼──────────┐
    │   Planner → Executor │  ← loop.py
    │   plan → steps       │
    └──────────┬───────────┘
               │
    ┌──────────▼──────────┐
    │   Tool Registry      │
    │   read_file          │
    │   write_file         │
    │   list_files         │
    │   grep_search        │
    │   glob_files         │
    │   run_command        │
    │   search_web         │
    └─────────────────────┘

Multi-Agente:
  OrchestratorAgent
    ├── descompone tarea con LLM
    ├── WorkerAgent [coder]
    ├── WorkerAgent [reviewer]     ← secuencial o paralelo
    └── WorkerAgent [documenter]
          └── consolida resultados
```

---

## 🚀 Instalación

**Requisitos:** Python 3.10+, [Ollama](https://ollama.ai) instalado y corriendo.

```bash
git clone <repo>
cd cawl_agent
pip install -e .
ollama pull qwen2.5-coder:7b
cawl status
```

Debería mostrar:
```
Ollama: Connected
Model: qwen2.5-coder:7b
Available: Yes
```

### Error: `cawl: command not found`

El directorio `Scripts` de Python no está en el PATH. Agrégalo:

```bash
# Encuentra la ruta
python -c "import sys, os; print(os.path.join(sys.prefix, 'Scripts'))"

# Agrégala al PATH del sistema (Windows):
# Win+R → sysdm.cpl → Opciones avanzadas → Variables de entorno → Path → Nuevo
```

---

## ⚙️ Configuración

`cawl/config/config.yaml`:

```yaml
executor:
  model: "qwen2.5-coder:7b"
  confirm_commands: true      # pedir confirmación antes de run_command

planner:
  model: "qwen2.5-coder:7b"

paths:
  base: "."
  memory: ".cawl"
```

---

## 📖 Comandos

### REPL interactivo (modo por defecto)

```bash
cawl run
```

Entra en modo chat con herramientas. Spinner animado mientras el agente trabaja.

```
cawl> listar los archivos en src/
⣷ ►  read_file(...)
cawl> buscar todos los TODO en el código
```

Comandos internos del REPL:

| Comando | Acción |
|---|---|
| `/help` | Mostrar ayuda |
| `/status` | Verificar conexión a Ollama |
| `/tools` | Listar herramientas disponibles |
| `/clear` | Limpiar historial de chat |
| `/quit` | Salir |

### Ejecutar una tarea desde archivo `.md`

```bash
cawl run --task tareas/mi_tarea.md [--project /ruta] [--model modelo]
```

### Ver el plan sin ejecutar

```bash
cawl plan --task tareas/mi_tarea.md
```

### Comando único (sin REPL)

```bash
cawl run -c "crear un archivo resultado.txt con la lista de .py en src/"
```

### Modo Watch — re-ejecuta al guardar

```bash
cawl watch --task tareas/mi_tarea.md [--interval 2]
```

Detecta cambios en el archivo `.md` cada `N` segundos y re-ejecuta automáticamente. Útil para iterar en tareas rápidamente. `Ctrl+C` para detener.

### Multi-Agente

```bash
# Un solo worker genérico
cawl multi -c "Analiza el proyecto y genera un README actualizado"

# Con roles especializados (secuencial, respetando dependencias)
cawl multi -c "Refactoriza auth.py, escribe tests y documenta" \
  --workers coder,reviewer,documenter

# En paralelo (sub-tareas independientes corren en threads)
cawl multi -c "Analiza src/ y genera docs simultáneamente" \
  --workers analyst,documenter --parallel
```

El orquestador descompone la tarea, asigna sub-tareas al worker más apropiado según el rol, y consolida los resultados en una respuesta final.

### GUI

```bash
cawl ui [--project /ruta] [--model modelo]
```

Interfaz con tema oscuro, árbol de archivos y burbuja de status animada que muestra qué herramienta se está ejecutando en tiempo real.

### Otros

```bash
cawl init [--project /ruta]   # Inicializar .cawl/ en un proyecto
cawl pull                      # Descargar el modelo configurado
cawl status                    # Verificar conexión a Ollama
```

---

## 🔧 Herramientas Disponibles

El LLM elige y ejecuta estas herramientas automáticamente:

| Herramienta | Firma | Descripción |
|---|---|---|
| `read_file` | `(path, offset?, limit?)` | Lee un archivo. Soporta rangos de líneas. |
| `write_file` | `(path, content, mode?)` | Escribe archivo. `mode='append'` para añadir. |
| `list_files` | `(path, max_depth?, show_hidden?)` | Lista directorio. |
| `grep_search` | `(pattern, path?, glob?, limit?)` | Busca regex en archivos. |
| `glob_files` | `(pattern, path?)` | Encuentra archivos por patrón glob. |
| `run_command` | `(command, timeout?)` | Ejecuta shell. Timeout 60s por defecto. |
| `search_web` | `(query, max_results?)` | Busca en DuckDuckGo. Sin API key. |

---

## 💾 Estructura del Proyecto

```
cawl_agent/
├── cawl/
│   ├── cli/
│   │   └── main.py              # CLI, REPL, TerminalSpinner, cmd_multi
│   ├── config/
│   │   ├── config.py
│   │   └── config.yaml
│   ├── core/
│   │   ├── executor.py          # Ejecuta pasos individuales con retry JSON
│   │   ├── llm_client.py        # Cliente Ollama (chat, generate, tool parsing)
│   │   ├── loop.py              # Bucle principal plan→execute
│   │   ├── multi_agent.py       # OrchestratorAgent + WorkerAgent
│   │   ├── planner.py           # Descompone tareas con retry JSON
│   │   └── status.py            # StatusEmitter pub/sub (spinner + UI bubble)
│   ├── memory/
│   │   ├── global_memory.py
│   │   └── project_memory.py    # Memoria aislada por proyecto
│   ├── tasks/
│   │   └── parser.py
│   ├── tools/
│   │   ├── file_tools.py        # read_file, write_file, list_files, grep, glob
│   │   ├── registry.py          # Registro central de herramientas
│   │   ├── system_tools.py      # run_command con timeout
│   │   └── web_tools.py         # search_web (DuckDuckGo)
│   └── ui.py                    # GUI PyQt5 con StatusBubble animada
├── tasks/                        # Carpeta sugerida para archivos .md de tareas
├── setup.py
└── README.md
```

---

## 🤖 Sistema Multi-Agente — Detalles

### Cómo funciona

```
OrchestratorAgent.run("tarea grande")
  │
  ├── 1. LLM descompone en sub-tareas con roles asignados
  │       [{"id":1, "subtask":"...", "role":"coder", "depends_on":[]}]
  │
  ├── 2a. Secuencial: ejecuta respetando depends_on (orden topológico)
  │   2b. Paralelo:   lanza threads para sub-tareas sin dependencias
  │
  └── 3. LLM consolida todos los resultados → respuesta final
```

### Uso desde código Python

```python
from cawl.core.multi_agent import OrchestratorAgent, WorkerAgent

# Con workers personalizados
workers = [
    WorkerAgent(
        role="coder",
        instructions="Escribe solo código Python limpio y tipado.",
        tools=["read_file", "write_file", "grep_search"],
    ),
    WorkerAgent(
        role="reviewer",
        instructions="Revisa código y reporta bugs y mejoras de forma concisa.",
        tools=["read_file", "grep_search"],
    ),
    WorkerAgent(
        role="documenter",
        instructions="Escribe documentación Markdown clara y técnica.",
        tools=["read_file", "write_file", "list_files"],
    ),
]

orchestrator = OrchestratorAgent(
    model="qwen2.5-coder:7b",
    workers=workers,
    project_path="/ruta/a/tu/proyecto",
    parallel=False,  # True para ejecutar en paralelo
)

result = orchestrator.run(
    "Refactoriza el módulo de autenticación, "
    "escribe tests unitarios y actualiza el README."
)
print(result)
```

---

## ⚡ Status en Tiempo Real

Todos los eventos internos del agente se emiten a través de `StatusEmitter`:

```python
from cawl.core.status import status

# Suscribirse a eventos (útil para integrar CAWL en tu propia UI)
def mi_callback(event_type: str, message: str):
    print(f"[{event_type}] {message}")

status.subscribe(mi_callback)
# ... ejecutar agente ...
status.unsubscribe(mi_callback)
```

Tipos de eventos: `thinking`, `planning`, `tool_call`, `tool_result`, `step`, `retry`, `trim`, `done`, `error`, `agent`.

**Terminal:** spinner Braille animado con icono por tipo de evento.
**GUI:** burbuja animada con puntos `...` que aparece al enviar y desaparece al recibir respuesta.

---

## 🧠 Memoria y Contexto

- Cada ejecución se guarda en `.cawl/memory.json` del proyecto.
- El planner recibe los últimos 5 runs como contexto para no repetir trabajo.
- El historial de chat del REPL se comprime automáticamente cuando supera ~12.000 caracteres (conservando siempre los 4 turnos más recientes).
- Máximo 20 runs almacenados por proyecto.

```bash
cat .cawl/memory.json   # ver historial del proyecto actual
```

---

## 🛡️ Seguridad

- `confirm_commands: true` (por defecto): el agente te pide confirmación antes de ejecutar cualquier comando de shell. Puedes responder `y`, `a` (siempre para esta sesión) o `n`.
- `run_command` tiene un timeout de 60 segundos. Procesos colgados son terminados automáticamente.
- Las herramientas disponibles para cada `WorkerAgent` en multi-agente pueden restringirse con `tools=[...]`.

---

## 🔗 Flujo híbrido con Claude / GPT-4

CAWL está diseñado para ser el **ejecutor local** de planes generados por IAs superiores:

1. **En Claude**: *"Crea un plan detallado en Markdown para [TAREA] con pasos específicos y verificables."*
2. **Guarda el resultado** en `tareas/mi_tarea.md`
3. **CAWL ejecuta**: `cawl run --task tareas/mi_tarea.md`

La IA maestra diseña la estrategia. CAWL ejecuta localmente sin consumir tokens adicionales.

---

## 🐛 Troubleshooting

**`Connection refused` a Ollama**
```bash
ollama serve          # en una terminal
cawl status           # en otra terminal
```

**`Model not found`**
```bash
cawl pull             # descarga el modelo configurado
# o manualmente:
ollama pull qwen2.5-coder:7b
```

**El agente devuelve texto en lugar de JSON**
Ya está manejado automáticamente: CAWL reintenta hasta 2 veces inyectando el error de parseo de vuelta al modelo para que se autocorrija.

**`run_command` se corta a los 60 segundos**
Aumenta el timeout pasándolo explícitamente o en la tarea: *"ejecuta X con timeout de 120 segundos"*.

**Historial muy largo / respuestas lentas**
El REPL comprime automáticamente el historial. También puedes limpiarlo manualmente con `/clear`.

---

## 🎓 Roadmap

- [x] Arquitectura Planner → Executor
- [x] Memoria persistente por proyecto
- [x] Retry automático en JSON inválido
- [x] Timeout en `run_command`
- [x] Status en tiempo real (terminal + UI)
- [x] Compresión automática del historial
- [x] `search_web` sin API key
- [x] Modo `watch` (re-run al guardar)
- [x] Sistema multi-agente (Orchestrator + Workers)
- [ ] Plugin system para herramientas custom
- [ ] Interfaz web (alternativa a PyQt5)
- [ ] Integración con Git (auto-commit de artefactos generados)
- [ ] Soporte streaming (respuestas token a token en terminal)

---

## 📄 Licencia

MIT — úsalo libremente.
