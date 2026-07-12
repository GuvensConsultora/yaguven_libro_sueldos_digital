# -*- coding: utf-8 -*-
"""Wizard exportador del Libro de Sueldos Digital (LSD / F.931).

Genera el TXT de la Interfaz de Liquidacion (registros 01-04) que AFIP/ARCA usa
para pre-cargar el F.931 via "Declaracion en Linea". 100% desde Odoo (no copia
de un export de referencia).

Logica financiera validada contra los 3 TXT reales de Tango (mayo 2026):
- bruta reg04 = suma de creditos del reg03 MENOS los debitos remunerativos
  (concepto 102 'Falta injustificada'); incluye el no remunerativo.
- BI1..BI5,BI8 = gross (bases de aporte/contrib estandar); BI6/BI7 = 0
  (docentes/regimenes especiales, no aplica); BI9 (LRT/ART) = bruta - redondeo
  (incluye el no remunerativo, "NR en ART"); BI10 = gross - detraccion.
- La captura de la bruta contempla las 3 estructuras (UOM/ASS/FOEVA_GROSS).
"""
import base64
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Debitos REMUNERATIVOS del reg03 que reducen la bruta (no son retenciones).
# Segun tabla_conceptos_pehuenche: 102 'Falta injustificada' (ARCA 110000, D).
REMUN_DEBIT = {'102'}
# Detraccion PyME (Ley 27.541), reg04 campo 47, por trabajador.
DETRAC_COMPLETA = 7003.68
DETRAC_MEDIA = 3501.84
# x_codigo_recibo que NO son conceptos del reg03 (bruta/neto/patronales).
XR_EXCLUIR = {'199', '999', '500', '501', '502', '503', '504'}


