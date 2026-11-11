# ADR-0001 · Monolito modular con puerto de repositorio

> Alcance histórico: API genérica `events`. Para ESC3 y los ciclos de vida
> independientes de API/worker, prevalece [ADR-0005](0005-inbox-esc3.md).

- Estado: aceptada; adaptación Rust, 2026-11-07.
- Contexto: Escenario 3 necesita ingesta, exploración y análisis coherentes, sin equipos/ciclos de despliegue independientes.

Un binario Rust en capas: `api` → `service` → puerto `EventRepository`, implementado por `PostgresRepository`. Configuración y DI explícita en `main`; contratos en `domain`, políticas en `auth`, errores en `error`.

Se descartan microservicios (más infraestructura y transacciones distribuidas sin requisito) y controladores con SQL (acoplamiento y autorización difícil de verificar). El puerto permite dobles de prueba sin un framework DI.

Consecuencias: alta cohesión y una unidad de entrega; ingesta y análisis escalan juntos. Reconsiderar si perfiles de carga o equipos independientes lo exigen. No se atribuye ahorro cloud sin mediciones. Implementación anterior disponible en Git `6ef42ba`; cambio de lenguaje en ADR-0004.
