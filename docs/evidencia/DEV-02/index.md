# DEV-02 · Distribuir componentes como imágenes de contenedor

[Issue #8](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/8). Criterios: imagen y Dockerfile versionados, reconstrucción desde el commit, despliegue por digest y ninguna vulnerabilidad crítica sin justificar.

## Decisiones

- **Una imagen para la API y el procesador.** Son el mismo binario con distinto comando (`serve` y `process`), como describe [contenedores.md](../../arquitectura/contenedores.md). Se despliegan por separado, cada uno con su ciclo de vida. Dos imágenes contendrían los mismos bytes y permitirían desplegar versiones incompatibles entre sí.
- **Runtime distroless.** No tiene shell ni gestor de paquetes, lo que reduce lo que un atacante puede usar dentro del contenedor. A cambio, `kubectl exec` no sirve: el diagnóstico usa logs, eventos y `kubectl debug`.
- **Bases fijadas por digest.** Un tag puede cambiar de contenido; el digest no.
- **Usuario 10001 numérico.** Kubernetes solo puede comprobar `runAsNonRoot` con un UID numérico.
- **Sin `HEALTHCHECK` en la imagen.** Kubernetes lo ignora, y la salud se declara con probes en los manifiestos (DEV-11).
- **Labels OCI** `source`, `revision` y `version`, recibidos como argumentos de construcción.

## Cómo reproducir

```bash
docker build -t event-service:local --build-arg VERSION=local --build-arg REVISION="$(git rev-parse HEAD)" .
bash scripts/verify-image.sh event-service:local
```

## Resultado obtenido · 2026-11-08, Docker local

Imagen construida sobre `main` con el Escenario 3 (`3854c07`). Pesa 48.9 MB.

```text
OK     usuario numérico distinto de root (10001:10001)
OK     la imagen no tiene shell
OK     el binario arranca y entrega el contrato OpenAPI
OK     label OCI source = https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps
OK     label OCI revision = 3854c07e6d9c96494f8f2b294658a1df0f116c10
OK     label OCI version = local
OK     la imagen no define variables de secretos
OK     imagen sin vulnerabilidades críticas con parche disponible
OK     crates de Rust sin vulnerabilidades críticas con parche disponible
Imagen verificada: event-service:local
```

El control negativo con `debian:bookworm-slim` terminó con `6 comprobaciones fallaron` y código de salida 1, así que el script sí detecta una imagen que no cumple.

Prueba funcional con Compose: la migración se aplicó y `/health/live` y `/health/ready` respondieron 200. El procesador (`process`) siguió en ejecución sin reiniciarse y `drain` terminó con código 0. En una ejecución anterior, sin el Escenario 3, `/v1/events` sin clave respondió 401.

## Vulnerabilidades

| Alcance | Críticas | Altas |
|---|---|---|
| Imagen (Debian 12) | 0 | 1 |
| Crates de Rust (`Cargo.lock`) | 0 | 0 |

La vulnerabilidad alta es `CVE-2026-84782` en `libssl3`, relacionada con DTLS y con parche disponible. La API usa rustls y no DTLS, por lo que no se considera explotable aquí. Se corrige al actualizar el digest de la base. CI publica el reporte y los SBOM en el artefacto `container-security-evidence`.

## Verificación

- [x] Publicación en GHCR con tag `sha-<corto>` y digest firmado en cada push a `main` ([DEV-04](../DEV-04/index.md)). El workflow también publica el tag `X.Y.Z` cuando se crea un tag `vX.Y.Z`; al 2026-11-12 el repositorio no tiene tags de versión, así que no hay imágenes semver publicadas.
- [x] Despliegue por digest en Azure: [DEV-09](../DEV-09/index.md) y la entrega controlada [43114911744](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/43114911744) de `84e43ab` a development y production ([DEV-05](../DEV-05/index.md)).

## Limitaciones

El binario va sin símbolos, por lo que Trivy no ve sus crates dentro de la imagen. Por eso `Cargo.lock` se analiza aparte y hay dos SBOM. La severidad bloqueante es solo la crítica con parche disponible; las altas quedan en el reporte para revisión.

## Despliegue por digest · 2026-11-09

El clúster de Azure ejecuta la imagen por digest, no por tag: commit `ad1c0c6`, [ejecución de publicación](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42542020614), digest `sha256:bd50b3cf03f23eb754c3635110222330ac6cba76b404101020eb091ef2845095`. El `imageID` de API, worker y Job de migración coincide con ese digest. El detalle está en [DEV-09](../DEV-09/index.md).
