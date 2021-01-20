#
# Casadi algebraic solver class
#
import casadi
import pybamm
import numpy as np


class CasadiAlgebraicSolver(pybamm.BaseSolver):
    """Solve a discretised model which contains only (time independent) algebraic
    equations using CasADi's root finding algorithm.
    Note: this solver could be extended for quasi-static models, or models in
    which the time derivative is manually discretised and results in a (possibly
    nonlinear) algebaric system at each time level.

    Parameters
    ----------
    tol : float, optional
        The tolerance for the solver (default is 1e-6).
    extra_options : dict, optional
        Any options to pass to the CasADi rootfinder.
        Please consult `CasADi documentation <https://tinyurl.com/y7hrxm7d>`_ for
        details.
    sensitivity : str, optional
        Whether (and how) to calculate sensitivities when solving. Options are:

        - None: no sensitivities
        - "explicit forward": explicitly formulate the sensitivity equations. \
        See :class:`pybamm.BaseSolver`
        - "casadi": use casadi to differentiate through the rootfinding operator

    """

    def __init__(self, tol=1e-6, extra_options=None, sensitivity=None):
        super().__init__(sensitivity=sensitivity)
        self.tol = tol
        self.name = "CasADi algebraic solver"
        self.algebraic_solver = True
        self.extra_options = extra_options or {}
        pybamm.citations.register("Andersson2019")

        self.rootfinders = {}
        self.y_sols = {}

    @property
    def tol(self):
        return self._tol

    @tol.setter
    def tol(self, value):
        self._tol = value

    def _integrate(self, model, t_eval, inputs_dict=None):
        """
        Calculate the solution of the algebraic equations through root-finding

        Parameters
        ----------
        model : :class:`pybamm.BaseModel`
            The model whose solution to calculate.
        t_eval : :class:`numpy.array`, size (k,)
            The times at which to compute the solution
        inputs_dict : dict, optional
            Any input parameters to pass to the model when solving. If any input
            parameters that are present in the model are missing from "inputs", then
            the solution will consist of `ProcessedSymbolicVariable` objects, which must
            be provided with inputs to obtain their value.
        """
        # Record whether there are any symbolic inputs
        inputs_dict = inputs_dict or {}
        symbolic_inputs = casadi.vertcat(
            *[v for v in inputs_dict.values() if isinstance(v, casadi.MX)]
        )

        # Create casadi objects for the root-finder
        inputs = casadi.vertcat(*[v for v in inputs_dict.values()])

        y0 = model.y0

        # If y0 already satisfies the tolerance for all t then keep it
        if self.sensitivity != "casadi" and all(
            np.all(abs(model.casadi_algebraic(t, y0, inputs).full()) < self.tol)
            for t in t_eval
        ):
            pybamm.logger.debug("Keeping same solution at all times")
            return pybamm.Solution(
                t_eval, y0, model, inputs_dict, termination="success"
            )

        # The casadi algebraic solver can read rhs equations, but leaves them unchanged
        # i.e. the part of the solution vector that corresponds to the differential
        # equations will be equal to the initial condition provided. This allows this
        # solver to be used for initialising the DAE solvers
        if model.rhs == {}:
            len_rhs = 0
            y0_diff = casadi.DM()
            y0_alg = y0
        else:
            # Check y0 to see if it includes sensitivities
            if model.len_rhs_and_alg == y0.shape[0]:
                len_rhs = model.len_rhs
            else:
                len_rhs = model.len_rhs * (inputs.shape[0] + 1)
            y0_diff = y0[:len_rhs]
            y0_alg = y0[len_rhs:]

        y_alg = None

        if model in self.rootfinders:
            if self.sensitivity == "casadi":
                # Reuse (symbolic) solution with new inputs
                y_sol = self.y_sols[model]
                return pybamm.Solution(
                    t_eval,
                    y_sol,
                    termination="success",
                    model=model,
                    inputs=inputs_dict,
                )
            roots = self.rootfinders[model]
        else:
            # Set up
            t_sym = casadi.MX.sym("t")
            y0_diff_sym = casadi.MX.sym("y0_diff", y0_diff.shape[0])
            y_alg_sym = casadi.MX.sym("y_alg", y0_alg.shape[0])
            y_sym = casadi.vertcat(y0_diff_sym, y_alg_sym)

            t_y0diff_inputs_sym = casadi.vertcat(t_sym, y0_diff_sym, symbolic_inputs)
            alg = model.casadi_algebraic(t_sym, y_sym, symbolic_inputs)

            # Set constraints vector in the casadi format
            # Constrain the unknowns. 0 (default): no constraint on ui, 1: ui >= 0.0,
            # -1: ui <= 0.0, 2: ui > 0.0, -2: ui < 0.0.
            constraints = np.zeros_like(model.bounds[0], dtype=int)
            # If the lower bound is positive then the variable must always be positive
            constraints[model.bounds[0] >= 0] = 1
            # If the upper bound is negative then the variable must always be negative
            constraints[model.bounds[1] <= 0] = -1

            # Set up rootfinder
            roots = casadi.rootfinder(
                "roots",
                "newton",
                dict(x=y_alg_sym, p=t_y0diff_inputs_sym, g=alg),
                {
                    **self.extra_options,
                    "abstol": self.tol,
                    "constraints": list(constraints[len_rhs:]),
                },
            )

            self.rootfinders[model] = roots

        timer = pybamm.Timer()
        integration_time = 0
        for idx, t in enumerate(t_eval):
            # Evaluate algebraic with new t and previous y0, if it's already close
            # enough then keep it
            # We can't do this if also doing sensitivity
            if self.sensitivity != "casadi" and np.all(
                abs(model.casadi_algebraic(t, y0, inputs).full()) < self.tol
            ):
                pybamm.logger.debug(
                    "Keeping same solution at t={}".format(t * model.timescale_eval)
                )
                if y_alg is None:
                    y_alg = y0_alg
                else:
                    y_alg = casadi.horzcat(y_alg, y0_alg)
            # Otherwise calculate new y_sol
            else:
                # If doing sensitivity with casadi, evaluate with symbolic inputs
                # Otherwise, evaluate with actual inputs
                if self.sensitivity == "casadi":
                    t_y0_diff_inputs = casadi.vertcat(t, y0_diff, symbolic_inputs)
                else:
                    t_y0_diff_inputs = casadi.vertcat(t, y0_diff, inputs)
                # Solve
                try:
                    timer.reset()
                    y_alg_sol = roots(y0_alg, t_y0_diff_inputs)
                    integration_time += timer.time()
                    success = True
                    message = None
                    # Check final output
                    y_sol = casadi.vertcat(y0_diff, y_alg_sol)
                    fun = model.casadi_algebraic(t, y_sol, inputs)
                except RuntimeError as err:
                    success = False
                    message = err.args[0]
                    fun = None

                # If there are no symbolic inputs, check the function is below the tol
                # Skip this check if also doing sensitivity
                if success and (
                    self.sensitivity == "casadi"
                    or (not any(np.isnan(fun)) and np.all(casadi.fabs(fun) < self.tol))
                ):
                    # update initial guess for the next iteration
                    y0_alg = y_alg_sol
                    y0 = casadi.vertcat(y0_diff, y0_alg)
                    # update solution array
                    if y_alg is None:
                        y_alg = y_alg_sol
                    else:
                        y_alg = casadi.horzcat(y_alg, y_alg_sol)
                elif not success:
                    raise pybamm.SolverError(
                        "Could not find acceptable solution: {}".format(message)
                    )
                elif any(np.isnan(fun)):
                    raise pybamm.SolverError(
                        "Could not find acceptable solution: solver returned NaNs"
                    )
                else:
                    raise pybamm.SolverError(
                        """
                        Could not find acceptable solution: solver terminated
                        successfully, but maximum solution error ({})
                        above tolerance ({})
                        """.format(
                            casadi.mmax(casadi.fabs(fun)), self.tol
                        )
                    )

        # Concatenate differential part
        y_diff = casadi.horzcat(*[y0_diff] * len(t_eval))
        y_sol = casadi.vertcat(y_diff, y_alg)

        # If doing sensitivity, return the solution as a function of the inputs
        if self.sensitivity == "casadi":
            y_sol = casadi.Function("y_sol", [symbolic_inputs], [y_sol])
            # Save the solution, can just reuse and change the inputs
            self.y_sols[model] = y_sol
        # Return solution object (no events, so pass None to t_event, y_event)
        sol = pybamm.Solution(t_eval, y_sol, model, inputs_dict, termination="success")
        sol.integration_time = integration_time
        return sol
