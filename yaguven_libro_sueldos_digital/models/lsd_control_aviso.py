# -*- coding: utf-8 -*-
"""Avisos del control previo del Libro de Sueldos Digital.

Un renglon por (recibo, control que salto). Se llena al generar el archivo y
vive lo que dura el asistente: el registro historico es del tablero del periodo,
que es otra pieza.

Ningun aviso frena la generacion. El archivo sale siempre, con avisos o sin
ellos: un control que bloquea deja a la liquidadora esperandonos, que es lo
contrario de lo que este control busca.
"""
from odoo import fields, models


class LsdControlAviso(models.TransientModel):
    _name = 'lsd.control.aviso'
    _description = 'Aviso del control previo del LSD'
    # Primero lo que ARCA rebota seguro, y dentro de cada grupo por legajo, que
    # es el orden en el que ella mira la nomina.
    _order = 'estado, legajo, control'

    wizard_id = fields.Many2one(
        'lsd.export.wizard', 'Asistente', required=True, ondelete='cascade',
        index=True)
    payslip_id = fields.Many2one('hr.payslip', 'Recibo', ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', 'Empleado')
    legajo = fields.Char('Legajo')
    # 'rechaza' antes que 'revisar' tambien alfabeticamente, asi el _order
    # simple los deja en el orden correcto sin campo de secuencia.
    estado = fields.Selection(
        [('rechaza', 'RECHAZA'), ('revisar', 'REVISAR')],
        'Estado', required=True,
        help='RECHAZA: ARCA lo rebota seguro. REVISAR: puede estar bien, pero '
             'conviene mirarlo antes de subir.')
    control = fields.Char('Control', required=True)
    detalle = fields.Char(
        'Qué hacer',
        help='Qué hay que corregir, no sólo qué está mal.')

    def action_abrir_recibo(self):
        """Abre el recibo del aviso.

        Sin esto el aviso dice que algo esta mal y hay que ir a buscarlo entre
        35 recibos: le agregaria trabajo en vez de sacarle.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip',
            'res_id': self.payslip_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
