# Dashboard ESC3 / MET-05

`event-service-met05.json` se puede importar en Grafana. Requiere un datasource Prometheus con UID `event-service-prometheus` y los jobs `event-service` y `event-service-worker`. No contiene credenciales.

Para regenerar el ConfigMap Kubernetes desde la raíz del repositorio:

```sh
node dashboards/render-configmap.cjs
```

Los ocho paneles usan métricas instrumentadas en `src/api.rs` y `src/scenario/store.rs`. Tasas e histogramas usan ventanas de 5 minutos. La ausencia de series y las divisiones sin observaciones se conservan como ausencia de datos / NaN. No hay relleno con cero ni umbrales nuevos.

El provider se monta desde `grafana-dashboards`; Grafana tiene un datasource con UID estable y dos montajes de solo lectura. Los manifiestos se aplican explícitamente en este orden: Jaeger, Prometheus, ConfigMap dashboard, Grafana. El JSON importable queda fuera de `kubernetes/observability` para que no sea interpretado como un recurso Kubernetes.

Resultados reales, limitaciones y comandos: `docs/evidencia/MET-05/README.md`.
## Preguntas operativas

El selector temporal inicia en 30 minutos y el refresco es de 10 segundos. Las tasas y las latencias agregadas usan ventanas móviles de cinco minutos.

| Panel | Pregunta e interpretación | Unidad / período |
| --- | --- | --- |
| Recepción por resultado | ¿Se aceptan, duplican o rechazan lecturas? Separar por `outcome`; ausencia de serie no demuestra cero rechazos. | lecturas/s, tasa de 5 min |
| Procesamiento por segundo | ¿A qué ritmo el worker completa trabajo? Comparar con recepción y backlog; una tasa baja con backlog cero puede significar poca entrada. | lecturas/s, tasa de 5 min |
| Backlog | ¿Queda trabajo pendiente? Es una medición instantánea de pendientes durables al scrape, no una tasa. | lecturas, scrape cada 5 s |
| Latencia HTTP p95 | ¿Qué rutas responden más lentamente? Estimación del percentil del histograma por ruta; incluye errores y éxitos. | segundos, ventana de 5 min |
| Duración de lote p95 | ¿Se ralentizan los lotes del worker? Estimación del percentil; no mide espera individual en inbox. | segundos, ventana de 5 min |
| Estados HTTP | ¿Aumentan respuestas 4xx/5xx? Separar por estado; probes y scrapes también contribuyen a los 200. | solicitudes/s, tasa de 5 min |
| Salud de targets | ¿Prometheus logra observar API y worker? `1` indica scrape exitoso y `0` fallo; no acredita capacidad máxima ni éxito de negocio. | estado 0/1, scrape cada 5 s |
| Duración media de lotes | ¿Cambia el coste medio de procesamiento? Contrastar con p95 y backlog; sin lotes puede devolver NaN. | segundos, ventana de 5 min |

La capacidad se observa indirectamente por ritmo de procesamiento, backlog y salud. Estos paneles no miden CPU/memoria ni acreditan aislamiento o capacidad máxima. La prueba de diez lecturas es funcional; no es un ensayo de saturación ni MET-07.

## Restauración reproducible

Procedimiento documentado para un operador autorizado; no se ejecuta automáticamente al generar el ConfigMap. Requiere la pila Prometheus/Jaeger ya instalada en `eventos-development` y contexto Kubernetes verificado. Desde la raíz:

```sh
node dashboards/render-configmap.cjs
kubectl --namespace eventos-development apply -f kubernetes/observability/grafana-dashboards.yaml
kubectl --namespace eventos-development apply -f kubernetes/observability/grafana.yaml
kubectl --namespace eventos-development rollout status deployment/grafana
```

Grafana vuelve a cargar el provider de archivos y el dashboard con UID `event-service-met05`, datasource `event-service-prometheus`, sin importar ni editar paneles manualmente. Tras una restauración, verificar por túnel `/api/dashboards/uid/event-service-met05`: `meta.provisioned=true`, ocho paneles y datasource esperado. Contrastar consultas y targets con el [procedimiento y evidencia real](../docs/evidencia/MET-05/README.md). La reconstrucción del dashboard no recupera el historial de las pilas `emptyDir`/Jaeger en memoria.