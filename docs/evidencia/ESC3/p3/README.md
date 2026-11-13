# Carga obligatoria P3 · evidencia completa

Seguimiento único: [ESC3-10, #50](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/50).

**Ejecución publicada:** [GitHub Actions 43360836707, intento 1](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/43360836707),
2026-11-13 UTC, job `compulsory-load` aprobado. Todos los JSON y logs de esta
carpeta proceden de ese artefacto remoto (`esc3-p3-43360836707-1`), descargado y
verificado offline antes de versionarlo. El manifiesto enlaza la ejecución y su
commit de prueba (merge de GitHub del PR #105), no un despliegue en Azure.

## Qué se publica

Esta carpeta conserva en Git **los JSON completos**, no solo una tabla ni rutas a
`artifacts/` ignorados. Se usan datos ficticios y seed 3. El manifiesto registra el
commit del código Rust ejecutado, fechas UTC, entorno, versión de Rust y SHA-256
de cada fichero. La API es un proceso real separado de `drain`, con PostgreSQL 16.
No hay worker durante la emisión: se acredita acumulación y posterior drenaje sin
nueva entrada. No se impone un plazo de procesamiento.

| Requisito | Perfil | Mínimo comprobado |
|---|---|---|
| P3-1 | `burst` | 1.000 únicos válidos; 20 rechazos adicionales no cuentan como válidos |
| P3-3 | `extra` | 1.000 + 50 tardíos únicos; 50 retransmisiones sin nuevas filas ni distorsión de agregados |
| P3-2 | `sustained` | 2.400 únicos, 20/s, ventana real de emisión de 120 s |

- `*-load.json`: salidas íntegras de `scenario_load`, recibos, aceptación/rechazo,
  latencias, retraso de programación, duración, pendientes, pérdida e incertidumbre.
- `*-queries.json`: respuestas completas de históricos paginados y estadísticas
  antes/después del drenaje, contadores por dispositivo, todos los recibos consultados
  y consulta adicional de ventana `[00:00:00,00:00:50)` con sus agregados.
- `summary.json`: resultado de las comprobaciones, no sustituye los datos originales.
- `manifest.json` y `*.log`: procedencia, hashes y logs de migración/API/drenaje.

El verificador reconstruye cada evento desde seed 3 y el algoritmo determinista del
generador, contrasta UUID aceptados con histórico completo, contenido sin sobrescritura,
orden temporal entre páginas, llegada efectivamente tardía y en orden inverso,
referencias de duplicados a sus originales, count/min/max/avg y semántica `[from,to)`.
Comprueba backlog antes/después y contadores conservativos. Los 5 rechazos de cada
burst/extra por dispositivo desconocido no entran en el contador del dispositivo
registrado, pero sus recibos rechazados sí se conservan y verifican.

## Verificación sin BD ni credenciales

Desde la raíz, con Python 3.10 o posterior:

```bash
python3 scripts/esc3-evidence.py --verify docs/evidencia/ESC3/p3
python3 -m unittest discover -s scripts/tests -p test_esc3_evidence.py -v
```

Falla si faltan ficheros, cambian hashes, faltan lecturas/recibos, se alteran
agregados, se incluyen duplicados, se rompe el orden o se reduce la carga sostenida.
Los tests negativos mutan expresamente los resultados publicados.
Los hashes detectan cambios, no son una firma criptográfica de un tercero.

## Repetición completa y publicación remota

El workflow [ESC3 compulsory P3 load](../../../../.github/workflows/esc3-load.yml)
ejecuta **los tres perfiles**, incluido sustained durante 120 s, en un runner de
GitHub con PostgreSQL 16. Publica siempre los resultados disponibles como artefacto
`esc3-p3-<run_id>-<attempt>` durante 90 días, también ante fallos. Tras esa retención,
esta carpeta versionada sigue disponible y permite verificación offline.
Puede repetirse mediante `workflow_dispatch` tras integrar el workflow, o en PR
que modifique estos archivos. No usa secretos cloud ni despliega infraestructura.

Para repetir localmente: usar una BD dedicada cuyo nombre empiece por `test_` o
termine en `_test`, accesible por loopback y **sin otros workers**; exportar
`DATABASE_URL`, `EVENT_PRODUCER_KEY` y `EVENT_ANALYST_KEY` como en el README.

```bash
cargo build --locked --bin event-service --example scenario_load
# Directorio nuevo: nunca sobrescribir una ejecución anterior.
python3 scripts/esc3-evidence.py artifacts/esc3-p3-nueva
python3 scripts/esc3-evidence.py --verify artifacts/esc3-p3-nueva
```

El runner aplica migraciones, arranca su propia API en `127.0.0.1:18083`, ejecuta
perfiles y drenajes separados y termina exclusivamente su proceso API. Se puede
cambiar `BIND_ADDR` por otro puerto loopback libre. No detiene BD ni borra datos.
Una migración fallida por BD no disponible termina la ejecución: esperar primero
a que PostgreSQL esté listo; no se registra como aceptación ni se reintenta una
escritura de resultado incierto.

### Repetición contra el despliegue existente

Con un túnel SSH autorizado hacia la API de `eventos-development` y las claves
producer/analyst exportadas **sin imprimirlas ni versionarlas**:

```bash
export ESC3_BASE_URL=http://127.0.0.1:18084
python3 scripts/esc3-evidence.py --external artifacts/esc3-p3-azure-nueva
python3 scripts/esc3-evidence.py --verify artifacts/esc3-p3-azure-nueva
```

`--external` no migra, no ejecuta drain, no arranca API y no escala ni detiene el
worker existente. Solo crea dispositivos ficticios nuevos, emite los tres perfiles
y consulta sus resultados (hasta ocho GET de recibos concurrentes; no cambia la
cadencia de emisión POST). Registra `processing_mode: live-worker`; espera backlog
cero para tomar dos snapshots estables con históricos/agregados. El pendiente
inicial publicado es el medido por el generador justo al acabar la carga, no el
del snapshot posterior ya estabilizado. El límite de observación de 180 s por perfil
es un guard operativo del runner, no un requisito P3 ni un SLO de procesamiento.
Si vence, la evidencia queda incompleta y no se declara aceptación.

La procedencia Azure debe acompañarse de evidencia del destino del túnel,
namespace, estado e imágenes de API/worker; `--external` por sí solo no certifica
que el destino sea Azure. Esta modalidad aún no acredita una ejecución del clúster.

## Alcance

La ejecución de esta carpeta y enlazada de Actions acredita carga
en un runner remoto, **no Azure/K3s, SLIs/SLOs, P3-5 ni la defensa integrada**.
Después se realizó una [ejecución Azure/K3s separada](../azure-2026-11-13/README.md),
tras aplicar los accesos autorizados y verificar la VM encendida. No se mezclan
sus resultados con los de este runner. El incidente P3-5 sigue separado en #27.
