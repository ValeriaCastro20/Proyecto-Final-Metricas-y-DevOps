# ESC3-01…10 · Evidencia funcional de la parte A

Contrato y comandos: [docs/escenario.md](../../escenario.md).

## Carga completa en Azure/K3s · 2026-11-13

[Ejecución real y JSON íntegros versionados](azure-2026-11-13/README.md), contra
`eventos-development`, API y worker existentes con PostgreSQL persistente:

- **P3-1:** 1.000 válidos únicos.
- **P3-3:** 50 duplicados y 50 tardíos únicos adicionales; históricos, recibos,
  orden temporal, ventanas `[from,to)` y count/min/max/avg comprobados.
- **P3-2:** 2.400 únicos a 20/s durante **120.001 s**.
- Sin pérdida ni solicitudes inciertas; pendientes finales cero en los tres perfiles.

Se publican reportes originales, todos los recibos consultados, históricos y
agregados completos, hashes, UIDs y digests de los componentes antes/después.
Worker activo: no se detuvo ni se desplegó la aplicación para esta prueba.
No acredita production, P3-5 ni cierre de MET-07.

## Carga obligatoria completa publicada · P3-1, P3-3 y P3-2

La nueva [evidencia P3 versionada](p3/README.md) publica los JSON completos de los
tres perfiles, históricos antes/después, todos los recibos, consultas por ventana,
agregados y hashes verificables sin BD. Ya no depende de los ficheros locales
ignorados descritos en la sección histórica siguiente.

Incluye 1.000 válidos (P3-1), 50 duplicados + 50 tardíos con consultas y agregados
comprobados (P3-3), y 2.400 únicos a 20/s durante 120 s reales (P3-2). El workflow
`ESC3 compulsory P3 load` repite y publica íntegramente la carga en GitHub Actions;
véanse alcance, reproducción y verificaciones en la carpeta enlazada. No acredita
carga Azure/K3s ni cierra MET-07.

**Ejecución remota publicada:** [Actions 43360836707, aprobada](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/43360836707).
Sus JSON y logs íntegros se conservan en [`p3/`](p3/README.md), incluido el
manifiesto con commit y hashes; no dependen de la caducidad del artefacto remoto.

| Prueba | Únicos aceptados | Duplicados | Tardíos únicos incluidos | Emisión | Pérdida | Pendientes antes → después |
|---|---:|---:|---:|---:|---:|---:|
| P3-1 · burst | 1000 | 0 | 0 | 1.057 s | 0 | 1000 → 0 |
| P3-3 · extra | 1050 | 50 | 50 | 0.984 s (base de 1000) | 0 | 1050 → 0 |
| P3-2 · sustained | 2400 | 0 | 0 | 120.001 s, 20/s | 0 | 2400 → 0 |

Burst y extra añaden 20 rechazos cada uno. Consultas, agregados completos y
ventana semiabierta comprobados; latencias y retrasos exactos en los JSON.

## Histórico: ejecución local · 2026-11-08

Entorno: Linux, ejecutables Rust de debug, HTTP loopback y PostgreSQL 16 en un
contenedor exclusivo de pruebas. **No es una prueba de rendimiento en Azure/K3s.**
No había procesador durante los tres perfiles de carga; se drenó después, sin
nueva entrada. Datos y cuentas ficticios, seed 3.

| Perfil | 202 únicos | 200 duplicados | 422 rechazados | Duración de emisión de únicos | Pérdida de aceptados | Pendientes antes → después |
|---|---:|---:|---:|---:|---:|---:|
| burst | 1000 | 0 | 20 | 1.550 s | 0 | 1000 → 0 |
| extra | 1050 (incluye 50 tardíos) | 50 | 20 | 1.240 s | 0 | 1050 → 0 |
| sustained | 2400 | 0 | 0 | 120.001 s, objetivo 20/s | 0 | 2400 → 0 |

Latencia HTTP p50 / p95 / máxima, en ms:

- burst: 95.65 / 166.68 / 245.87;
- extra: 80.34 / 95.81 / 118.68;
- sustained: 10.82 / 14.91 / 319.87.

Los JSON íntegros se generaron en `artifacts/esc3-{burst,extra,sustained}-local.json`
y el resumen en `artifacts/esc3-local-results.json` (artefactos locales ignorados por
Git, no adjuntos remotos). Incluyen recibos, contadores, errores inciertos y pérdida
calculada comparando los UUID aceptados con el histórico persistido.

**Interpretación de los rechazos:** de los 20 inválidos de burst/extra, 5 usan un
dispositivo inexistente. Por eso el contador filtrado por el dispositivo registrado
muestra 15 rechazados; los otros 5 están en el ledger global/dispositivo inexistente.
El total de HTTP 422 sigue siendo 20. Ningún rechazo se suma a los válidos.

## Reinicio real de componentes

`cargo run --locked --example verify_system` ejecutado con base y puerto dedicados:

```text
PASS: 200 -> 503 -> 200 without restarting API
PASS: event persisted after API + PostgreSQL restart
PASS: ESC3 devices, limits, readings, rejection receipts, alerts and pending work
      survived API + PostgreSQL restart; backlog drained to zero
PASS: failure responses and API logs do not disclose submitted secrets or URL values
```

Se compararon respuestas completas antes/después para configuración del dispositivo,
históricos, agregados, alertas, recibos, rechazos y contadores. Se conservaron una
lectura procesada y una pendiente durante el reinicio, y luego se procesó la pendiente.

## Pruebas ejecutables

Resultado de la entrega inicial: **31 pruebas aprobadas** (20 sin DB y 11 PostgreSQL),
`cargo fmt --all -- --check`, Clippy con `-D warnings` y rustdoc con `-D warnings`
sin errores. Resultados detallados en `artifacts/esc3-unit-local.txt` y
`artifacts/esc3-postgres-local.txt`.

### Correcciones de CodeRabbit

Tras revisar las observaciones se aplicaron:

- pool único de hasta 10 conexiones compartido por API genérica, ESC3 y readiness;
- categoría pública segura de errores del worker, backoff exponencial acotado y
  reinicio del backoff tras éxito, conservando el fallo inmediato de `drain`;
- docstrings en contratos, handlers, almacenamiento, simulador y pruebas;
- pruebas de backoff/reset y de fallo conjunto de readiness/ESC3 al cerrar el pool.

Revalidación local: **34 pruebas aprobadas** (22 sin DB + 12 PostgreSQL), formato,
Clippy y rustdoc estrictos sin errores. Resultados en
`artifacts/esc3-review-unit-local.txt` y `artifacts/esc3-review-postgres-local.txt`.
El CI y la revisión humana deben corresponder al commit de estas correcciones, no
solo al verde de `beff889`.

- `tests/scenario_domain.rs`: campos, rangos físicos, límites, formato de IDs y UTC.
- `tests/scenario3/mod.rs` dentro del target `postgres`: 1,000 válidos, 50 duplicados,
  50 tardíos, retransmisiones concurrentes, rechazos y permisos; proceso worker real
  detenido con trabajo pendiente y reanudado sin nueva entrada; agregados y alertas.
- El target PostgreSQL existente ejecuta estas pruebas con `--ignored` en CI;
  no se modificó el workflow de C.

La carga y las comprobaciones locales no acreditan despliegue Kubernetes, aprobación
remota de esta revisión ni los requisitos MET de D. Al publicar el cambio, enlazar
los checks del commit correspondiente; no reutilizar el verde del PR #40 como
evidencia de esta implementación.
