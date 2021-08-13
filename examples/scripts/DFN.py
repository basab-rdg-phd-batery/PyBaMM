#
# Example showing how to load and solve the DFN
#

import pybamm
import numpy as np

pybamm.set_logging_level("INFO")

# load model
model = pybamm.lithium_ion.SPM({"operating mode": "CCCV"})
# create geometry
geometry = model.default_geometry

# load parameter values and process model and geometry
param = pybamm.ParameterValues(chemistry=pybamm.parameter_sets.Mohtat2020)

param["Current function [A]"] = -5
param["Upper voltage cut-off [V]"] = 5
param.update({"CCCV voltage [V]": 4.2}, check_already_exists=False)
param.process_geometry(geometry)
param.process_model(model)

# set mesh
var = pybamm.standard_spatial_vars
var_pts = {var.x_n: 30, var.x_s: 30, var.x_p: 30, var.r_n: 10, var.r_p: 10}
mesh = pybamm.Mesh(geometry, model.default_submesh_types, var_pts)

# discretise model
disc = pybamm.Discretisation(mesh, model.default_spatial_methods)
disc.process_model(model)

# solve model
t_eval = np.linspace(0, 4500, 100)
solver = pybamm.CasadiSolver(mode="safe", atol=1e-6, rtol=1e-3)
solution = solver.solve(model, t_eval)

# plot
plot = pybamm.QuickPlot(
    solution,
    [
        # "Negative particle concentration [mol.m-3]",
        # "Electrolyte concentration [mol.m-3]",
        # "Positive particle concentration [mol.m-3]",
        "Current [A]",
        ["Current density variable", "Total current density"],
        "dIdt",
        "dIdt_I",
        "dIdt_V",
        # "Negative electrode potential [V]",
        # "Electrolyte potential [V]",
        # "Positive electrode potential [V]",
        "Terminal voltage [V]",
    ],
    time_unit="seconds",
    spatial_unit="um",
)
plot.dynamic_plot()
