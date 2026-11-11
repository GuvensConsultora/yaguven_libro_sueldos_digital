# -*- coding: utf-8 -*-
"""Control previo AL PAGO: corre solo despues de cada calculo de recibos.

Usa los MISMOS controles del exportador del Libro de Sueldos
(`lsd.export.wizard._correr_controles`), no una copia: arma el archivo por
dentro para los recibos recien calculados, sin guardarlo en ningun lado, y
deja los avisos pegados a cada recibo. Un control en dos momentos, no dos
controles que con el tiempo dicen cosas distintas.

El momento importa mas que el control. En octubre 2026 el control de obra
social existia (solo para media jornada) y corria al generar el LSD, que es
DESPUES de pagar. Aca corre al calcular, que es ANTES.

Dos reglas que no se negocian:
- Nunca frena el calculo. Si el control falla, el recibo queda calculado igual
  y el error va al log. Corre dentro de un savepoint para que una falla suya no
  arrastre nada del calculo.
- No modifica el recibo. Solo escribe avisos.
"""
import logging
from collections import defaultdict

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    control_aviso_ids = fields.One2many(
        'payroll.control.aviso', 'payslip_id', 'Control previo al pago')
    control_avisos_count = fields.Integer(
        'Avisos', compute='_compute_control_avisos')
    control_rechaza = fields.Boolean(
        'ARCA lo rechazaría', compute='_compute_control_avisos')

    @api.depends('control_aviso_ids.estado')
    def _compute_control_avisos(self):
        for slip in self:
            slip.control_avisos_count = len(slip.control_aviso_ids)
            slip.control_rechaza = any(
                a.estado == 'rechaza' for a in slip.control_aviso_ids)

    def compute_sheet(self):
        res = super().compute_sheet()
        try:
            with self.env.cr.savepoint():
                self._control_previo_pago()
        except Exception:
            # Ruidoso en el log y silencioso para ella: el recibo ya esta bien
            # calculado y no tiene por que enterarse de una falla nuestra.
            _logger.exception('Control previo al pago: fallo sobre %s recibos; '
                              'el calculo sigue igual.', len(self))
        return res

    def action_control_previo_pago(self):
        """Volver a correr el control sin recalcular (boton del recibo/lote)."""
        self._control_previo_pago()
        return True

    def _control_previo_pago(self):
        slips = self.filtered(
            lambda s: s.state != 'cancel' and s.contract_id and s.date_from)
        if not slips:
            return
        # Se agrupa como agrupa el Libro de Sueldos: compania + periodo, y el
        # aguinaldo aparte porque usa otro tope (base 180) y otro periodo.
        grupos = defaultdict(lambda: self.env['hr.payslip'])
        for s in slips:
            es_sac = 'aguinaldo' in (s.name or '').lower()
            ref = s.date_to if es_sac else s.date_from
            grupos[(s.company_id.id, ref.year, ref.month, es_sac)] |= s

        Wizard = self.env['lsd.export.wizard']
        Aviso = self.env['payroll.control.aviso']
        for (company_id, year, month, es_sac), grupo in grupos.items():
            periodo = '%04d%02d' % (year, month)
            wiz = Wizard.create({
                'company_id': company_id,
                'year': year,
                'month': '%02d' % month,
                # 'individual' limita el archivo a estos empleados. El SAC no:
                # su grupo ya filtra por nombre y por periodo.
                'grupo': 'sac' if es_sac else 'individual',
                'employee_ids': [(6, 0, grupo.mapped('employee_id').ids)],
            })
            # Solo los recibos de este calculo: si el empleado tiene otro recibo
            # en el periodo (otra liquidacion, otro lote), no se mezcla.
            wiz = wiz.with_context(lsd_payslip_ids=grupo.ids)
            controlados = wiz._payslips()
            wiz.action_generar()

            # Los avisos anteriores de estos recibos se reemplazan, no se
            # acumulan: un aviso que ya se corrigio no puede seguir en pantalla.
            Aviso.search([('payslip_id', 'in', controlados.ids)]).unlink()
            Aviso.search([('payslip_id', '=', False),
                          ('company_id', '=', company_id),
                          ('periodo', '=', periodo)]).unlink()

            # Los avisos del periodo (sin recibo) van al lote, si es uno solo.
            lotes = controlados.mapped('payslip_run_id')
            lote_unico = lotes.id if len(lotes) == 1 else False
            vals = []
            for a in wiz.aviso_ids:
                vals.append({
                    'payslip_id': a.payslip_id.id or False,
                    'run_id': a.payslip_id.payslip_run_id.id or lote_unico,
                    'company_id': company_id,
                    'periodo': periodo,
                    'employee_id': a.employee_id.id or False,
                    'legajo': a.legajo,
                    'estado': a.estado,
                    'control': a.control,
                    'detalle': a.detalle,
                })
            if vals:
                Aviso.create(vals)
            _logger.info('Control previo al pago %s: %s recibos, %s avisos.',
                         periodo, len(controlados), len(vals))


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    control_aviso_ids = fields.One2many(
        'payroll.control.aviso', 'run_id', 'Control previo al pago')
    control_avisos_count = fields.Integer(
        'Avisos', compute='_compute_control_avisos')

    @api.depends('control_aviso_ids')
    def _compute_control_avisos(self):
        for run in self:
            run.control_avisos_count = len(run.control_aviso_ids)

    def action_control_previo_pago(self):
        self.slip_ids._control_previo_pago()
        return True
