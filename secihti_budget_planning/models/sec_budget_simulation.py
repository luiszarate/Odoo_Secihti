# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SecBudgetSimulation(models.Model):
    _name = 'sec.budget.simulation'
    _description = 'Budget Planning Simulation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Simulation Name',
        required=True,
        default=lambda self: _('New Simulation')
    )

    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today
    )

    project_id = fields.Many2one(
        'sec.project',
        string='Project',
        required=True,
        ondelete='cascade'
    )

    stage_id = fields.Many2one(
        'sec.stage',
        string='Stage',
        domain="[('project_id', '=', project_id)]",
        help='Optional: Filter by stage'
    )

    description = fields.Text(
        string='Description',
        help='Description of this simulation scenario'
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('archived', 'Archived')
    ], string='Status', default='draft', required=True, tracking=True)

    planned_expense_ids = fields.One2many(
        'sec.planned.expense',
        'simulation_id',
        string='Planned Expenses'
    )

    total_planned_amount = fields.Monetary(
        string='Total Planned',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )

    total_allocated_amount = fields.Monetary(
        string='Total Allocated',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )

    total_unallocated_amount = fields.Monetary(
        string='Total Unallocated',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )

    currency_id = fields.Many2one(
        'res.currency',
        related='project_id.currency_id',
        string='Currency',
        readonly=True
    )

    notes = fields.Html(
        string='Notes',
        help='Additional notes about this simulation'
    )

    @api.depends('planned_expense_ids.amount', 'planned_expense_ids.allocated_amount')
    def _compute_totals(self):
        for simulation in self:
            total_planned = sum(simulation.planned_expense_ids.mapped('amount'))
            total_allocated = sum(simulation.planned_expense_ids.mapped('allocated_amount'))
            simulation.total_planned_amount = total_planned
            simulation.total_allocated_amount = total_allocated
            simulation.total_unallocated_amount = total_planned - total_allocated

    def action_activate(self):
        self.ensure_one()
        self.write({'state': 'active'})
        return True

    def action_archive(self):
        self.ensure_one()
        self.write({'state': 'archived'})
        return True

    def action_set_draft(self):
        self.ensure_one()
        self.write({'state': 'draft'})
        return True

    def action_view_graphical_planning(self):
        """Open the graphical planning view"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Budget Planning - %s') % self.name,
            'res_model': 'sec.budget.simulation',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
            'context': {'form_view_ref': 'secihti_budget_planning.view_sec_budget_simulation_planning_form'}
        }
