# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SecBudgetAllocationWizard(models.TransientModel):
    _name = 'sec.budget.allocation.wizard'
    _description = 'Budget Allocation Wizard'

    planned_expense_id = fields.Many2one(
        'sec.planned.expense',
        string='Planned Expense',
        required=True,
        readonly=True
    )

    simulation_id = fields.Many2one(
        'sec.budget.simulation',
        string='Simulation',
        required=True,
        readonly=True
    )

    expense_amount = fields.Monetary(
        string='Expense Amount',
        related='planned_expense_id.amount',
        readonly=True
    )

    allocated_amount = fields.Monetary(
        string='Already Allocated',
        related='planned_expense_id.allocated_amount',
        readonly=True
    )

    remaining_amount = fields.Monetary(
        string='Remaining to Allocate',
        related='planned_expense_id.remaining_amount',
        readonly=True
    )

    currency_id = fields.Many2one(
        'res.currency',
        related='simulation_id.currency_id',
        readonly=True
    )

    allocation_line_ids = fields.One2many(
        'sec.budget.allocation.wizard.line',
        'wizard_id',
        string='Budget Lines Available'
    )

    @api.model
    def default_get(self, fields_list):
        """Populate wizard with available budget lines"""
        res = super().default_get(fields_list)

        # Get planned_expense_id from context if not in res
        expense_id = res.get('planned_expense_id') or self._context.get('default_planned_expense_id')
        simulation_id = res.get('simulation_id') or self._context.get('default_simulation_id')

        if expense_id:
            expense = self.env['sec.planned.expense'].browse(expense_id)

            if not expense.exists():
                return res

            # Set IDs if not already set
            res['planned_expense_id'] = expense.id
            res['simulation_id'] = simulation_id or expense.simulation_id.id

            # Get available budget lines
            available_lines = expense._get_available_budget_lines()

            # Create wizard lines
            wizard_lines = []
            for budget_line in available_lines:
                simulated_remaining = expense._get_simulated_remaining(budget_line)

                # Skip lines with no remaining budget
                if simulated_remaining <= 0:
                    continue

                # Suggest amount: min of (remaining expense, simulated remaining)
                suggested_amount = min(expense.remaining_amount, simulated_remaining) if expense.remaining_amount > 0 else 0

                wizard_lines.append((0, 0, {
                    'budget_line_id': budget_line.id,
                    'activity_id': budget_line.activity_id.id,
                    'rubro_id': budget_line.rubro_id.id,
                    'available_amount': simulated_remaining,
                    'suggested_amount': suggested_amount,
                    'amount': 0,  # User will select
                }))

            res['allocation_line_ids'] = wizard_lines

        return res

    def action_allocate(self):
        """Create allocations from selected lines"""
        self.ensure_one()

        if not self.allocation_line_ids:
            raise UserError(_('No budget lines available. Please check that there are activities with remaining budget in this project.'))

        # Get lines with amount > 0
        lines_to_allocate = self.allocation_line_ids.filtered(lambda l: l.amount > 0)

        if not lines_to_allocate:
            raise UserError(_('Please enter an amount for at least one budget line.'))

        # Create allocations
        allocations = self.env['sec.budget.allocation']
        for line in lines_to_allocate:
            allocations |= self.env['sec.budget.allocation'].create({
                'simulation_id': self.simulation_id.id,
                'planned_expense_id': self.planned_expense_id.id,
                'activity_id': line.activity_id.id,
                'budget_line_id': line.budget_line_id.id,
                'amount': line.amount,
            })

        # Return action to close wizard and show notification
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success!'),
                'message': _('%s allocation(s) created successfully. Total allocated: %s') % (
                    len(allocations),
                    sum(allocations.mapped('amount'))
                ),
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_allocate_suggested(self):
        """Quick allocate using suggested amounts"""
        self.ensure_one()

        # Set all amounts to suggested amounts
        for line in self.allocation_line_ids:
            line.amount = line.suggested_amount

        return self.action_allocate()


class SecBudgetAllocationWizardLine(models.TransientModel):
    _name = 'sec.budget.allocation.wizard.line'
    _description = 'Budget Allocation Wizard Line'
    _order = 'available_amount desc, sequence, id'

    wizard_id = fields.Many2one(
        'sec.budget.allocation.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade'
    )

    sequence = fields.Integer(
        string='Sequence',
        default=10
    )

    budget_line_id = fields.Many2one(
        'sec.activity.budget.line',
        string='Budget Line',
        required=True,
        readonly=True
    )

    activity_id = fields.Many2one(
        'sec.activity',
        string='Activity',
        readonly=True
    )

    rubro_id = fields.Many2one(
        'sec.rubro',
        string='Rubro',
        readonly=True
    )

    available_amount = fields.Monetary(
        string='Available Budget',
        readonly=True,
        currency_field='currency_id',
        help='Simulated remaining budget for this budget line'
    )

    suggested_amount = fields.Monetary(
        string='Suggested',
        readonly=True,
        currency_field='currency_id',
        help='Suggested allocation amount'
    )

    amount = fields.Monetary(
        string='Amount to Allocate',
        currency_field='currency_id',
        help='Amount you want to allocate from this budget line'
    )

    currency_id = fields.Many2one(
        'res.currency',
        related='wizard_id.currency_id',
        readonly=True
    )

    @api.onchange('amount')
    def _onchange_amount(self):
        """Warn if amount exceeds available"""
        if self.amount > self.available_amount:
            return {
                'warning': {
                    'title': _('Warning'),
                    'message': _('The amount (%s) exceeds the available budget (%s) for this budget line.') % (
                        self.amount, self.available_amount
                    ),
                }
            }
