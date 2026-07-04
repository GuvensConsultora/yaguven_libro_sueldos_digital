from odoo import fields, models


class HrContract(models.Model):
    _inherit = 'hr.contract'

    # ── Códigos AFIP del Libro de Sueldos Digital (reg. 04) ────────────────────
    # Default = el que aplica a la gran mayoria de los contratos (validado contra
    # Tango mayo 2026, 36/38 casos). Solo se pisa en las excepciones puntuales.
    x_situacion_revista = fields.Char(
        'Situación de revista (AFIP)',
        default='01',
        help='Código de tabla "Situación de Revista" del LSD (reg. 04, campo 16).',
    )
    x_condicion = fields.Char(
        'Condición (AFIP)',
        default='01',
        help='Código de "condición" del LSD (reg. 04, campo 9).',
    )
    x_actividad = fields.Char(
        'Actividad (AFIP)',
        default='001',
        help='Código de tabla "Actividades" del LSD (reg. 04, campo 12).',
    )
    x_pct_tarea_diferencial = fields.Float(
        '% contribución tarea diferencial',
        default=0.0,
        help='Porcentaje de contribución adicional por tarea diferencial (LSD reg. 04, '
             'campo 25). 0 salvo excepción puntual del convenio.',
    )
