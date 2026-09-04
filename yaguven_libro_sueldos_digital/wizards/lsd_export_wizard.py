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
import math

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
# Reglas que liquidan el aporte de obra social del trabajador. El concepto que
# viaja al reg03 no sale de la regla sino de la obra social del contrato
# (payroll.obra_social.codigo_lsd), porque cada OS tiene el suyo.
OS_APORTE_CODES = {'UOM_OS', 'ASS_OS', 'FOEVA_OS'}


def _techo2(valor):
    """Redondea hacia arriba al centavo, que es como calcula ARCA.

    Medido el 02/09/2026 sobre los tres CUIL de media jornada: para una base de
    703.821,48 al 3% ARCA reclama 21.114,65 y el producto exacto es 21.114,6444;
    para 680.674,76 reclama 20.420,25 contra 20.420,2428. Con redondeo normal
    los dos darian un centavo menos.
    """
    return math.ceil(round(valor * 100, 6)) / 100.0


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
    # El campo del reg01 (posicion 22) dice CADA CUANTO SE PAGA, no que se
    # paga. El diseno oficial de ARCA admite exactamente tres valores:
    # 'M'=mes, 'Q'=quincena, 'S'=SEMANAL. No existe un valor para el SAC ni
    # para la liquidacion final, porque no son tipos de liquidacion: son
    # liquidaciones mas, del mismo tipo, con sus propios conceptos. Julio 2026
    # lo confirma: las tres liquidaciones de ARCA salieron 'M', incluida la de
    # las bajas.
    #
    # Estaba etiquetado ('S','SAC') y ('F','Final'). El segundo ARCA lo
    # rechaza por inexistente, que al menos se nota; el primero es peor,
    # porque 'S' SI es valido: el aguinaldo se declaraba como liquidacion
    # semanal y ARCA lo aceptaba en verde. Paso en junio 2026.
    tipo_liquidacion = fields.Selection(
        [('M', 'Mensual'), ('Q', 'Quincenal'), ('S', 'Semanal')],
        'Tipo de liquidación', default='M', required=True,
        help='Periodicidad del pago, tal como la informa ARCA en la cabecera '
             'del archivo. El aguinaldo y las liquidaciones finales NO son un '
             'tipo aparte: van como Mensual, y se marcan con las opciones de '
             'abajo.')
    excluir_bajas = fields.Boolean(
        'Sacar las bajas del mes', default=True,
        help='Los empleados con cese en el período van en su propia '
             'liquidación, así que salen de Mensualizados y de Jornalizados. '
             'Si no se sacan, aparecen dos veces en el mismo período y ARCA '
             'rechaza por CUIL duplicado. Destildar sólo si se sabe por qué.')
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
        [('mensualizados', 'Mensualizados'),
         ('jornalizados', 'Jornalizados'),
         ('bajas', 'Bajas del mes'),
         ('sac', 'SAC (aguinaldo)'),
         ('individual', 'Empleados puntuales'),
         ('todos', 'Todos (uso puntual)')],
        'Grupo', default='mensualizados', required=True,
        help='Qué recibos entran en esta liquidación. Es el único selector que '
             'decide el contenido: "Bajas del mes" sale sola de la fecha de '
             'cese y no hay que elegir a nadie, y "SAC" además usa el tope '
             'base 180. El tipo de liquidación de la cabecera sigue siendo '
             'Mensual en todos los casos.')
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
        if self.grupo == 'sac':
            # El aguinaldo se procesa como recibo aparte (fecha desde =
            # inicio del semestre, no del mes) -- se identifica por nombre,
            # no por date_from, a diferencia del mensual/quincenal.
            domain += [('date_to', '=', d_to), ('name', 'ilike', 'Aguinaldo')]
        else:
            domain += [('date_from', '=', d_from)]
        # `active_test=False` no es un detalle: al empleado con baja se lo
        # archiva, y un m2m NO devuelve registros archivados. Sin esto el
        # legajo dado de baja desaparece de employee_ids y de
        # excluir_employee_ids **en silencio** -- justo el caso para el que
        # existe el grupo 'individual'. Julio 2026: MALDONADO estaba archivado,
        # la liquidacion de bajas salia con 1 trabajador en vez de 2 y ademas
        # el tipo se colaba en la de jornalizados, que daba 24 en vez de 23.
        # El total seguia dando 37, asi que no habia con que darse cuenta.
        w = self.with_context(active_test=False)
        if self.grupo == 'individual':
            domain += [('employee_id', 'in', w.employee_ids.ids)]
        elif self.grupo == 'bajas':
            domain += [('employee_id', 'in', self._empleados_de_baja().ids)]
        else:
            if self.grupo == 'mensualizados':
                domain += [('contract_id.wage_type', '=', 'monthly')]
            elif self.grupo == 'jornalizados':
                domain += [('contract_id.wage_type', '=', 'hourly')]
            # El que se va no se cuenta dos veces: va en su propia liquidacion.
            # Era un paso manual y por eso se olvidaba -- julio 2026 salio con
            # 13 mensualizados en vez de 12 porque GUBIOTTI, con cese el 08/07,
            # no se habia sacado a mano.
            fuera = w.excluir_employee_ids
            if self.excluir_bajas:
                fuera |= self._empleados_de_baja()
            if fuera:
                domain += [('employee_id', 'not in', fuera.ids)]
        return self.env['hr.payslip'].search(domain)

    def _empleados_de_baja(self):
        """Empleados con fecha de cese dentro del periodo liquidado.

        `active_test=False` porque al darlos de baja se los archiva: sin eso el
        search no los devuelve y volvemos al mismo problema que resolvia.
        """
        self.ensure_one()
        d_from, d_to = self._rango_periodo()
        return self.env['hr.employee'].with_context(active_test=False).search([
            ('departure_date', '>=', d_from),
            ('departure_date', '<=', d_to),
            ('company_id', '=', self.company_id.id),
        ])

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
        grilla = {c.codigo: c.codigo_afip for c in self.env['lsd.concepto'].search(
            [('company_id', '=', self.company_id.id)])}
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
            # El codigo puede depender del contrato y no solo de la regla: la
            # cuota sindical y el seguro de vida de ASIMRA se registran con su
            # propio codigo aunque los calcule la regla de UOM.
            xr = str(line.salary_rule_id.codigo_recibo_para(payslip.contract_id))
            if xr in XR_EXCLUIR:
                continue
            if code in OS_APORTE_CODES:
                os_ = payslip.contract_id.obra_social_id
                concepto = str(os_.codigo_lsd if os_ else '' or xr or '')
            else:
                concepto = xr
            if not concepto:
                continue
            dc = 'C' if total >= 0 else 'D'
            # Cantidad y unidad del reg03. Solo se completan donde ARCA las
            # necesita: el SAC proporcional (concepto ARCA 120003) prorratea su
            # tope con los dias declarados acá, y sin ellos ARCA lo deja AFUERA
            # de las bases topeadas. Se vio el 02/09/2026 en la liquidacion
            # final de GARCIA: "La base imponible 1 informada (361.815,59)
            # difiere de la determinada (264.494,92)" -- la diferencia eran los
            # 97.320,67 del aguinaldo -- y el mismo error en la 4 y en la 5, que
            # son justo las tres bases con tope. Las bases sin tope (2, 3, 8, 9)
            # no dieron error porque ahi el aguinaldo si entraba.
            cantidad, unidad = 0.0, ' '
            if grilla.get(concepto) == '120003':
                cantidad, unidad = payslip._lsd_dias_sac(), 'D'
            conceptos.append((concepto, round(abs(total), 2), dc, cantidad, unidad))
        cred = sum(i for c, i, dc, _q, _u in conceptos if dc == 'C')
        deb_rem = sum(i for c, i, dc, _q, _u in conceptos
                      if dc == 'D' and c in REMUN_DEBIT)
        bruta = round(cred - deb_rem, 2)
        return conceptos, round(gross, 2), round(redondeo, 2), bruta

    def _build_reg03(self, cuil, conceptos):
        out = []
        for concepto, importe, dc, cantidad, unidad in conceptos:
            # Campo 4 'Cantidad': 3 enteros + 2 decimales, sin coma.
            cant = self._num(int(round(float(cantidad) * 100)), 5)
            r = ('03' + self._num(cuil, 11) + concepto.rjust(10) + cant
                 + self._alf(unidad, 1) + self._imp(importe) + dc + ' ' * 6)
            if len(r) != 51:
                raise UserError(_('Reg03 mal formado (%s chars) CUIL %s') % (len(r), cuil))
            out.append(r)
        return out

    # ── Bases imponibles a partir de la grilla de conceptos ───────────────────
    def _bases_desde_conceptos(self, conceptos, payslip, log):
        """BI1..BI9 sumando cada concepto por las bases que integra.

        Es la misma cuenta que hace ARCA para determinar las bases, con la
        grilla que el contribuyente tiene registrada en el portal LSD. Los
        conceptos en debito restan -- es el caso de 'Falta injustificada', que
        integra todas las bases y las baja; las retenciones tambien vienen en
        debito pero tienen la grilla en cero, asi que no mueven nada.
        """
        grilla = self.env['lsd.concepto'].grilla(self.company_id)
        bi = [0.0] * 9
        faltantes = []
        for concepto, importe, dc, _q, _u in conceptos:
            fila = grilla.get(concepto)
            if fila is None:
                faltantes.append(concepto)
                continue
            signo = -1.0 if dc == 'D' else 1.0
            for k, marca in enumerate(fila):
                if marca:
                    bi[k] += signo * importe
        if faltantes:
            # Ruidoso a proposito: un concepto sin grilla sale con base cero y
            # el archivo se sube igual, pero ARCA lo va a rechazar. Es el mismo
            # modo de falla silencioso que tenia el calculo escrito a mano.
            aviso = ('  [!] %s: conceptos sin grilla cargada (%s). Importar la '
                     'tabla desde el portal LSD.'
                     % (payslip.employee_id.name, ', '.join(sorted(set(faltantes)))))
            log.append(aviso)
            _logger.warning(aviso)
        return [round(v, 2) for v in bi]

    # ── Registro 04: bases F931 + datos administrativos ───────────────────────
    def _build_reg04(self, payslip, cuil, gross, redondeo, bruta,
                     conceptos, log):
        c = payslip.contract_id
        os = c.obra_social_id
        rnos = os.codigo_os_dgi if os else ''
        # Detraccion PyME (Ley 27.541), proporcional a la jornada: media para el
        # de media jornada, completa para el resto.
        #
        # Salia de `x_os_doble`, que se usaba como sinonimo de "media jornada"
        # porque en la practica coincidian. Dejaron de coincidir: CIROLIA tenia
        # la marca con jornada COMPLETA, y por eso se le declaraba media
        # detraccion. Se lee de `x_proporcion_jornada`, que es el campo que
        # describe la jornada y nada mas. Para los tres de media jornada el
        # resultado no cambia.
        detrac = (DETRAC_MEDIA if (c.x_proporcion_jornada or 1.0) < 1.0
                  else DETRAC_COMPLETA)
        # ── Bases imponibles 1 a 9 ────────────────────────────────────────
        # No se declaran: ARCA las DETERMINA sumando los conceptos del registro
        # 03 segun la grilla que el contribuyente tiene registrada en el portal
        # (modelo lsd.concepto). Acá se hace la misma cuenta, para que lo que
        # informamos coincida con lo que el validador va a reconstruir.
        #
        # Escribirlas a mano fallo tres veces sobre el libro de agosto 2026,
        # siempre porque la composicion NO depende de si el concepto es
        # remunerativo sino del concepto: 572 y 573 (no remunerativos de
        # UOM/ASIMRA) integran obra social y no LRT, mientras 535 y 556 (los de
        # SOEVA) integran LRT y no obra social. Con la grilla eso sale solo.
        bi = self._bases_desde_conceptos(conceptos, payslip, log)
        base_os = bi[3]
        # Guia N.o 18 (LSD - Bases imponibles): BI10 = BI2 (contribuciones
        # previsionales) menos la detraccion Ley 27.541 -- NO el bruto. Con el
        # bruto, ARCA la determina distinta a la informada apenas hay una falta
        # injustificada u otro concepto que la grilla saca de BI2 pero no del
        # bruto. Confirmado en produccion el 03/09/2026 sobre FREIRE (CUIL
        # 20-31719227-5): "La base imponible 10 informada (1.070.841,92)
        # difiere de la determinada (983.368,22)" -- el bruto menos detraccion
        # daba la primera, BI2 menos detraccion da la segunda, exacto.
        bi10 = round(bi[1] - detrac, 2)
        modalidad = (c.contract_type_id.code or '').strip()
        # Horas trabajadas. Sólo se informan para los jornalizados: en los
        # mensualizados Tango manda '000' y declara los días en su lugar (ver
        # payslip._lsd_dias_trabajados()). Antes iba el mismo número para todos
        # -- las horas TEÓRICAS del calendario, 168 en agosto -- que no describía
        # a nadie: el que trabajó 40 horas informaba 168 igual que el resto.
        if (c.wage_type or '') == 'hourly':
            horas = sum(payslip.worked_days_line_ids.mapped('number_of_hours')) or 0
        else:
            horas = 0
        # Campos 28 y 29: aporte y contribucion ADICIONALES de obra social.
        #
        # Es el canal por el que se declara que el de media jornada aporta como
        # jornada completa (art. 92 ter LCT). Antes se resolvia duplicando las
        # bases 4 y 8, y ARCA lo rechaza (ver arriba): la base la determina el
        # sistema a partir de los conceptos, no se la puede forzar. Lo que si
        # acepta es el excedente declarado aparte, y ahi valida
        #     aporte informado == alicuota x base 4 + campo 28.
        # Medido el 02/09/2026: con la base ya sin duplicar, ARCA reclamo
        # "El aporte de obra social calculado es de $21.114,65 y Ud. informa
        # $42.229,29" -- exactamente la mitad, que es lo que va en el campo 28.
        #
        # Las alicuotas salen de la obra social del contrato (3% retencion y 6%
        # contribucion en las tres de Pehuenche), no de una constante.
        ap_adic = c.x_aporte_adic_os or 0.0
        co_adic = c.x_contrib_adic_os or 0.0
        # Sin obra social nacional no hay nada de obra social que declarar. Lo
        # dijo ARCA el 02/09/2026 sobre CIROLIA, jubilada en actividad, apenas
        # se la declaro con la condicion correcta: "el codigo de obra social
        # debe ser cero" y "No puede especificarse importe adicional de obra
        # social para esta actividad". Con RNOS y adicionales en cero, entro.
        #
        # Quien lo decide es el CODIGO DE CONDICION, no una marca nuestra: la
        # tabla de ARCA ya dice, por condicion, si genera aportes de obra social
        # (`arca.codigo.aportes_os`). La condicion 02 'Jubilado' no genera, y es
        # exactamente el dato que ARCA cruza cuando dice "de acuerdo a los datos
        # ingresados".
        if c.x_condicion_id and not c.x_condicion_id.aportes_os:
            rnos = ''
            adherentes = 0
            ap_adic = co_adic = 0.0
        else:
            adherentes = int(c.x_adherentes_os or 0)
        if c.x_os_doble and os and rnos:
            retenido = round(sum(
                abs(l.total) for l in payslip.line_ids
                if (l.code or '') in OS_APORTE_CODES), 2)
            estandar = _techo2(base_os * (os.porcentaje_retencion or 0.0) / 100.0)
            # max() por si el recibo no retiene obra social (contrato exento):
            # sin aporte no hay excedente que declarar.
            ap_adic += max(0.0, round(retenido - estandar, 2))
            co_adic += _techo2(base_os * (os.porcentaje_aporte or 0.0) / 100.0)
        pct_dif = int(round((c.x_pct_tarea_diferencial or 0) * 100))
        pct_adic_ss = int(round((c.x_aporte_adicional_ss or 0) * 100))
        emp = payslip.employee_id

        # Grupo familiar: sale de la ficha del empleado, no del contrato.
        conyuge = '1' if emp.marital in ('married', 'cohabitant') else '0'
        hijos = self._num(int(emp.children or 0), 2)

        # Localidad: la del establecimiento donde presta servicios. El valor del
        # wizard queda como respaldo para los contratos que todavía no la tengan
        # cargada, pero NO es lo correcto cuando hay más de un establecimiento:
        # la localidad determina el porcentaje de reducción de contribuciones.
        localidad = (c.x_localidad_id.codigo if c.x_localidad_id else self.localidad) or ''

        tipo_empleador = (c.x_tipo_empleador_id.codigo if c.x_tipo_empleador_id
                          else '1')

        r = (
            '04'
            + self._num(cuil, 11)                    # 3-13
            + conyuge                                # 14 cónyuge
            + hijos                                  # 15-16 hijos
            + ('1' if c.x_en_convenio else '0')      # 17 CCT (convenio)
            + ('1' if c.x_scvo else '0')             # 18 SCVO
            + ('1' if c.x_corresponde_reduccion else '0')   # 19 reducción
            + self._alf(tipo_empleador, 1)           # 20 tipo empleador
            + self._alf(c.x_tipo_operacion or '0', 1)       # 21 tipo operación
            + c._arca_codigo('x_situacion_revista_id', 'x_situacion_revista', 2)
            + c._arca_codigo('x_condicion_id', 'x_condicion', 2)
            + c._arca_codigo('x_actividad_id', 'x_actividad', 3)
            + self._num(modalidad, 3)                # 29-31 modalidad contratación
            + self._alf(c.x_siniestrado_id.codigo or '00', 2)   # 32-33 siniestrado
            + self._alf(localidad, 2)                # 34-35 localidad
            + payslip._lsd_situaciones()             # 36-47 sit. revista 1/2/3 + días
            + payslip._lsd_dias_trabajados()         # 48-49 días trabajados
            + self._num(int(horas), 3)               # 50-52 horas trabajadas
            + self._num(pct_adic_ss, 5)              # 53-57 % adic. SS
            + self._num(pct_dif, 5)                  # 58-62 % tarea diferencial
            + self._num(rnos, 6)                     # 63-68 RNOS
            + self._num(adherentes, 2)               # 69-70 adherentes OS
            + self._imp(ap_adic)                     # 71-85 aporte adic. OS
            + self._imp(co_adic)                     # 86-100 contrib. adic. OS
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

        # Aviso ruidoso si se eligieron N empleados y no salieron N recibos.
        # El modo silencioso es el peligroso: el archivo sale con uno menos y
        # el total del periodo puede seguir cerrando igual.
        if self.grupo == 'individual':
            elegidos = self.with_context(active_test=False).employee_ids
            faltan = elegidos - payslips.mapped('employee_id')
            if faltan:
                log.append('  [!] SIN RECIBO en este periodo, quedan afuera: '
                           + ', '.join(faltan.mapped('name')))
                log.append('')
        reg02_03 = []
        reg04 = []
        n = 0
        # Reg02 campo tope: '000' = usa tope mensual completo (base 30 dias);
        # el SAC usa tope base 180. No es una preferencia del usuario, es una
        # regla fija de la RG -- se calcula acá, no se toma de self.dias_base.
        # Depende de que la liquidacion SEA del aguinaldo, no del tipo que se
        # informa en la cabecera: el SAC va como 'M' igual que el resto. Sale
        # del mismo selector que decide que recibos entran, para que no puedan
        # quedar desalineados (antes eran dos campos distintos).
        tope = '180' if self.grupo == 'sac' else '000'
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
            reg04.append(self._build_reg04(ps, cuil, gross, redondeo, bruta,
                                           conceptos, log))
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
