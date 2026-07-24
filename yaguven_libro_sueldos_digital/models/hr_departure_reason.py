from odoo import fields, models


class HrDepartureReason(models.Model):
    _inherit = 'hr.departure.reason'

    x_codigo_arca = fields.Char(
        'Código ARCA (motivo de baja)',
        help='Código de la tabla "Motivo de la Baja" de Simplificación Registral '
             '(ARCA), a informar en la Ficha ARCA del wizard de alta/baja.',
    )
