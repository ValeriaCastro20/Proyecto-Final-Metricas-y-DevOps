# DEV-11 · Salud y recursos de los workloads

[Issue #17](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/17).

## Probes

| Workload | Startup | Readiness | Liveness | Qué significa |
|---|---|---|---|---|
| API | `/health/live` | `/health/ready`, consulta la base | `/health/live` | Sin base deja de recibir tráfico, pero no se reinicia |
| Worker | `worker-health live` | `worker-health ready` | `worker-health live` | Ver abajo |
| PostgreSQL | `pg_isready` | `pg_isready` | `pg_isready`, 6 fallas | Da margen a recuperaciones lentas |
| Job de migración | No aplica | No aplica | No aplica | Proceso finito, `activeDeadlineSeconds` y sin reintentos |

El worker no tiene HTTP y la imagen no tiene shell, así que usa un subcomando del binario. El bucle escribe dos heartbeats en un `emptyDir` en memoria:

- `live`, en cada vuelta. Falla si el bucle se traba por más de 120 s. Ese límite supera la espera máxima de reintento (60 s), para que una caída de la base no reinicie el worker.
- `ready`, solo tras una consulta correcta. Vence después del intervalo `PROCESSOR_POLL_MS` más 30 s de margen (90 s con el máximo admitido de 60 s). Así no oscila un worker sano con polling lento, y uno con credenciales malas no completa el rollout.

## Recursos

| Workload | Requests | Limits | Medido con carga |
|---|---|---|---|
| API | 100m / 128Mi | 500m / 256Mi | 201m / 8Mi |
| Worker | 100m / 128Mi | 500m / 256Mi | 47m / 3Mi |
| PostgreSQL | 250m / 256Mi | 1 CPU / 1Gi | 311m / 42Mi |

La memoria medida está muy por debajo de lo solicitado, y la CPU de PostgreSQL superó su request sin llegar al límite. Los requests reservan capacidad en el nodo, así que sobredimensionarlos no cuesta dinero en una VM de precio fijo, pero sí reduce lo que queda para la observabilidad. No se ajustan todavía: esta medición viene de un equipo distinto a la VM.

Superar el límite de memoria provoca `OOMKilled` y un reinicio. Superar el de CPU solo limita el proceso.

## Resultado obtenido · 2026-11-09, ensayo local

**No es la evidencia final.** K3s `v1.35.2+k3s1` desechable en Docker, con una imagen construida desde este commit.

| Prueba | Resultado |
|---|---|
| PostgreSQL detenido durante 150 s | API y worker dejan de estar listos, el endpoint queda sin tráfico y hay 0 reinicios |
| PostgreSQL restaurado | Ambos vuelven a estar listos sin reiniciarse |
| Liveness del worker forzada a fallar | `Container worker failed liveness probe, will be restarted`, 2 reinicios |
| Imagen sin `worker-health` | El rollout falla y no se promueve |
| Carga de 90 s, unas 126 lecturas por segundo | Consumo de la tabla anterior |

Una imagen construida desde Windows puede traer los `.sql` con CRLF, y SQLx rechazaría una base migrada con LF. La imagen publicada por CI no tiene este problema.

## Resultado en Azure · 2026-11-09

VM `Standard_B2s_v2`, namespace `eventos-development`, imagen publicada `sha256:bd50b3cf…`, que todavía no incluye `worker-health`. El generador de carga corría dentro del mismo nodo, por eso la CPU del nodo llegó a 99 %.

| Workload | Reposo | Durante la carga (128 peticiones/s) |
|---|---|---|
| API | 1m / 1Mi | 73m / 7Mi |
| Worker | 5m / 1Mi | 5m / 1Mi |
| PostgreSQL | 23m / 25Mi | 122m / 40Mi |
| Nodo completo | 114m / 1773Mi | 1990m / 1871Mi |

Con estos datos los requests actuales quedan justificados como reserva holgada. El nodo usa 23 % de su memoria, lo que deja espacio para la observabilidad. No se reducen hasta medir con ella instalada.

Con PostgreSQL detenido, la API pasó a `0/1`, salió del endpoint y no se reinició. **El worker publicado siguió en `1/1`**: sin probes no refleja la caída de la base, que es lo que corrige este PR.

## Verificación con `worker-health` en Azure · 2026-11-09

Namespace `eventos-development`, commit `c8581f0`, [ejecución de publicación](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42746903680), digest `sha256:e726151c970772b60b4d557acfc2908fc654c45206000986cec44521f450d4e1`. La firma se comprobó con `gh attestation verify`. Se usaron los manifiestos de `main`, con las tres probes del worker.

| Prueba | Resultado |
|---|---|
| Entrega | `ENTREGA_OK` en 19 s; API y worker `1/1`, digest `e726151c9707` en los Pods |
| PostgreSQL detenido 93 s | API fuera del endpoint antes de 15 s; worker no listo antes de 47 s; 0 reinicios en ambos |
| PostgreSQL restaurado | Los dos vuelven a estar listos solos, sin reinicios; smoke correcto; lecturas 12868 antes y 12869 después, por el smoke |
| Proceso del worker congelado con `SIGSTOP` | No listo antes de 46 s, sin efecto en la API; `Container worker failed liveness probe, will be restarted`; 1 reinicio antes de 186 s y vuelve a `1/1` |
| Después del reinicio | Smoke correcto |

La readiness saca al worker antes de que la liveness lo reinicie, y una caída de la base no provoca reinicios. El consumo medido en la sección anterior corresponde a la imagen sin `worker-health`. Con esta imagen, en reposo: API 1m / 1Mi, worker 17m / 1Mi, PostgreSQL 29m / 27Mi.
