# Corrección documental de auditoría MET-07 y costos

Refs #89. Base contrastada: `main` en `eb8fa8f`.

- El plan MET-07 vigente solo pide dos minutos de carga y registros separados de
  intentos, estados/fallos de conexión e IDs. No exige JSONL ni identifica el
  generador. Tampoco fija diez minutos de espera global, limpieza ante error o
  cancelación ni acreditación de `firing` antes de restaurar. La auditoría pasa a
  reconocer esas ausencias, sin afirmar que ya se corrigió el plan.
- Se corrigen también las filas relacionadas de la misma tabla: carga hasta T4,
  intervalos sin solicitudes y descripción de señales como pendientes de integrar.
  El código de gauge/regla existe; verificar su operación es otra evidencia.
- COM-06 enlaza costos y DEV-14: controles y cargos observados al 2026-11-08,
  US$2.21 acumulados desde 2026-10-20. No se atribuye ese saldo al presente ni se
  equipara el presupuesto mensual con el máximo agregado de US$100.

Verificación: comparación literal contra `docs/evidencia/MET-07/index.md`,
`docs/infra/costos.md` y `docs/evidencia/DEV-14/index.md`; enlaces locales y tabla
Markdown comprobados, `git diff --check` y formato Rust. No hay cambios de código,
de Terraform ni del procedimiento MET-07; no se ejecuta degradación o despliegue.
CI, revisión de CodeRabbit y revisión humana se verifican por separado en el PR.
