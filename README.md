# GUERRA — Prueba Técnica UTL Senado 2026

## Candidato

Nombre: Cristian Andres Guerra Cotes

Email: christianandresguerra@gmail.com

Repositorio: git@github.com:Heyparalebola/guerra_cotes_prueba_utl_2026.git

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

El proyecto usa SQLite y archivos locales. El dashboard no necesita servidor.

La base pesa más de 50 MB y no se publica directamente en Git. Debe descargarse desde el Release del repositorio y guardarse como `db/puestos_2026.db`:

```text
URL DEL RELEASE: https://github.com/Heyparalebola/guerra_cotes_prueba_utl_2026/releases
```

También puede reconstruirse ejecutando el scraper.

## Pipeline de ejecución

Desde la raíz del repositorio:

```bash
python scraper/scraper.py --preflight
python scraper/scraper.py
python db/etl.py
python dashboard/export_data.py
python viz/heatmap.py
python viz/scatter.py
python outputs/generar_manifest.py
```

### ¿Qué hace cada comando?

1. `python scraper/scraper.py --preflight`: revisa que los municipios, puestos y mesas estén disponibles. No descarga resultados ni modifica la base de datos.
2. `python scraper/scraper.py`: descarga los resultados oficiales de Cámara y Senado y los guarda en `db/puestos_2026.db`.
3. `python db/etl.py`: ejecuta la limpieza y validación de la base de datos, y muestra un resumen de los registros cargados.
4. `python dashboard/export_data.py`: prepara los datos que necesita el dashboard y actualiza `dashboard/data.json` y `dashboard/index.html`.
5. `python viz/heatmap.py`: genera el mapa de calor de los resultados electorales.
6. `python viz/scatter.py`: genera el gráfico de dispersión para comparar los resultados de Cámara y Senado.
7. `python outputs/generar_manifest.py`: verifica las salidas principales del proyecto y crea `outputs/evaluation_manifest.json`.

En resumen: primero se revisa la disponibilidad, luego se descargan y validan los datos, después se actualizan el dashboard y los gráficos, y al final se verifica que los archivos generados estén completos.

El scraper procesa TUNJA, PAIPA, SOGAMOSO y DUITAMA por defecto. Para limitar la descarga:

```bash
python scraper/scraper.py --municipios TUNJA PAIPA
```

También acepta cualquier municipio de Boyacá usando su nombre oficial. Los espacios pueden escribirse con guion bajo:

```bash
python scraper/scraper.py --preflight --municipios CHIQUINQUIRA VILLA_DE_LEIVA
```

La descarga usa 12 conexiones simultáneas por defecto. Puede ajustarse con `--workers`.

Una segunda ejecución es idempotente: la base usa un índice único y `INSERT OR IGNORE`, por lo que las filas existentes se reportan como omitidas.

## API

Fuente: `https://resultadospreccongreso2026.registraduria.gov.co`.

Archivos utilizados:

- `/json/nomenclator.json`: departamentos, municipios, zonas, puestos y cantidad de mesas.
- `/json/ACT/CA/{codigo_puesto}{mesa:06d}.json`: resultados de Cámara por mesa.
- `/json/ACT/SE/{codigo_puesto}{mesa:06d}.json`: resultados de Senado por mesa.
- `/json/web/config.json`: configuración pública del sitio.
- El catálogo `partidos` de `/json/nomenclator.json` relaciona el índice `i` usado por `codpar` con nombre, color y sigla.

Campos revisados en los JSON: `ver`, `amb`, `ambitos`, `i`, `n`, `c`, `s`, `l`, `m`, `h`, `p`, `r`, `codpar`, `nombre` y `votos`.

Las solicitudes usan `Accept: application/json`, un `User-Agent` identificable y `Referer` del sitio público. Hay tres intentos con espera incremental antes de registrar un error. Si la API no responde, el parser busca un archivo compatible en `sample_data/`.

El nivel más bajo almacenado en el nomenclátor es el puesto (`l=6`) y el campo `m` indica cuántas mesas contiene. La aplicación pública construye cada mesa como un ámbito virtual de 19 dígitos: 13 del puesto y 6 del número de mesa. Con ese código se consultan directamente los archivos `ACT` individuales.

Los JSON incluyen una fila total por partido y el detalle de candidatos. Las consultas de totales filtran `candidate_id IS NULL` para evitar contar los mismos votos dos veces.

El registro con código de candidato `0` corresponde a “SOLO POR LA LISTA”. Se conserva en la base, pero se excluye de rankings y consultas que solicitan candidatos individuales.

## Municipios en la BD

| Municipio | Código | Puestos | Mesas esperadas | Votos CA |
|---|---:|---:|---:|---:|
| TUNJA | 0700001 | 26 | 424 | 73.845 |
| PAIPA | 0700181 | 7 | 95 | 16.907 |
| SOGAMOSO | 0700277 | 18 | 301 | 51.445 |
| DUITAMA | 0700079 | 22 | 287 | 48.690 |

La base contiene 1.607.364 filas de resultados, 1.107 mesas, 73 puestos, 83 partidos y 1.361 candidatos.

## Hallazgos principales

Pacto Histórico lidera Senado en Tunja, Sogamoso y Duitama. Alianza Verde lidera en Paipa.

El arrastre Verde no es uniforme. En varios puestos de Duitama y Sogamoso el ratio SE/CA supera 1, mientras Paipa presenta ratios menores a 1 en todos sus puestos.

El top CA no tiene que coincidir con el top por atribución SE. La fórmula pondera la participación del candidato dentro de su partido por los votos que ese partido obtuvo en Senado; por eso el desempeño de la lista cambia el orden individual.

## Bonus implementados

- `--preflight` con disponibilidad y conteo previo.
- Cinco índices SQLite para municipio, corporación, partido, puesto y candidato.
- Explicación de la diferencia entre top CA y atribución SE.
- Modo oscuro en el dashboard.
- Exportación CSV con los filtros activos.
- Filtros por departamento, municipio, partido, candidato, cantidad y ratio.
- Resolución automática de municipios adicionales de Boyacá desde el nomenclátor.
