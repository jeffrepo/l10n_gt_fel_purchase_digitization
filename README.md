# Serie y número FEL desde Compras - Odoo 19

Al usar **Compras > Orden de compra > Subir factura**, este complemento lee
la serie y el número del PDF original del proveedor y completa los campos
existentes `account.move.fel_serie` y `account.move.fel_numero` de INFILE FEL.
También se ejecuta en el flujo de importación de adjuntos de Contabilidad.

Requiere Odoo 19 y los módulos `purchase` e `infilefel`. Usa el lector PDF que
ya incluye Odoo; no requiere instalar librerías ni contratar otro servicio.
Es independiente de `gdomex`: se instala como un módulo adicional.

## Instalación en Odoo.sh

1. Agregar la carpeta `l10n_gt_fel_purchase_digitization` al repositorio de
   addons de una rama de pruebas de Odoo.sh, junto a los demás módulos.
2. Esperar a que termine la compilación, actualizar la lista de aplicaciones
   e instalar **Guatemala - Serie y número FEL desde compras**.
3. Abrir una orden de compra confirmada y usar **Subir factura** con el PDF
   original. Abrir la factura de proveedor resultante y comprobar los campos.
4. En facturas en borrador que ya tengan el PDF, usar el botón
   **Leer serie y número del PDF**, junto al campo Número.

La instalación en pruebas y producción no se ha realizado desde este proyecto.

## Alcance

- Lee los rótulos `Serie` y `Número de DTE` (también `Número`, `Número de
  documento` y `Número de factura`, con dos puntos). La serie FEL debe tener
  ocho caracteres hexadecimales. Conserva números como texto, incluidos ceros
  iniciales y valores mayores que el límite de un entero de 32 bits.
- Requiere un PDF con texto seleccionable, como el ejemplo proporcionado.
  No implementa OCR de imágenes: fotografías, PDF escaneados sin capa de texto,
  documentos cifrados y formatos no reconocidos requieren revisión manual.
  La digitalización estándar sigue disponible para los demás campos; activar
  ese OCR no garantiza el llenado de estos dos campos personalizados.
- Solo completa campos vacíos de facturas/notas de crédito de proveedor en
  borrador. Si un valor existente contradice al PDF, no completa el otro.
- No cambia la referencia, el número interno, la autorización FEL, el proveedor,
  los importes, los impuestos ni las líneas. No publica ni certifica facturas.
- Si encuentra varios PDF en la misma importación, no elige uno al azar. Para
  reintentar, seleccionar el PDF correcto como adjunto principal de la factura.
- Revisa hasta 50 páginas, 20 MiB y dos millones de caracteres. Omite documentos
  fuera de esos límites y documentos con series/números contradictorios.
- No cambia la configuración de digitalización ni sus créditos. La extracción
  de estos dos campos es local; el OCR estándar mantiene su funcionamiento.

## Verificación

Pruebas del analizador, ejecutables sin Odoo desde la carpeta del módulo:

```sh
python3 tests/test_fel_parser.py
```

Pruebas de integración en una base de pruebas Odoo 19 con las dependencias:

```sh
odoo-bin -d BASE_DE_PRUEBAS -i l10n_gt_fel_purchase_digitization --test-enable --test-tags /l10n_gt_fel_purchase_digitization --stop-after-init
```

Incluyen importación de adjuntos, carga desde Compras, conflictos, varios PDF,
documentos inválidos y exclusión de facturas de clientes. El PDF del usuario
se prueba por separado y no se distribuye dentro del módulo.

Validación local realizada: siete pruebas del analizador aprobadas, lectura
correcta del PDF original proporcionado, pruebas con PDF sintéticos (ceros
iniciales, datos contradictorios, sin texto y cifrados), sintaxis Python y XML,
y existencia del campo en la vista INFILE FEL 19 disponible en el proyecto.
Las pruebas de integración quedan pendientes: este entorno no tiene un servidor
Odoo 19 ni una base de datos de pruebas.

El punto de integración se comprobó contra el código oficial de Odoo 19:
[carga desde Compras](https://github.com/odoo/odoo/blob/19.0/addons/purchase/models/purchase_order.py),
[importación contable](https://github.com/odoo/odoo/blob/19.0/addons/account/models/account_document_import_mixin.py)
y [lector PDF](https://github.com/odoo/odoo/blob/19.0/odoo/tools/pdf/__init__.py).
La [documentación de digitalización](https://www.odoo.com/documentation/19.0/applications/finance/accounting/vendor_bills/invoice_digitization.html)
describe los campos estándar reconocidos por OCR; este complemento agrega el
llenado de los dos campos personalizados indicados por el usuario.
