# SECIHTI Budget Planning Module

## Overview

This module provides a graphical interface for planning and simulating how to use remaining budgets in SECIHTI projects. It allows users to create planned expenses and allocate budget from multiple rubros (budget categories) to these expenses without affecting the real budgets.

## Features

- **Budget Simulations**: Create multiple simulation scenarios to plan budget usage
- **Planned Expenses**: Create planned expenses (like post-its) with their costs
- **Budget Allocations**: Connect budget lines (rubros) to expenses with visual allocations
- **Partial Allocation**: Each expense can be funded partially or fully from multiple rubros
- **Simulation Mode**: All changes are simulated and don't affect real budgets
- **Visual Interface**: Kanban and form views provide an intuitive planning experience

## Installation

1. Copy this module to your Odoo addons directory
2. Update the apps list in Odoo
3. Install the "SECIHTI Budget Planning" module

## Dependencies

- `secihti_budget`: The main SECIHTI budget management module

## Usage

### Creating a Budget Simulation

1. Go to **SECIHTI → Simulacion de presupuesto → Mover rubros**
2. Click **Create** to create a new simulation
3. Fill in:
   - **Simulation Name**: A descriptive name for your simulation
   - **Project**: The SECIHTI project you're planning for
   - **Stage** (optional): Filter by a specific stage
   - **Description**: Purpose of this simulation

### Adding Planned Expenses

1. Open a simulation
2. Go to the **Planned Expenses** tab
3. Add expenses with:
   - **Name**: Description of the expense
   - **Amount**: Total cost of the planned expense
   - **Color**: Visual identifier (like post-it colors)

### Allocating Budget to Expenses

1. Open a planned expense
2. Go to the **Allocations** tab
3. Create allocations by selecting:
   - **Activity**: The activity containing the budget
   - **Budget Line (Rubro)**: The specific rubro to allocate from
   - **Amount**: How much to allocate from this rubro

The system will show:
- **Real Remaining**: The actual remaining budget in the budget line
- **Simulated Remaining**: What the remaining would be after this allocation

### Viewing the Planning Interface

1. Open a simulation
2. Click **Open Planning View** button
3. Use the kanban view to see planned expenses like post-its
4. Color-coded badges show allocation status:
   - **Green**: Fully allocated
   - **Yellow**: Partially allocated
   - **Red**: Not allocated or over-allocated

## Data Models

### sec.budget.simulation
- Container for a planning scenario
- Tracks total planned, allocated, and unallocated amounts
- States: Draft, Active, Archived

### sec.planned.expense
- Represents a planned expense (the "post-its")
- Tracks allocation status and percentage
- Can have multiple budget allocations

### sec.budget.allocation
- Connects a budget line to a planned expense (the "red lines")
- Specifies how much budget to allocate
- Shows simulated remaining after allocation

## Important Notes

- **This module is for planning only** - it does NOT modify real budgets
- Multiple simulations can be created for different scenarios
- An expense can be funded from multiple rubros
- The system warns but allows over-allocation in simulation mode for "what if" scenarios

## Menu Structure

```
SECIHTI
└── Simulacion de presupuesto
    ├── Mover rubros (Budget Simulations)
    ├── Gastos Planificados (Planned Expenses)
    └── Asignaciones de Presupuesto (Budget Allocations)
```

## Technical Details

- **Version**: 14.0.1.0.0
- **Category**: Accounting
- **License**: LGPL-3
- **Author**: SECIHTI

## Support

For issues or questions, please contact the SECIHTI development team.
