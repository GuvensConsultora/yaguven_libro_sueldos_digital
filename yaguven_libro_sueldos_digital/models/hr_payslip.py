from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrPayslipSituacionRevista(models.Model):
    """Situaciones de revista de un recibo, con el día en que empieza cada una.

    La situación de revista no es del contrato sino del período liquidado: la
    misma persona puede estar activa del 1 al 14 y en licencia por maternidad del
    15 en adelante. Por eso vive acá y no en `hr.contract`.

    ARCA admite hasta tres tramos por período (registro 04, posiciones 36 a 47).
    """
    _name = 'hr.payslip.situacion.revista'
    _description = 'Situación de revista del período'
    _order = 'dia_inicio, id'

    payslip_id = fields.Many2one(
        'hr.payslip', 'Recibo', required=True, ondelete='cascade', index=True)
    situacion_id = fields.Many2one(
        'arca.codigo', 'Situación', required=True,
        domain="[('tabla', '=', 'situacion')]",
        options="{'no_create': True}",
    )
    dia_inicio = fields.Integer(
        'Día de inicio', required=True, default=1,
        help='Día del mes en que empieza esta situación. El primer tramo '
             'arranca el 1.',
    )

    @api.constrains('dia_inicio')
    def _check_dia_inicio(self):
        for linea in self:
            if not 1 <= linea.dia_inicio <= 31:
                raise ValidationError(
                    _('El día de inicio tiene que estar entre 1 y 31 (se cargó %s).')
                    % linea.dia_inicio)

    @api.constrains('payslip_id')
    def _check_cantidad(self):
        """ARCA reserva tres tramos por período: un cuarto no entra en el archivo."""
        for linea in self:
            if len(linea.payslip_id.x_situacion_revista_ids) > 3:
                raise ValidationError(_(
                    'El Libro de Sueldos Digital admite hasta 3 situaciones de '
                    'revista por período. Si hiciera falta informar más, hay que '
                    'consultarlo con ARCA.'))


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    x_situacion_revista_ids = fields.One2many(
        'hr.payslip.situacion.revista', 'payslip_id',
        'Situaciones de revista del período',
        help='Si se deja vacío, se informa la situación de revista del contrato '
             'desde el día 1, que es el caso de quien trabajó el mes completo '
             'sin novedades.',
    )
    x_dias_trabajados = fields.Integer(
        'Cantidad de días trabajados',
        help='Días del período que corresponde tributar. Se completa solo con 30 '
             'para el mes entero; se corrige cuando la persona ingresa o egresa '
             'a mitad de mes, porque de este número depende el importe a detraer.',
    )
    x_maternidad_art13 = fields.Monetary(
        'Maternidad / Art. 13 ley 27.674', currency_field='currency_id',
        help='Monto a informar cuando la trabajadora está en licencia por '
             'maternidad. En ese caso las remuneraciones van en cero y el importe '
             'se declara acá.',
    )

    @api.constrains('x_dias_trabajados')
    def _check_dias_trabajados(self):
        """El campo son 2 posiciones: un 100 se informaría como '00' en silencio."""
        for slip in self:
            if not 0 <= slip.x_dias_trabajados <= 31:
                raise ValidationError(
                    _('Los días trabajados tienen que estar entre 0 y 31 '
                      '(se cargó %s).') % slip.x_dias_trabajados)

    def _lsd_situaciones(self):
        """Los tres tramos como los espera el registro 04 (posiciones 36 a 47).

        Devuelve siempre 12 caracteres: por cada tramo, 2 del código y 2 del día.
        Los tramos no usados van con el código en blanco y el día en '00', que es
        como los emite el aplicativo.
        """
        self.ensure_one()
        lineas = self.x_situacion_revista_ids.sorted('dia_inicio')[:3]
        if not lineas:
            # Sin novedades: la situación del contrato desde el día 1. Es el
            # comportamiento que tenía el exportador antes de que existieran
            # estas líneas, y cubre a la enorme mayoría de los recibos.
            codigo = self.contract_id._arca_codigo(
                'x_situacion_revista_id', 'x_situacion_revista', 2)
            return codigo + '01' + '  00' + '  00'

        partes = []
        for linea in lineas:
            partes.append((linea.situacion_id.codigo or '').strip().zfill(2))
            partes.append(str(linea.dia_inicio).zfill(2))
        while len(partes) < 6:
            partes += ['  ', '00']
        return ''.join(partes)

    def _lsd_dias_trabajados(self):
        """Días a informar: lo cargado, y si no, 30 (el mes completo)."""
        self.ensure_one()
        return str(self.x_dias_trabajados or 30).zfill(2)[-2:]
