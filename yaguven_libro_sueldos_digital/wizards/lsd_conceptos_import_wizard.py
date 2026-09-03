# -*- coding: utf-8 -*-
"""Refresca la grilla de bases desde el archivo que baja del portal LSD.

Ruta en ARCA: Libro de Sueldos Digital / Conceptos / "Conceptos del
contribuyente" / Exportar. Baja un TXT separado por ';' con una fila por
concepto registrado y las columnas que dicen que bases integra cada uno.
"""
import base64

from odoo import fields, models, _


class LsdConceptosImportWizard(models.TransientModel):
    _name = 'lsd.conceptos.import.wizard'
    _description = 'Importar conceptos del portal LSD'

    file = fields.Binary('Archivo del portal', required=True)
    filename = fields.Char('Nombre')
    company_id = fields.Many2one(
        'res.company', 'Compañía', required=True,
        default=lambda s: s.env.company)
    log = fields.Text('Resultado', readonly=True)
    state = fields.Selection(
        [('draft', 'Borrador'), ('done', 'Importado')], default='draft')

    def action_importar(self):
        self.ensure_one()
        res = self.env['lsd.concepto'].importar_txt(
            base64.b64decode(self.file), self.company_id)
        total = self.env['lsd.concepto'].search_count(
            [('company_id', '=', self.company_id.id)])
        self.write({
            'state': 'done',
            'log': _('Conceptos nuevos: %(nuevos)s\n'
                     'Actualizados: %(act)s\n'
                     'Total en la tabla: %(total)s',
                     nuevos=res['creados'], act=res['actualizados'],
                     total=total),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
