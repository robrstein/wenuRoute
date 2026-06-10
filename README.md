# wenuRoute

**WenuRoute** es una herramienta multiplataforma de análisis de código que actúa como guía visual para desarrolladores, mostrando las rutas de ejecución de un proyecto como un grafo interactivo navegable.

## Características

- 🔍 **Analiza proyectos** HTML, React/JSX/TypeScript, Python (Flask, FastAPI, Django), Node.js/Express, Flutter/Dart y Android (Java/Kotlin).
- 🔗 **Sigue cadenas de llamadas**: CSS → JS → endpoint → SQL.
- 📊 **Genera un grafo HTML interactivo** con PyVis (nodos coloreados por tipo, panel de detalle lateral, filtros por capa y tipo).
- 🖥️ **Salida en consola** con `--format text` para entornos sin navegador.
- ⚡ **Arquitectura modular**: un parser por lenguaje, fácil de extender.

## Instalación

```bash
pip install -e .
# o desde PyPI cuando esté publicado:
# pip install wenuroute
```

### Requisitos

- Python 3.9+
- Dependencias instaladas automáticamente: `pyvis`, `beautifulsoup4`, `click`, `networkx`, `lxml`, `rich`.

## Uso

```bash
# Analizar el directorio actual y generar wenuroute_graph.html
wenuroute

# Analizar un proyecto específico
wenuroute ./mi-proyecto

# Guardar en un archivo personalizado
wenuroute ./mi-proyecto -o reporte.html

# Ver resumen en consola (sin abrir navegador)
wenuroute ./mi-proyecto --format text

# Modo verbose (muestra cada archivo procesado)
wenuroute ./mi-proyecto --verbose
```

Abre el archivo HTML generado en cualquier navegador para explorar el grafo:

| Acción | Resultado |
|---|---|
| **Click** en un nodo | Abre el panel de detalle lateral (nombre, tipo, archivo, línea, parámetros, conexiones) |
| **Click** en espacio vacío | Cierra el panel de detalle |
| **Doble click** en un cluster | Expande el cluster mostrando sus nodos |
| **Click derecho** en un nodo | Menú contextual: ver vecinos, ampliar foco, expandir cluster |
| **Click** en nodo dentro del panel | Navega a ese nodo y muestra su detalle |

## Interfaz del grafo (proyectos grandes)

El grafo generado incluye una barra lateral izquierda con herramientas diseñadas para proyectos grandes:

| Función | Descripción |
|---|---|
| 🔍 **Búsqueda** | Filtra nodos por nombre o archivo; resalta y hace zoom a los resultados |
| 🌐 **Filtros por capa** | Botones para mostrar/ocultar Frontend, Backend, Mobile |
| ✅ **Filtros por tipo** | Checkboxes para mostrar/ocultar cada tipo de nodo (Endpoint, SQL, Function…) |
| 📁 **Clustering por módulo** | Agrupa todos los nodos de un mismo archivo en un nodo-cluster colapsable. Un proyecto de 50 archivos muestra 50 clusters en lugar de 500 nodos. Doble clic para expandir |
| 🎯 **Modo foco** | Click derecho → "Ver vecinos" → oculta todo excepto el nodo y sus conexiones directas. Ideal para trazar endpoint → función → SQL |
| 📋 **Panel de detalle** | Click en cualquier nodo abre un panel lateral fijo con: nombre, tipo, archivo, línea, parámetros, lista de nodos entrantes y salientes (clickeables) |
| 🗺 **Minimapa** | Overlay fijo en esquina inferior derecha: vista completa del grafo con rectángulo de viewport. Click en el minimapa para navegar. Se actualiza con zoom, drag y filtros |
| ⏸ **Control de física** | La simulación se detiene automáticamente tras la estabilización. Botón para reactivar o pausar |

### Clusters (agrupación por módulo)

Los clusters se muestran como nodos cuadrados con borde punteado; el color del borde indica la capa del proyecto:

| Color | Capa |
|---|---|
| 🔵 Azul | Frontend |
| �� Verde | Backend |
| 🟣 Morado | Mobile |
| ⚫ Gris | Otro |

## Tipos de nodos

| Color | Tipo | Qué representa |
|---|---|---|
| 🟢 Verde | UI Element | Botón, enlace, formulario, widget |
| 🔵 Azul | Function | Función o método |
| 🟠 Naranja | Endpoint | Ruta HTTP / navegación |
| 🔴 Rojo | SQL | Consulta SQL o llamada ORM |
| 🟣 Morado | Style | Hoja de estilos CSS |
| 🩵 Cian | Event | Evento DOM / gesto / intent |
| 🔷 Gris | Module | Archivo / módulo |

## Lenguajes soportados

| Lenguaje | Extensiones | Detecta |
|---|---|---|
| HTML | `.html`, `.htm` | Botones, formularios, enlaces, handlers, CSS links |
| React / JS / TS | `.js`, `.jsx`, `.ts`, `.tsx` | Componentes, fetch, axios, React Router, JSX events |
| Python | `.py` | Flask/FastAPI/Django routes, funciones, SQL/ORM |
| Node.js / Express | `.js`, `.mjs`, `.cjs` | Express routes, funciones, Knex/Mongoose, SQL |
| Flutter / Dart | `.dart` | Widgets, onPressed/onTap, Navigator, http/dio |
| Android (Java/Kt) | `.java`, `.kt` | Activities, onClick, Intent, Retrofit, Room SQL |

## Estructura del proyecto

```
wenuroute/
├── wenuroute/
│   ├── cli.py          # Punto de entrada CLI (Click)
│   ├── analyzer.py     # Orquestador: recorre el árbol de archivos
│   ├── graph.py        # Renderizado HTML (PyVis) y texto
│   ├── models.py       # RouteNode, RouteEdge, RouteGraph
│   └── parsers/
│       ├── base.py     # Clase abstracta BaseParser
│       ├── html.py
│       ├── react.py
│       ├── python.py
│       ├── nodejs.py
│       ├── flutter.py
│       └── android.py
└── tests/
    └── test_parsers.py
```

## Desarrollo

```bash
pip install -e .
python -m pytest tests/ -v

# Ejecutar un solo test
python -m pytest tests/test_parsers.py::TestPythonParser::test_detects_flask_route -v
```

## Licencia

GPL v3 (GNU General Public License v3.0)

Este programa es software libre: puedes redistribuirlo y/o modificarlo bajo los términos de la Licencia Pública General de GNU publicada por la Free Software Foundation, ya sea la versión 3 de la Licencia, o (a tu elección) cualquier versión posterior.

Ver el archivo [LICENSE](LICENSE) para más detalles.

## Screenshots


![Screenshot](https://raw.githubusercontent.com/robrstein/wenuRoute/refs/heads/main/screenshot/wenuroute_Screenshot_2.jpg)


![Screenshot](https://raw.githubusercontent.com/robrstein/wenuRoute/refs/heads/main/screenshot/wenuroute_Screenshot_3.jpg)

![Screenshot](https://raw.githubusercontent.com/robrstein/wenuRoute/refs/heads/main/screenshot/wenuroute_Screenshot_4.jpg)

![Screenshot](https://raw.githubusercontent.com/robrstein/wenuRoute/refs/heads/main/screenshot/wenuroute_Screenshot_5.jpg)