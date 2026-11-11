# ADR-0002 · PostgreSQL 16 y SQLx

> El esquema `events` corresponde al contrato genérico. Las tablas y garantías
> actuales de ESC3 se documentan en [ADR-0005](0005-inbox-esc3.md).

- Estado: aceptada; adaptación Rust, 2026-11-07.
- Contexto: unicidad concurrente, lote atómico, durabilidad y agregados JSONB.

Se mantiene PostgreSQL 16 y el mismo esquema `events`. SQLx reemplaza ORM/driver anteriores con consultas parametrizadas asíncronas y migraciones SQL embebidas. La base impone unicidad natural y COMMIT antes de 201. Agregados se calculan en SQL; listado/resumen leen un snapshot repetible.

Alternativas: memoria sin persistencia no cumple durabilidad; NoSQL sin garantías transaccionales no simplifica el lote; motor columnar y ETL añaden componentes y desfase no exigidos. Un ORM Rust no aporta valor suficiente para estas consultas explícitas.

Costes: dependencia de PostgreSQL y SQL específico; mitigar con pool acotado, timeouts y reintentos limitados solo de lecturas transitorias. Índices no garantizan rendimiento sin EXPLAIN/benchmarks. Migración de datos existentes requiere backup y ensayo; ver persistencia y ADR-0004.
