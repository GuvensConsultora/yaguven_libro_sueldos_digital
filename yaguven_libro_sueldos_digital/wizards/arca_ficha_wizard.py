from odoo import api, fields, models


class ArcaFichaWizard(models.TransientModel):
    _name = 'arca.ficha.wizard'
    _description = 'Ficha ARCA (Alta/Baja) - Simplificación Registral'

    employee_id = fields.Many2one('hr.employee', string='Empleado', required=True)
    contract_id = fields.Many2one(
        'hr.contract', string='Contrato', required=True,
        domain="[('employee_id', '=', employee_id)]",
    )
    tipo = fields.Selection(
        [('alta', 'Alta'), ('baja', 'Baja')],
        string='Tipo de trámite', required=True, default='alta',
    )

    # ── Datos de Alta (y comunes al contrato) ───────────────────────────────
    x_cuil = fields.Char('CUIL', compute='_compute_ficha')
    x_domicilio_explotacion = fields.Char('Domicilio de explotación', compute='_compute_ficha')
    x_fecha_inicio = fields.Date('Fecha de inicio', compute='_compute_ficha')
    x_fecha_fin = fields.Date('Fecha de fin (solo si plazo fijo)', compute='_compute_ficha')
    x_modalidad_contratacion = fields.Char('Modalidad de contratación', compute='_compute_ficha')
    x_situacion_revista = fields.Char('Situación de revista', compute='_compute_ficha')
    x_obra_social = fields.Char('Obra social (RNOS)', compute='_compute_ficha')
    x_convenio_cct = fields.Char('Convenio (CCT)', compute='_compute_ficha')
    x_categoria = fields.Char('Categoría', compute='_compute_ficha')
    x_puesto_desempenado = fields.Char('Puesto desempeñado', compute='_compute_ficha')
    x_retribucion_pactada = fields.Monetary(
        'Retribución pactada', compute='_compute_ficha', currency_field='x_currency_id')
    x_currency_id = fields.Many2one('res.currency', compute='_compute_ficha')
    x_modalidad_liquidacion = fields.Char('Modalidad de liquidación', compute='_compute_ficha')

    # ── Datos propios de Baja ───────────────────────────────────────────────
    x_fecha_baja = fields.Date('Fecha de baja', compute='_compute_ficha')
    x_motivo_baja = fields.Char('Motivo de la baja', compute='_compute_ficha')

    # ── Sin fuente confiable en Odoo (B.23): se completan a mano al usar ────
    x_trabajador_agropecuario = fields.Boolean('Trabajador agropecuario')
    x_tipo_servicio = fields.Char(
        'Grupo/Tipo de servicio',
        help='Solo aplica a regímenes previsionales especiales (ANSeS). Dejar '
             'vacío salvo que corresponda.',
    )
    x_fecha_telegrama_renuncia = fields.Date('Fecha telegrama de renuncia (si aplica)')

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        for wiz in self:
            contract = wiz.employee_id.contract_id or self.env['hr.contract'].search(
                [('employee_id', '=', wiz.employee_id.id)], order='date_start desc', limit=1)
            wiz.contract_id = contract
            wiz.tipo = 'baja' if wiz.employee_id.departure_date else 'alta'

    @api.depends('employee_id', 'contract_id')
    def _compute_ficha(self):
        for wiz in self:
            emp = wiz.employee_id
            c = wiz.contract_id
            company = c.company_id if c else emp.company_id
            wiz.x_cuil = emp.identification_id or ''
            wiz.x_domicilio_explotacion = ', '.join(filter(None, [
                company.street,
                company.city,
                company.state_id.name if company.state_id else '',
                company.zip,
            ]))
            wiz.x_fecha_inicio = c.date_start if c else False
            wiz.x_fecha_fin = c.date_end if c else False
            wiz.x_modalidad_contratacion = (
                f'{c.contract_type_id.code} - {c.contract_type_id.name}'
                if c and c.contract_type_id else ''
            )
            wiz.x_situacion_revista = c.x_situacion_revista if c else ''
            wiz.x_obra_social = (
                f'{c.obra_social_id.codigo_os_dgi} - {c.obra_social_id.name}'
                if c and c.obra_social_id else ''
            )
            wiz.x_convenio_cct = (
                c.structure_type_id.x_numero_cct if c and c.structure_type_id else ''
            )
            wiz.x_categoria = c.job_id.name if c and c.job_id else ''
            wiz.x_puesto_desempenado = c.job_id.name if c and c.job_id else ''
            wiz.x_retribucion_pactada = c.wage if c else 0.0
            wiz.x_currency_id = c.currency_id if c else False
            wiz.x_modalidad_liquidacion = (
                dict(c._fields['wage_type'].selection).get(c.wage_type, '') if c else ''
            )
            wiz.x_fecha_baja = emp.departure_date
            wiz.x_motivo_baja = (
                f'{emp.departure_reason_id.x_codigo_arca} - {emp.departure_reason_id.name}'
                if emp.departure_reason_id else ''
            )
