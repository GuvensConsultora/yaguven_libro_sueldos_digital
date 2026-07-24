from odoo import fields, models


class HrPayrollStructureType(models.Model):
    _inherit = 'hr.payroll.structure.type'

    x_numero_cct = fields.Char(
        'Número de CCT',
        help='Número de Convenio Colectivo de Trabajo a informar en Simplificación '
             'Registral (ARCA) para los contratos de esta estructura. Sin valor por '
             'defecto: se completa a mano porque una misma estructura puede admitir '
             'más de un convenio según la tarea real del empleado (ej. Vinateros '
             'FOEVA/SOEVA: CCT 154/91 viña vs. 85/89 bodega).',
    )
