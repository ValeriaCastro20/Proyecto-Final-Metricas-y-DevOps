# P3-1, P3-3 y P3-2 · ejecución real en Azure/K3s

Seguimiento: [#50](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/50).
Publicación en PR independiente [#105](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/pull/105).

## Destino y procedimiento

- VM `vm-eventos-b97e31-k3s`, **encendida**, confirmada por el [workflow de estado](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/43361832253).
- Acceso aplicado mediante [Terraform desde main, aprobado por un revisor](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/43361832125).
  No se eludió `azure-infra` ni se publican CIDRs administrativos.
- SSH con verificación estricta de huella: coincidió con la previamente contrastada
  por Azure en [DEV-13](../../DEV-13/index.md). Claves de API solo en memoria y tráfico
  por túnel SSH; nunca se enviaron por HTTP público ni se versionaron credenciales.
- Namespace **`eventos-development`**, nodo `k3s-eventos`, K3s `v1.35.2+k3s1`.
  No se probó production.
- API y worker existentes, digest observado en ambos:
  `sha256:17b4e6051228fd27df63471a3fff003bd8f2cb7ca916ef8e29d96a29835597e9`.
  PostgreSQL 16 con digest
  `sha256:5264710be20f409750ac6dc4e5706dcef929c87e241605463f0f9aefa932a8d9`.
- `deployment.json` conserva servidor UTC, namespace, Service, UID de nodo/Pods,
  imágenes efectivas, readiness y reinicios antes/después. No contiene Secrets,
  kubeconfig ni especificaciones completas con variables de entorno.

El cliente Rust se ejecutó en el equipo local, seed 3, contra el Service del clúster
mediante túnel SSH. **La API, el worker y los datos son del despliegue Azure**, no
de un PostgreSQL o API local. Las latencias incluyen cliente, red y túnel; no se
presentan como tiempos exclusivos de servidor ni como un benchmark SLO.

## Resultados

| Prueba | 202 únicos | 200 duplicados | 422 rechazados | Tardíos únicos incluidos | Emisión base | Pérdida / inciertos | Pendiente al acabar carga → final |
|---|---:|---:|---:|---:|---:|---:|---:|
| P3-1 · burst | 1000 | 0 | 20 | 0 | 1.997 s | 0 / 0 | 0 → 0 |
| P3-3 · extra | 1050 | 50 | 20 | 50 | 2.112 s (1000 base) | 0 / 0 | 0 → 0 |
| P3-2 · sustained | 2400 | 0 | 0 | 0 | **120.001 s, 20/s** | 0 / 0 | 0 → 0 |

Latencia HTTP p50 / p95 / máxima (ms):

- burst: 109.86 / 245.65 / 413.25;
- extra: 114.58 / 311.00 / 414.30;
- sustained: 189.06 / 252.47 / 358.68. Retraso máximo de programación: **2.74 ms**.

El worker estuvo **activo durante toda la carga**: ya había procesado todos los
aceptados al consultar el contador final del generador. No se detuvo, escaló,
reinició ni ejecutó drain en el clúster, y no se aplicaron migraciones ni despliegues
de aplicación. Esta ejecución no demuestra crecimiento/recuperación de backlog:
la prueba controlada sin worker está separada en [`../p3/`](../p3/README.md).

Los 20 rechazados de burst/extra no cuentan como válidos. Cinco de cada perfil
corresponden a dispositivo desconocido: no aparecen en el contador del dispositivo
registrado (15 rechazados), pero sí en los recibos rechazados completos.

## Evidencia completa y comprobaciones

- `*-load.json`: JSON íntegros emitidos por los tres perfiles Rust, con IDs de
  recibos, códigos HTTP, tiempos, latencias, incertidumbre, pérdida y contadores.
- `*-queries.json`: todos los históricos paginados, todos los recibos consultados,
  estadísticas y contadores estables, más ventana semiabierta `[00:00:00,00:00:50)`.
- `summary.json`: aceptación de los tres perfiles; `manifest.json`: hashes y
  procedencia; `deployment.json`: destino real y estado de los componentes.

El verificador reconstruye las mediciones deterministas desde seed 3 y contrasta
cada evento y UUID aceptado con el histórico. Comprueba deduplicación y referencias
originales, llegada tardía efectiva en orden temporal inverso, orden de consultas
entre páginas, count/min/max/avg exactos sin distorsión por duplicados y semántica
`[from,to)`. Verifica además identidad del dispositivo de recibos y conservación de
contadores. Los snapshots con `processing_mode: live-worker` se toman ya estables,
sin afirmar que el procesador estuvo detenido.

La consulta secuencial de recibos resultó lenta por la red. Tras emitir **los tres
perfiles una sola vez**, se detuvo exclusivamente el recolector local durante las
lecturas de sustained y se completó esa fase mediante
`scripts/esc3-resume-reads.py`, con ocho GET concurrentes. Se conservaron los reportes
de emisión y las consultas completas de burst/extra, sin repetir POST, crear nueva
carga ni modificar API/worker. `collection_resumed` lo deja explícito en el manifiesto.
Sus fechas `started_utc`/`finished_utc` corresponden a esa recolección final; las
fechas de los recibos/lecturas y los límites servidor UTC en `deployment.json`
conservan la cronología de la ejecución completa.

Verificación offline desde la raíz, sin BD, Azure ni credenciales:

```bash
python3 scripts/esc3-evidence.py --verify docs/evidencia/ESC3/azure-2026-11-13
python3 -m unittest discover -s scripts/tests -p test_esc3_evidence.py -v
```

Para una nueva ejecución, configurar un túnel autorizado al Service de development,
exportar las claves sin imprimirlas y seguir la [modalidad external](../p3/README.md#repetición-contra-el-despliegue-existente).
Si ya existen los tres `*-load.json` completos y falta solo la lectura de evidencia,
usar `python3 scripts/esc3-resume-reads.py <directorio>` con `ESC3_BASE_URL` loopback
y `EVENT_ANALYST_KEY`: ese comando solo hace GET, no reemite perfiles ni migra/drena.

Esta evidencia acredita la carga P3-1/P3-2/P3-3 en development de Azure/K3s.
**No acredita production, P3-5, MET-07, SLOs, HA ni la defensa global.**