class LsdExportWizard(models.TransientModel):
    _name = 'lsd.export.wizard'
    _description = 'Exportador Libro de Sueldos Digital (LSD / F.931)'

    year = fields.Integer(
        'Año', required=True, default=lambda s: fields.Date.today().year)
    month = fields.Selection(
        [('01', 'Enero'), ('02', 'Febrero'), ('03', 'Marzo'), ('04', 'Abril'),
         ('05', 'Mayo'), ('06', 'Junio'), ('07', 'Julio'), ('08', 'Agosto'),
         ('09', 'Septiembre'), ('10', 'Octubre'), ('11', 'Noviembre'),
         ('12', 'Diciembre')],
        'Mes', required=True,
        default=lambda s: '%02d' % fields.Date.today().month)
    tipo_liquidacion = fields.Selection(
        [('M', 'Mensual'), ('Q', 'Quincenal'), ('S', 'SAC'), ('F', 'Final')],
        'Tipo de liquidación', default='M', required=True)
    modo_envio = fields.Selection(
        [('SJ', 'SJ · Liquidación + F931'), ('RE', 'RE · Solo rectifica F931')],
        'Modo de envío', default='SJ', required=True)
    nro_liquidacion = fields.Char('Nº liquidación', default='00001', required=True)
    dias_base = fields.Char('Días base (tope)', default='30')
    fecha_pago = fields.Date('Fecha de pago')
    localidad = fields.Char(
        'Código localidad (AFIP)', default='B1',
        help='Código de localidad/zona del reg04. Default provincial; ajustar '
             'si hay establecimientos en distinta jurisdicción.')
    company_id = fields.Many2one(
        'res.company', 'Compañía', required=True,
        default=lambda s: s.env.company)
    # Lety presenta 3 liquidaciones separadas por periodo (confirmado contra
    # los PDF reales de ARCA de mayo/2026): mensualizados, jornalizados, y
    # aparte cualquier empleado con baja ese mes (ej. Beron en mayo, Silva en
    # junio). 'todos' junta todo en una sola liquidacion (uso puntual/legacy).
    grupo = fields.Selection(
        [('todos', 'Todos'), ('mensualizados', 'Mensualizados'),
         ('jornalizados', 'Jornalizados'), ('individual', 'Empleados puntuales (baja)')],
        'Grupo', default='todos', required=True)
    employee_ids = fields.Many2many(
        'hr.employee', string='Empleados a incluir',
        help='Solo si Grupo = "Empleados puntuales": define exactamente quien '
             'entra en esta liquidacion (ej. el empleado con baja ese mes).')
    excluir_employee_ids = fields.Many2many(
        'hr.employee', 'lsd_wizard_excluir_rel', string='Empleados a excluir',
        help='Para Mensualizados/Jornalizados/Todos: saca a estos empleados del '
             'grupo (van en su propia liquidacion individual aparte, ej. bajas).')
    file = fields.Binary('Archivo LSD', readonly=True)
    filename = fields.Char('Nombre', readonly=True)
    log = fields.Text('Resultado', readonly=True)
    state = fields.Selection(
        [('draft', 'Borrador'), ('done', 'Generado')], default='draft')

    # ── Formateadores de campo ────────────────────────────────────────────────
    @staticmethod
    def _alf(v, w):
        """Alfanumérico: recorta/rellena con espacios a la derecha."""
        v = '' if v is None else str(v)
        return v[:w].ljust(w)

    @staticmethod
    def _num(v, w):
        """Numérico: dígitos con ceros a la izquierda (ancho fijo)."""
        v = '' if v is None else str(v).strip()
        v = ''.join(ch for ch in v if ch.isdigit())
        return v[-w:].zfill(w)

    @staticmethod
    def _imp(v, w=15):
        """Importe en centavos, sin signo, ceros a la izquierda (15)."""
        cents = int(round(abs(v or 0) * 100))
        s = str(cents)
        return s[-w:].zfill(w)

    def _periodo(self):
        return '%04d%s' % (self.year, self.month)

    # ── Datos del período ─────────────────────────────────────────────────────
    def _rango_periodo(self):
        import calendar
        y, m = self.year, int(self.month)
        d_from = fields.Date.to_date('%04d-%02d-01' % (y, m))
        last = calendar.monthrange(y, m)[1]
        d_to = fields.Date.to_date('%04d-%02d-%02d' % (y, m, last))
        return d_from, d_to

    def _payslips(self):
        d_from, d_to = self._rango_periodo()
        domain = [
            ('state', '!=', 'cancel'),
            ('company_id', '=', self.company_id.id),
        ]
        if self.tipo_liquidacion == 'S':
            # El aguinaldo se procesa como recibo aparte (fecha desde =
            # inicio del semestre, no del mes) -- se identifica por nombre,
            # no por date_from, a diferencia del mensual/quincenal.
            domain += [('date_to', '=', d_to), ('name', 'ilike', 'Aguinaldo')]
        else:
            domain += [('date_from', '=', d_from)]
        if self.grupo == 'individual':
            domain += [('employee_id', 'in', self.employee_ids.ids)]
        else:
            if self.grupo == 'mensualizados':
                domain += [('contract_id.wage_type', '=', 'monthly')]
            elif self.grupo == 'jornalizados':
                domain += [('contract_id.wage_type', '=', 'hourly')]
            if self.excluir_employee_ids:
                domain += [('employee_id', 'not in', self.excluir_employee_ids.ids)]
        return self.env['hr.payslip'].search(domain)

    # ── Registro 03: conceptos + bruta ────────────────────────────────────────
    def _conceptos_y_bruta(self, payslip):
        """Devuelve (lista de (concepto, importe, dc), gross, redondeo, bruta).

        El campo 3 del reg03 es el codigo PROPIO del empleador (x_codigo_recibo,
        el mismo que aparece impreso en el recibo de Tango), no un codigo ARCA
        traducido -- la asociacion codigo propio -> concepto ARCA ya esta
        registrada de antes en la seccion "Conceptos" del portal LSD (ver
        fuente/arca_conceptos_relacionados_2026-07-01.txt, bajado de ahi).
        Poner el codigo ARCA directo en este campo lo rechaza con "Codigo de
        concepto inexistente" (confirmado al intentar subir el TXT de junio).
        """
        conceptos = []
        gross = redondeo = 0.0
        for line in payslip.line_ids:
            code = line.code or ''
            total = line.total
            if code.endswith('_GROSS'):
                gross = total
            if 'REDONDEO' in code:
                redondeo = total
            if abs(total) < 0.005:
                continue
            if code.startswith('PAT_') or code.endswith('_GROSS') or code.endswith('_NET'):
                continue
            xr = str(line.salary_rule_id.x_codigo_recibo or '')
            if xr in XR_EXCLUIR:
                continue
            if code in ('UOM_OS', 'ASS_OS', 'FOEVA_OS'):
                os_ = payslip.contract_id.obra_social_id
                concepto = str(os_.codigo_lsd if os_ else '' or xr or '')
            else:
                concepto = xr
            if not concepto:
                continue
            dc = 'C' if total >= 0 else 'D'
            conceptos.append((concepto, round(abs(total), 2), dc))
        cred = sum(i for c, i, dc in conceptos if dc == 'C')
        deb_rem = sum(i for c, i, dc in conceptos if dc == 'D' and c in REMUN_DEBIT)
        bruta = round(cred - deb_rem, 2)
        return conceptos, round(gross, 2), round(redondeo, 2), bruta

    def _build_reg03(self, cuil, conceptos):
        out = []
        for concepto, importe, dc in conceptos:
            r = ('03' + self._num(cuil, 11) + concepto.rjust(10) + '00000'
                 + ' ' + self._imp(importe) + dc + ' ' * 6)
            if len(r) != 51:
                raise UserError(_('Reg03 mal formado (%s chars) CUIL %s') % (len(r), cuil))
            out.append(r)
        return out

    # ── Registro 04: bases F931 + datos administrativos ───────────────────────
    def _build_reg04(self, payslip, cuil, gross, redondeo, bruta):
        c = payslip.contract_id
        os = c.obra_social_id
        rnos = os.codigo_os_dgi if os else ''
        # Detracción PyME proporcional a la jornada: media para trabajadores de
        # media jornada (marca `x_os_doble` = doble aporte OS, verificado 4/4
        # contra Tango mayo 2026), completa para el resto.
        detrac = DETRAC_MEDIA if c.x_os_doble else DETRAC_COMPLETA
        b = gross
        bi = [b, b, b, b, b, 0.0, 0.0, b, b]
        bi[8] = round(bruta - redondeo, 2)          # NR en ART
        bi10 = round(gross - detrac, 2)
        modalidad = (c.contract_type_id.code or '').strip()
        # horas trabajadas del recibo (informativo)
        horas = sum(payslip.worked_days_line_ids.mapped('number_of_hours')) or 0
        pct_dif = int(round((c.x_pct_tarea_diferencial or 0) * 100))

        r = (
            '04'
            + self._num(cuil, 11)                    # 3-13
            + '0'                                    # 14 cónyuge
            + '00'                                   # 15-16 hijos
            + '1'                                    # 17 CCT (convenio)
            + '1'                                    # 18 SCVO
            + '0'                                    # 19 reducción
            + '1'                                    # 20 tipo empleador
            + '0'                                    # 21 tipo operación
            + self._num(c.x_situacion_revista, 2)    # 22-23 sit. revista
            + self._num(c.x_condicion, 2)            # 24-25 condición
            + self._num(c.x_actividad, 3)            # 26-28 actividad
            + self._num(modalidad, 3)                # 29-31 modalidad contratación
            + '00'                                   # 32-33 siniestrado
            + self._alf(self.localidad, 2)           # 34-35 localidad
            + '01' + '01'                            # 36-39 sit. revista 1 + día
            + '  00  00'                             # 40-47 slots sit. revista 2/3
            + '00'                                   # 48-49 días trabajados
            + self._num(int(horas), 3)               # 50-52 horas trabajadas
            + '00000'                                # 53-57 % adic. SS
            + self._num(pct_dif, 5)                  # 58-62 % tarea diferencial
            + self._num(rnos, 6)                     # 63-68 RNOS
            + '00'                                   # 69-70 adherentes OS
            + self._imp(0) + self._imp(0)            # 71-100 ap/ct adic. OS
            + '0' * 60                               # 101-160 (reservado)
            + self._imp(bruta)                       # 161-175 remuneración bruta
            + ''.join(self._imp(x) for x in bi)      # 176-310 BI1..BI9
            + '0' * 30                               # 311-340 (reservado)
            + self._imp(bi10)                        # 341-355 BI10
            + self._imp(detrac)                      # 356-370 detracción
        )
        if len(r) != 370:
            raise UserError(_('Reg04 mal formado (%s chars) CUIL %s') % (len(r), cuil))
        return r

    # ── Orquestador ───────────────────────────────────────────────────────────
    def action_generar(self):
        self.ensure_one()
        payslips = self._payslips()
        if not payslips:
            raise UserError(_('No hay recibos en %s para la compañía %s.')
                            % (self._periodo(), self.company_id.name))
        cuit = (self.company_id.vat or '').replace('-', '')
        if not cuit:
            raise UserError(_('La compañía no tiene CUIT cargado.'))

        log = [f'=== LSD {self._periodo()} · {self.company_id.name} ===',
               f'Recibos: {len(payslips)}', '']
        reg02_03 = []
        reg04 = []
        n = 0
        # Reg02 campo tope: '000' = usa tope mensual completo (base 30 dias);
        # el SAC usa tope base 180. No es una preferencia del usuario, es una
        # regla fija de la RG -- se calcula acá, no se toma de self.dias_base.
        tope = '180' if self.tipo_liquidacion == 'S' else '000'
        for ps in payslips:
            emp = ps.employee_id
            cuil = (emp.identification_id or '').replace('-', '')
            if not cuil:
                log.append(f'  SKIP {emp.name}: sin CUIL (identification_id)')
                continue
            if not ps.contract_id:
                log.append(f'  SKIP {emp.name}: sin contrato')
                continue
            conceptos, gross, redondeo, bruta = self._conceptos_y_bruta(ps)
            # reg02
            legajo = emp.barcode or ''
            fpago = (self.fecha_pago or self._rango_periodo()[1])
            r02 = ('02' + self._num(cuil, 11) + self._alf(legajo, 10)
                   + self._alf(emp.name, 50) + ' ' * 22
                   + self._num(tope, 3)
                   + fpago.strftime('%Y%m%d') + ' ' * 8 + '1')
            if len(r02) != 115:
                raise UserError(_('Reg02 mal formado (%s) CUIL %s') % (len(r02), cuil))
            reg02_03.append(r02)
            reg02_03.extend(self._build_reg03(cuil, conceptos))
            reg04.append(self._build_reg04(ps, cuil, gross, redondeo, bruta))
            n += 1
            log.append(f'  OK {legajo:>6} {emp.name[:28]:28} bruta={bruta:,.2f}')

        # reg01
        r01 = ('01' + self._num(cuit, 11) + self.modo_envio + self._periodo()
               + self.tipo_liquidacion + self._num(self.nro_liquidacion, 5)
               + self._num(self.dias_base, 2) + self._num(str(n), 6))
        if len(r01) != 35:
            raise UserError(_('Reg01 mal formado (%s)') % len(r01))

        lines = [r01] + reg02_03 + reg04
        # Sin \r\n final: con el terminador de mas, el parser de ARCA lee una
        # linea 414 fantasma vacia ("El tipo de Registro ... es invalido: ''"),
        # confirmado al intentar subir el TXT.
        txt = '\r\n'.join(lines)
        self.file = base64.b64encode(txt.encode('latin-1', errors='replace'))
        self.filename = 'LSD_%s.txt' % self._periodo()
        log.append('')
        log.append(f'=== Generado: {n} trabajadores, {len(lines)} líneas ===')
        self.log = '\n'.join(log)
        self.state = 'done'
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
