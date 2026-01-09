# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SecBudgetAllocation(models.Model):
    _name = 'sec.budget.allocation'
    _description = 'Budget Allocation (Simulation)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'planned_expense_id, sequence, id'

    name = fields.Char(
        string='Description',
        compute='_compute_name',
        store=True
    )

    simulation_id = fields.Many2one(
        'sec.budget.simulation',
        string='Simulation',
        required=True,
        ondelete='cascade',
        index=True
    )

    planned_expense_id = fields.Many2one(
        'sec.planned.expense',
        string='Planned Expense',
        required=True,
        ondelete='cascade',
        index=True
    )

    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='Used to order allocations'
    )

    # Source of the budget (the "from" side of the red line)
    activity_id = fields.Many2one(
        'sec.activity',
        string='Activity',
        required=True,
        ondelete='restrict',
        help='Activity containing the budget line'
    )

    budget_line_id = fields.Many2one(
        'sec.activity.budget.line',
        string='Budget Line (Rubro)',
        required=True,
        domain="[('activity_id', '=', activity_id)]",
        ondelete='restrict',
        help='Specific budget line (rubro) to allocate from'
    )

    rubro_id = fields.Many2one(
        'sec.rubro',
        related='budget_line_id.rubro_id',
        string='Rubro',
        readonly=True,
        store=True
    )

    # Amount to allocate (portion of the planned expense covered by this budget line)
    amount = fields.Monetary(
        string='Allocated Amount',
        required=True,
        currency_field='currency_id',
        help='Amount to allocate from this budget line to the planned expense'
    )

    # Budget line information (for reference and validation)
    line_rem_total = fields.Monetary(
        string='Line Remaining Budget',
        related='budget_line_id.rem_total',
        readonly=True,
        help='Remaining budget available in this budget line (from real budget)'
    )

    line_amount_total = fields.Monetary(
        string='Line Total Budget',
        related='budget_line_id.amount_total',
        readonly=True
    )

    # Simulated remaining after this allocation
    simulated_remaining = fields.Monetary(
        string='Simulated Remaining',
        compute='_compute_simulated_remaining',
        store=True,
        currency_field='currency_id',
        help='Simulated remaining budget after all allocations in this simulation'
    )

    simulated_remaining_status = fields.Selection([
        ('positive', 'Positive'),
        ('zero', 'Zero'),
        ('negative', 'Negative')
    ], string='Status', compute='_compute_simulated_remaining', store=True)

    simulated_remaining_color = fields.Char(
        string='Status Color',
        compute='_compute_simulated_remaining',
        help='Color indicator for simulated remaining'
    )

    currency_id = fields.Many2one(
        'res.currency',
        related='simulation_id.currency_id',
        string='Currency',
        readonly=True,
        store=True
    )

    project_id = fields.Many2one(
        'sec.project',
        related='simulation_id.project_id',
        string='Project',
        readonly=True,
        store=True
    )

    notes = fields.Text(
        string='Notes',
        help='Additional notes about this allocation'
    )

    @api.depends('budget_line_id', 'rubro_id', 'amount')
    def _compute_name(self):
        for allocation in self:
            if allocation.budget_line_id and allocation.rubro_id:
                allocation.name = _('%s → %s (%s)') % (
                    allocation.rubro_id.name,
                    allocation.planned_expense_id.name if allocation.planned_expense_id else _('Expense'),
                    allocation.amount
                )
            else:
                allocation.name = _('New Allocation')

    @api.depends('budget_line_id.rem_total', 'amount', 'simulation_id.planned_expense_ids.allocation_ids.amount')
    def _compute_simulated_remaining(self):
        """
        Calculate simulated remaining budget for this budget line
        considering all allocations in the simulation
        """
        for allocation in self:
            if not allocation.budget_line_id:
                allocation.simulated_remaining = 0
                allocation.simulated_remaining_status = 'zero'
                allocation.simulated_remaining_color = 'muted'
                continue

            # Get the real remaining budget from the budget line
            real_remaining = allocation.budget_line_id.rem_total

            # Get all allocations for this budget line in this simulation
            all_allocations = self.search([
                ('simulation_id', '=', allocation.simulation_id.id),
                ('budget_line_id', '=', allocation.budget_line_id.id)
            ])

            # Sum all allocated amounts
            total_allocated = sum(all_allocations.mapped('amount'))

            # Calculate simulated remaining
            simulated_rem = real_remaining - total_allocated

            allocation.simulated_remaining = simulated_rem

            # Determine status
            if simulated_rem > 0:
                status = 'positive'
                color = 'success'
            elif simulated_rem == 0:
                status = 'zero'
                color = 'info'
            else:
                status = 'negative'
                color = 'danger'

            allocation.simulated_remaining_status = status
            allocation.simulated_remaining_color = color

    @api.constrains('amount')
    def _check_amount_positive(self):
        for allocation in self:
            if allocation.amount <= 0:
                raise ValidationError(_('The allocation amount must be greater than zero.'))

    @api.constrains('amount', 'budget_line_id', 'simulation_id')
    def _check_simulated_budget_available(self):
        """
        Warn (but don't block) if allocation would make simulated remaining negative
        This is a soft check - we allow over-allocation in simulation
        """
        for allocation in self:
            if allocation.simulated_remaining < 0:
                # Just log a warning, don't raise an error
                # In simulation mode, we allow "what if" scenarios
                pass

    @api.constrains('planned_expense_id', 'simulation_id')
    def _check_simulation_consistency(self):
        for allocation in self:
            if allocation.planned_expense_id.simulation_id != allocation.simulation_id:
                raise ValidationError(
                    _('The planned expense and allocation must belong to the same simulation.')
                )

    @api.onchange('budget_line_id')
    def _onchange_budget_line_id(self):
        """Auto-fill activity when budget line is selected"""
        if self.budget_line_id:
            self.activity_id = self.budget_line_id.activity_id

    @api.onchange('activity_id')
    def _onchange_activity_id(self):
        """Clear budget_line_id if activity changes"""
        if self.activity_id:
            # Update domain for budget_line_id
            return {
                'domain': {
                    'budget_line_id': [('activity_id', '=', self.activity_id.id)]
                }
            }
        else:
            self.budget_line_id = False
            return {
                'domain': {
                    'budget_line_id': []
                }
            }


class SecActivityBudgetLine(models.Model):
    """Extend budget line to show simulated allocations"""
    _inherit = 'sec.activity.budget.line'

    simulation_allocation_ids = fields.One2many(
        'sec.budget.allocation',
        'budget_line_id',
        string='Simulation Allocations',
        help='Allocations from this budget line in simulations'
    )

    def action_view_simulations(self):
        """View all simulations using this budget line"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Simulations for %s') % self.rubro_id.name,
            'res_model': 'sec.budget.allocation',
            'view_mode': 'tree,form',
            'domain': [('budget_line_id', '=', self.id)],
            'context': {'default_budget_line_id': self.id},
            'target': 'current',
        }
