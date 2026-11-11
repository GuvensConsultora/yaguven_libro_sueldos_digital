# -*- coding: utf-8 -*-
"""Avisos del control previo AL PAGO de sueldos.

Son los mismos controles del Libro de Sueldos Digital (`lsd.export.wizard`),
corridos en otro momento: apenas se calculan los recibos, antes de pagarlos.

Por que existe: en octubre 2026 los recibos retuvieron obra social sin los no
remunerativos del acuerdo UOM. El control que lo hubiera visto estaba en el
exportador del LSD, que se corre DESPUES de pagar. ARCA rechazo 28 CUIL el
dia del vencimiento (11/11/2026), con los sueldos ya pagados. Un control que
avisa cuando la plata ya salio no protege nada.

A diferencia de `lsd.control.aviso` (transitorio, vive lo que dura el
asistente), estos se guardan: quedan pegados al recibo hasta el proximo calculo,
que los reemplaza.

Ningun aviso frena nada. El recibo se calcula y se paga igual: un control que
bloquea deja a la liquidadora esperandonos.
"""
from odoo import fields, models


class PayrollControlAviso(models.Model):
    _name = 'payroll.control.aviso'
    _description = 'Aviso del control previo al pago de sueldos'
    # Mismo orden que el control del LSD: primero lo que ARCA rebota seguro,
    # y dentro de cada grupo por legajo, que es como ella mira la nomina.
    _order = 'estado, legajo, control'

    payslip_id = fields.Many2one(
        'hr.payslip', 'Recibo', ondelete='cascade', index=True,
        help='Vacío cuando el aviso es del período y no de una persona '
             '(por ejemplo, un concepto nuevo que usan varios).')
    # Guardado aparte y no como related: los avisos del periodo no tienen
    # recibo, y tienen que aparecer igual en el lote.
    run_id = fields.Many2one(
        'hr.payslip.run', 'Lote', ondelete='cascade', index=True)
    company_id = fields.Many2one('res.company', 'Compañía', required=True,
                                 index=True)
    periodo = fields.Char('Período', required=True, index=True,
                          help='AAAAMM, como en el Libro de Sueldos.')
    employee_id = fields.Many2one('hr.employee', 'Empleado')
    legajo = fields.Char('Legajo')
    estado = fields.Selection(
        [('rechaza', 'RECHAZA'), ('revisar', 'REVISAR')],
        'Gravedad', required=True,
        help='RECHAZA: ARCA lo va a rebotar. Conviene corregir el recibo antes '
             'de pagar. REVISAR: puede estar bien, pero hay que mirarlo.')
    control = fields.Char('Control', required=True)
    detalle = fields.Char(
        'Qué pasa y qué hacer',
        help='Trae los dos importes: el del recibo y el que espera ARCA.')

    def action_abrir_recibo(self):
        """Abre el recibo del aviso, para no tener que buscarlo entre 35."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip',
            'res_id': self.payslip_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
