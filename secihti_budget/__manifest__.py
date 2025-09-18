# -*- coding: utf-8 -*-
{
    "name": "SECIHTI Project Budget",
    "summary": "Budget control for SECIHTI financed projects",
    "version": "14.0.1.0.0",
    "author": "ChatGPT",
    "website": "",
    "category": "Project",
    "license": "LGPL-3",
    "depends": [
        "purchase",
        "mail",
    ],
    "data": [
        "security/sec_security.xml",
        "security/ir.model.access.csv",
        "data/sec_rubro_data.xml",
        "views/sec_menus.xml",
        "views/sec_project_views.xml",
        "views/sec_stage_views.xml",
        "views/sec_activity_views.xml",
        "views/sec_rubro_views.xml",
        "views/purchase_order_views.xml",
        "views/import_activity_wizard_views.xml",
        "views/export_report_wizard_views.xml",
    ],
    "application": True,
    "installable": True,
}
