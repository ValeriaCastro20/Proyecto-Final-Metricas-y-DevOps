# DEV-12 · Recuperar una versión funcional

[Issue #18](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/18).

## Runbook

1. **Detectar.** La entrega falla en el rollout o en el smoke, o una probe saca el Pod del servicio.
2. **Diagnosticar**, sin cambiar nada:

   ```bash
   sudo k3s kubectl -n eventos-production get pods
   sudo k3s kubectl -n eventos-production describe deployment event-service-api
   sudo k3s kubectl -n eventos-production get events --sort-by=.lastTimestamp
   sudo k3s kubectl -n eventos-production logs deployment/event-service-api --tail=50
   ```

3. **Elegir la versión sana.** `KUBECTL="sudo k3s kubectl" bash scripts/k8s-rollback.sh production` sin imagen lista las versiones conservadas. Su firma se comprueba con `gh attestation verify`.
4. **Revertir.** `KUBECTL="sudo k3s kubectl" bash scripts/k8s-rollback.sh production <imagen@sha256:...>`. Solo modifica los Deployments que no estén sanos en esa versión: un worker que no cambió no retrocede.
5. **Verificar.** El script comprueba rollout, digest en los Pods y smoke, y termina con `ROLLBACK_OK`. Confirmar los Pods con `get pods`.
6. **Registrar** causa, digest anterior, digest restaurado y tiempo.

`k8s-deliver.sh` restaura y comprueba por sí solo cuando falla una entrega, usando los templates que capturó antes de empezar, sin depender de que el controlador haya actualizado la anotación de revisión.

El smoke compartido con la entrega comprueba `event_id` y `processed_at` en el mismo objeto JSON. Una lectura anterior procesada no permite dar por recuperado un evento nuevo pendiente. La regresión offline está en `scripts/tests/test_k8s_delivery.py`; no acredita una nueva ejecución del rollback en Azure.

## Qué no hace un rollback

- **No restaura datos.** Solo cambia los Deployments; el PVC de PostgreSQL no se toca.
- **No revierte migraciones.** No hay downgrades automáticos. Toda migración debe ser compatible con la versión anterior mientras dure una entrega: agregar columnas o tablas, no borrarlas ni renombrarlas en el mismo cambio.
- **Si la base se dañó,** el rollback no alcanza: hace falta un respaldo, y hoy no hay uno automatizado.

## Simulacro

[`k8s-rollback-drill.sh`](../../../scripts/k8s-rollback-drill.sh) solo actúa sobre development. Provoca solo en la API una imagen inexistente y luego una configuración inválida, recupera, comprueba que el worker no se modificó y compara el número de lecturas.

## Resultado obtenido · 2026-11-09, ensayo local

**No es la evidencia final.** K3s `v1.35.2+k3s1` desechable en Docker, con la primera versión del script.

| Falla provocada | Cómo se detectó | Tiempo total | Solo rollback y smoke | Después |
|---|---|---|---|---|
| Imagen inexistente | `ImagePullBackOff`, el rollout no termina | 84 s | 7 s | Versión anterior activa y smoke correcto |
| `BIND_ADDR` inválido | `CrashLoopBackOff`, el rollout no termina | 83 s | 6 s | Versión anterior activa y smoke correcto |

El tiempo total incluye 75 s de espera antes de declarar fallido el rollout. Las lecturas pasaron de 1 a 3: se conservaron las anteriores y se sumaron las de los smoke. El Pod anterior siguió atendiendo durante las dos fallas, porque `maxUnavailable` es 0.

## Resultado en Azure · 2026-11-09

Clúster K3s de la VM del proyecto, namespace `eventos-development`, imágenes publicadas `bd50b3cf03f2` y `d203a4f1499c`. Esta tabla corresponde al script corregido: el simulacro ya no crea una revisión artificial del worker.

| Falla provocada solo en la API | Cómo se detectó | Tiempo total | Solo rollback y smoke | Worker |
|---|---|---|---|---|
| Imagen inexistente | `ImagePullBackOff`, el rollout no termina | 82 s | 6 s | Misma generación, revisión, imagen y Pod |
| `BIND_ADDR` inválido | `CrashLoopBackOff`, el rollout no termina | 81 s | 5 s | Misma generación, revisión, imagen y Pod |

El tiempo total incluye 75 s de espera antes de declarar fallido el rollout. Las lecturas pasaron de 12865 a 12867 por los smoke, sin pérdidas, y el simulacro terminó con `SIMULACRO_OK`.

| Vuelta manual | Resultado |
|---|---|
| De `d203a4f1499c` a `bd50b3cf03f2`, en API y worker | Los dos restaurados, digest comprobado en los Pods, smoke correcto, `ROLLBACK_OK` en 7 s |
| Repetir con la misma imagen | `ya está sano en esa versión: no se modifica`; generación y Pods iguales |

## Verificación del código integrado · 2026-11-09

Namespace `eventos-development`, commit `c8581f0`, [ejecución de publicación](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42746903680), digest `sha256:e726151c970772b60b4d557acfc2908fc654c45206000986cec44521f450d4e1`. Repite el simulacro con los scripts de `main`, incluido el smoke que valida la lectura exacta.

| Falla provocada solo en la API | Tiempo total | Solo rollback y smoke | Worker |
|---|---|---|---|
| Imagen inexistente | 81 s | 5 s | Misma generación, revisión, imagen y Pod |
| `BIND_ADDR` inválido | 80 s | 4 s | Misma generación, revisión, imagen y Pod |

Las lecturas pasaron de 12873 a 12875 por los smoke, y el simulacro terminó con `SIMULACRO_OK`.

| Vuelta manual | Resultado |
|---|---|
| De `e726151c9707` a `e76a3dbdda59`, imagen firmada del commit `f4c23e1` | Los dos restaurados, digest comprobado en los Pods, smoke correcto, `ROLLBACK_OK` en 11 s |
| Entrega posterior de `e726151c9707` | `ENTREGA_OK`; lecturas de 12878 a 12880, solo por los smoke |

## Límite

El script considera sana una revisión si tiene el digest pedido y su rollout terminó. Una configuración mala que pase las probes no se detecta ahí: el smoke final falla y hay que revisar a mano.

Cada Deployment conserva 3 revisiones anteriores (`revisionHistoryLimit`). Tras varias fallas seguidas, una versión antigua deja de estar disponible: al pedir `bd50b3cf03f2` después de los simulacros, el script respondió `no conserva otra revisión con esa imagen`, terminó con error y no modificó nada.
