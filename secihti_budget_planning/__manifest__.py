# -*- coding: utf-8 -*-
{
    'name': 'SECIHTI Budget Planning',
    'version': '14.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Graphical budget planning and simulation for SECIHTI projects',
    'description': """
        SECIHTI Budget Planning and Simulation
        =======================================

        This module provides a graphical interface for planning and simulating
        how to use remaining budgets in SECIHTI projects.

        Features:
        ---------
        * Visual budget planning interface
        * Create planned expenses (simulated)
        * Allocate budget from multiple rubros to expenses
        * Partial or full allocation support
        * Simulation mode - doesn't affect real budgets
        * Track budget movements and allocations
        * Smart auto-complete: One-click to complete expenses to 100%
        * Quick allocation wizard with budget suggestions
        * Real-time warnings for over-allocation
        * Contextual alerts and visual feedback
    """,
    'author': 'SECIHTI',
    'website': '',
    'depends': ['secihti_budget'],
    'data': [
        'security/ir.model.access.csv',
        'views/sec_budget_allocation_wizard_views.xml',
        'views/sec_budget_simulation_views.xml',
        'views/sec_planned_expense_views.xml',
        'views/sec_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
