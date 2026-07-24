{
    'name': 'Yagüven - Libro de Sueldos Digital (LSD/F.931)',
    'version': '18.0.3.0.0',
    'summary': 'Exportador del Libro de Sueldos Digital (interfaz AFIP/ARCA) para Declaración en Línea',
    'description': '''
Libro de Sueldos Digital (LSD)
==============================

Genera el archivo TXT de la Interfaz de Liquidación (registros 01-04) que
AFIP/ARCA usa para pre-cargar el F.931 vía "Declaración en Línea".

- Wizard de exportación por período (año/mes) desde el menú de Nómina.
- Registros armados 100% desde Odoo (sin depender de un export de referencia
  de otro sistema).
- Códigos de tabla AFIP (situación de revista, condición, actividad,
  modalidad de contratación) como campos nuevos en el contrato, con default
  al valor mayoritario para minimizar carga manual.
- Ficha ARCA (Alta/Baja): wizard que arma, desde el legajo, los datos a tipear
  en Simplificación Registral (no hay webservice de alta/baja de ARCA), en el
  orden del formulario oficial.
''',
    'author': 'Yagüven C.G.',
    'category': 'Human Resources/Payroll',
    'license': 'LGPL-3',
    'depends': ['hr_payroll', 'payroll_ar_reform_27802'],
    'data': [
        'security/ir.model.access.csv',
        'data/hr_departure_reason_data.xml',
        'views/hr_contract_views.xml',
        'views/hr_payroll_structure_type_views.xml',
        'wizards/lsd_export_wizard_views.xml',
        'wizards/arca_ficha_wizard_views.xml',
        'views/hr_employee_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
