# DEV-05 · Resolución de publicación antes de entregar

Refs #86. El intento de entrega `43113671575` de main `70016ae` terminó en
`resolve`: no cambió API, worker, migración ni datos en ningún ambiente.

La publicación `43101928126` del mismo commit consta como `success` y conserva
el artefacto `image-publication-70016ae967b0df93870c715c3107fbf1c5426cef`.
Se reprodujo una respuesta vacía de `gh run list` al combinar commit/evento con
`--status success`, mientras que al omitir ese último filtro aparece el run.
No se atribuye una causa interna a GitHub sin evidencia adicional.

El workflow consulta hasta 20 publicaciones del **mismo commit** y evento push,
selecciona localmente la primera con conclusión `success` y falla si no existe.
Mantiene descarga del artefacto exacto, verificación de attestation, workflow
firmante, commit firmado, pertenencia a main y aprobación de production.
No admite publicaciones fallidas ni reconstruye la imagen al entregar.

Validación: la consulta corregida devuelve `43101928126`; workflow YAML válido,
pruebas offline existentes y formato/Husky. Este cambio debe integrarse con sus
revisiones antes de relanzar la entrega desde main. No acredita despliegue exitoso.
