# DEV-05 · Entrega controlada

[Issue #11](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/11).

## Flujo

[`deliver.yml`](../../../.github/workflows/deliver.yml) se lanza a mano desde `main` con un commit ya publicado:

1. **Resolver:** comprueba que el commit pertenece a `main`, toma el digest de su publicación y verifica la firma. La firma debe corresponder a ese commit y a `publish-image.yml`.
2. **development:** migración, rollout, comprobación del digest en los Pods y smoke.
3. **Aprobación:** el environment `production` espera a un revisor.
4. **production:** el mismo digest y los mismos pasos. No se reconstruye nada.

Si falla la migración, los workloads no cambian. Si falla el rollout o el smoke, [`k8s-deliver.sh`](../../../scripts/k8s-deliver.sh) restaura el template capturado de cada Deployment que la entrega cambió, comprueba su digest y repite el smoke. Compara templates, no anotaciones de revisión que el controlador todavía podría no haber actualizado. Un Deployment que no cambió no se toca. El job falla, así que production no se ejecuta.

## Decisiones

- **Azure Run Command.** El puerto 6443 sigue cerrado y SSH solo acepta IP administradas, así que los runners no llegan al clúster. Run Command no abre puertos ni guarda credenciales.
- **Riesgo aceptado.** Run Command ejecuta como root en la VM, así que la identidad de despliegue tiene control total de la VM. Se limita con OIDC restringido a los environments, un rol acotado a la VM y workflows solo desde `main`. Las escrituras en el clúster usan `event-service-deployer`.
- **Manual y no en cada push.** La VM pasa apagada para controlar costos, y un disparador automático fallaría casi siempre.
- **Actions fijadas por commit** en los jobs con `id-token: write`.
- **El bundle no lleva secretos.** Solo manifiestos y scripts; las claves se leen en el clúster y nunca se imprimen.

## Exposición pública

Solo production se publica, con [`k8s-ingress.sh`](../../../scripts/k8s-ingress.sh). El nombre DNS es la etiqueta de la IP de Azure y el certificado lo emite Let's Encrypt mediante cert-manager, en versión y checksum fijos. La API se sirve solo por HTTPS y exige `X-API-Key`. Development no tiene Ingress.

## Qué versión corre en cada ambiente

```bash
sudo k3s kubectl -n eventos-production get deployment event-service-api \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
gh attestation verify oci://<imagen>@<digest> --repo marchelo23/Proyecto-Final-Metricas-y-DevOps
```

## Puesta en marcha

Se hace una vez. `k8s-bootstrap.sh` e `k8s-ingress.sh` son intervenciones manuales declaradas, porque crean recursos que la cuenta de despliegue no puede crear.

```bash
KUBECTL="sudo k3s kubectl" bash scripts/k8s-bootstrap.sh development
KUBECTL="sudo k3s kubectl" bash scripts/k8s-bootstrap.sh production
KUBECTL="sudo k3s kubectl" bash scripts/k8s-ingress.sh <fqdn>
```

## Resultado obtenido · 2026-11-09, ensayo local

**No es la evidencia final.** K3s `v1.35.2+k3s1` desechable en Docker, con un registro local como espejo de GHCR. El workflow no se ejecutó; el script que envía a la VM sí.

| Prueba | Resultado |
|---|---|
| Entrega a development | `ENTREGA_OK` en 15 s, digest comprobado en los Pods y lectura procesada |
| Repetir el mismo digest | `ENTREGA_OK`, sin cambios |
| Entrega defectuosa, imagen sin `worker-health` | El rollout falla, vuelve a la versión anterior, código de salida 1, 191 s |
| Bootstrap y entrega a production | `ENTREGA_OK` en 17 s |
| HTTPS por Ingress | `/health/live` 200 y sin clave 401 |
| Mismo Ingress por HTTP | 404: la API no se sirve sin cifrar |
| Reto ACME con NetworkPolicy | Alcanzable, 200 |
| `gh attestation verify` sobre la imagen publicada | Correcta, con el commit de la firma |
| `actionlint` y `shellcheck` | Sin hallazgos |

## Restauración automática en Azure · 2026-11-09

`k8s-deliver.sh` ejecutado por SSH en `eventos-development`. El workflow todavía no se ejecutó. Se usaron las imágenes publicadas `bd50b3cf03f2` y `d203a4f1499c`.

| Prueba | Resultado |
|---|---|
| Entrega con `BIND_ADDR` inválido solo en la API | La API vuelve a la revisión capturada; `event-service-worker no cambió` y conserva revisión y Pod; smoke correcto; código de salida 1; 185 s |
| Smoke fallido cuando la entrega cambió API y worker | Ambos vuelven a la revisión capturada, digest comprobado y smoke correcto; código de salida 1; 32 s |
| Entrega correcta de otra versión | `ENTREGA_OK`, digest `d203a4f1499c` en API y worker |

Las lecturas aumentaron solo por los smoke, sin pérdidas.

## Regresiones offline de la revisión

`python3 -m unittest discover -s scripts/tests -v` incluye `test_k8s_delivery.py`.
Ejecuta los scripts reales con dobles locales de `kubectl` y `curl`, sin Azure ni credenciales:
una lectura ajena procesada no satisface el smoke, y un `apply` parcial con anotaciones
de revisión viejas restaura los templates capturados. Cubre cambios solo en API y en
ambos Deployments, conservando intacto un worker no modificado. Estas pruebas no
sustituyen repetir la entrega corregida en el clúster.

## Entrega real en Actions · 2026-11-09

Imagen del commit `c8581f0`, digest `sha256:e726151c970772b60b4d557acfc2908fc654c45206000986cec44521f450d4e1`, firmada en la [publicación](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42746903680). `resolve` verificó la firma en las dos ejecuciones.

| Ejecución | development | Aprobación de production | production |
|---|---|---|---|
| [`42753623476`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42753623476) | `ENTREGA_OK`, smoke correcto | `marchelo23` | `SMOKE FALLÓ: el alta del dispositivo devolvió 401`, sin `ENTREGA_OK`, ejecución fallida |
| [`42757194366`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42757194366) | `ENTREGA_OK`, smoke correcto | `ValeriaCastro20` | `ENTREGA_OK`, smoke correcto, ejecución exitosa |

**Smoke que detuvo la entrega.** La primera ejecución no se completó por un error del propio smoke: un `port-forward` anterior a development seguía ocupando el puerto 18080, y las claves de producción llegaron a la API de development. El [PR #75](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/pull/75) cierra el túnel y rechaza un puerto ocupado. Era la primera entrega a production, así que no había versión a la cual volver y los Deployments quedaron creados hasta la ejecución correcta.

**Aprobación.** En la segunda ejecución, la misma persona lanzó la entrega y aprobó production. GitHub lo permite porque el environment no activa `prevent self-review`. En la primera, lanzó una persona y aprobó otra.

## Verificación de production · 2026-11-09

| Prueba | Resultado |
|---|---|
| Digest en API y worker | `e726151c9707` en el Deployment y en el `imageID` de los Pods, igual que en development |
| Pods | API y worker listos, 0 reinicios |
| `k8s-verify-security.sh production`, antes y después del Ingress | 23 de 23 controles correctos, sin recursos temporales restantes |
| Certificado | Let's Encrypt, emitido por cert-manager `v1.21.3` y válido para el FQDN de production |
| `GET /health/live` y `/health/ready` por HTTPS | 200 |
| `GET /v1/devices` por HTTPS sin clave | 401 |
| `GET /health/live` por HTTP | 404: la API no se sirve sin cifrar |

## Restauración automática con la imagen final · 2026-11-09

`k8s-deliver.sh` por SSH en `eventos-development`, con la imagen `e726151c9707`.

| Prueba | Resultado |
|---|---|
| `BIND_ADDR` inválido solo en la API | API restaurada, `event-service-worker no cambió`, código de salida 1, 186 s |
| Smoke fallido con API y worker cambiados | Los dos restaurados y comprobados, código de salida 1, 17 s |
