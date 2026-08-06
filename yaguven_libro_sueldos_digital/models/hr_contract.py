from odoo import api, fields, models


class HrContract(models.Model):
    """Datos del contrato que ARCA exige en el registro 04 del Libro de Sueldos.

    La pantalla espeja la de "Declaración en Línea" de ARCA a propósito: quien
    liquida da de alta primero en ARCA y después en el sistema, así que carga los
    mismos datos dos veces. Si acá se ven en otro orden o con otros nombres, cada
    alta obliga a traducir mentalmente entre las dos pantallas.

    Los códigos salen del catálogo `arca.codigo` (módulo `yaguven_arca_tablas`),
    que trae las tablas oficiales. No se escriben a mano: un código que no exista
    en la tabla de ARCA hace que el libro no valide, y ese error recién aparece
    al presentar.
    """
    _inherit = 'hr.contract'

    # ── Campos de texto originales ────────────────────────────────────────────
    # Se conservan hasta verificar la migración a los many2one de abajo. El
    # exportador ya lee los many2one, con estos como respaldo.
    x_situacion_revista = fields.Char(
        'Situación de revista (AFIP)',
        default='01',
        help='OBSOLETO: usar "Situación de revista". Se conserva como respaldo.',
    )
    x_condicion = fields.Char(
        'Condición (AFIP)',
        default='01',
        help='OBSOLETO: usar "Condición". Se conserva como respaldo.',
    )
    x_actividad = fields.Char(
        'Actividad (AFIP)',
        default='001',
        help='OBSOLETO: usar "Actividad". Se conserva como respaldo.',
    )

    # ── Perfil del trabajador ─────────────────────────────────────────────────
    x_situacion_revista_id = fields.Many2one(
        'arca.codigo', 'Situación de revista',
        domain="[('tabla', '=', 'situacion')]",
        default=lambda self: self._default_arca('situacion', '01'),
        help='Situación del trabajador al inicio del período. "01 - Activo" es '
             'lo habitual; el resto son licencias, suspensiones y siniestros.',
    )
    x_condicion_id = fields.Many2one(
        'arca.codigo', 'Condición',
        domain="[('tabla', '=', 'condicion')]",
        default=lambda self: self._default_arca('condicion', '01'),
        help='Define el régimen previsional: servicios comunes, jubilado, menor '
             'de 18, servicios diferenciados.',
    )
    x_actividad_id = fields.Many2one(
        'arca.codigo', 'Actividad',
        domain="[('tabla', '=', 'actividad')]",
        default=lambda self: self._default_arca('actividad', '001'),
        help='Actividad desarrollada, según la tabla de ARCA.',
    )
    x_siniestrado_id = fields.Many2one(
        'arca.codigo', 'Código de siniestrado',
        domain="[('tabla', '=', 'incapacidad')]",
        default=lambda self: self._default_arca('incapacidad', '00'),
        help='Se completa cuando el trabajador tuvo un accidente de trabajo o '
             'in itinere. "00 - No Incapacitado" es lo habitual.',
    )
    x_localidad_id = fields.Many2one(
        'arca.codigo', 'Localidad',
        domain="[('tabla', '=', 'localidad')]",
        help='Zona geográfica del establecimiento donde presta servicios. '
             'Determina el porcentaje de reducción de contribuciones, así que '
             'difiere entre establecimientos aunque estén en la misma provincia.',
    )

    # ── Datos generales ───────────────────────────────────────────────────────
    x_en_convenio = fields.Boolean(
        'Trabajador en CCT', default=True,
        help='Destildar para el personal fuera de convenio.',
    )
    x_scvo = fields.Boolean(
        'Cobertura de Seguro Colectivo de Vida Obligatorio', default=True,
        help='Destildar para quienes no tienen la cobertura. El total de tildados '
             'tiene que coincidir con "Cuiles c/S.C.V.O." del F.931.',
    )
    x_corresponde_reduccion = fields.Boolean(
        'Corresponde reducción',
        help='Marca de reducción de contribuciones patronales. El porcentaje lo '
             'determina ARCA según la localidad del establecimiento.',
    )
    x_tipo_empleador_id = fields.Many2one(
        'arca.codigo', 'Tipo de empleador',
        domain="[('tabla', '=', 'empleador')]",
        help='Encuadre del empleador. Para una empresa privada es el del '
             'Dto. 814/01, art. 2, inc. b).',
    )
    x_tipo_operacion = fields.Char(
        'Tipo de operación', default='0',
        help='Uso excepcional: en la operatoria habitual va en 0.',
    )
    x_base_diferencial_lrt = fields.Monetary(
        'Base diferencial LRT', currency_field='currency_id',
        help='Base adicional sobre la que se calcula la alícuota de riesgos del '
             'trabajo, cuando la tarea tiene una alícuota diferencial.',
    )

    # ── Seguridad social ──────────────────────────────────────────────────────
    x_aporte_adicional_ss = fields.Float(
        'Aporte adicional seguridad social (%)',
        help='Porcentaje de aporte adicional del trabajador.',
    )
    x_pct_tarea_diferencial = fields.Float(
        '% contribución tarea diferencial',
        default=0.0,
        help='Contribución adicional del empleador por tarea diferencial. El '
             'régimen agrario, por ejemplo, aporta un 2% extra.',
    )
    x_base_dif_aporte_ss = fields.Monetary(
        'Base diferencial de aporte (SS)', currency_field='currency_id')
    x_base_dif_contrib_ss = fields.Monetary(
        'Base diferencial de contribución (SS)', currency_field='currency_id')

    # ── Obra social ───────────────────────────────────────────────────────────
    x_adherentes_os = fields.Integer(
        'Cantidad de adherentes', default=0,
        help='Familiares adheridos a la obra social del trabajador.',
    )
    x_aporte_adic_os = fields.Monetary(
        'Aporte adicional obra social', currency_field='currency_id',
        help='Monto fijo adicional que retiene el convenio, cuando corresponde.',
    )
    x_contrib_adic_os = fields.Monetary(
        'Contribución adicional obra social', currency_field='currency_id')
    x_base_dif_aporte_os = fields.Monetary(
        'Base diferencial de aporte (OS)', currency_field='currency_id')
    x_base_dif_contrib_os = fields.Monetary(
        'Base diferencial de contribución (OS)', currency_field='currency_id')

    # ── Helpers ───────────────────────────────────────────────────────────────
    @api.model
    def _default_arca(self, tabla, codigo):
        """Código por defecto de una tabla ARCA, o vacío si no está cargado.

        Devuelve el id y no el registro porque se usa como `default` de un
        many2one. Si el catálogo todavía no se cargó, el campo queda vacío en
        lugar de romper la creación del contrato.
        """
        return self.env['arca.codigo'].search(
            [('tabla', '=', tabla), ('codigo', '=', codigo)], limit=1).id

    def _arca_codigo(self, campo_m2o, campo_char, ancho):
        """Código a informar, tomando el many2one y cayendo al texto anterior.

        Mientras dure la convivencia entre los campos viejos de texto y los
        nuevos many2one, el exportador tiene que poder generar el archivo con
        cualquiera de los dos cargados.
        """
        self.ensure_one()
        registro = self[campo_m2o] if campo_m2o in self._fields else False
        valor = registro.codigo if registro else (self[campo_char] or '')
        return str(valor).strip().zfill(ancho)
