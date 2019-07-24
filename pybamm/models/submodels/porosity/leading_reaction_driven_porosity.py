#
# Class for leading-order reaction driven porosity changes
#
import pybamm
from .base_porosity import BaseModel


class LeadingOrder(BaseModel):
    """Leading-order model for reaction-driven porosity changes

    Parameters
    ----------
    param : parameter class
        The parameters to use for this submodel


    **Extends:** :class:`pybamm.porosity.BaseModel`
    """

    def __init__(self, param):
        super().__init__(param)

    def get_fundamental_variables(self):

        eps = pybamm.standard_variables.eps_piecewise_constant
        variables = self._get_standard_porosity_variables(eps)
        return variables

    def get_coupled_variables(self, variables):

        j_n = variables["Negative electrode interfacial current density"].orphans[0]
        j_p = variables["Positive electrode interfacial current density"].orphans[0]

        deps_dt_n = pybamm.PrimaryBroadcast(
            -self.param.beta_surf_n * j_n, ["negative electrode"]
        )
        deps_dt_s = pybamm.FullBroadcast(
            0, "separator", auxiliary_domains={"secondary": "current collector"}
        )
        deps_dt_p = pybamm.PrimaryBroadcast(
            -self.param.beta_surf_p * j_p, ["positive electrode"]
        )

        deps_dt = pybamm.Concatenation(deps_dt_n, deps_dt_s, deps_dt_p)

        variables.update(self._get_standard_porosity_change_variables(deps_dt))

        return variables

    def set_rhs(self, variables):
        self.rhs = {}
        for domain in ["negative electrode", "separator", "positive electrode"]:
            eps_av = variables["Average " + domain + " porosity"]
            deps_dt_av = variables["Average " + domain + " porosity change"]
            self.rhs.update({eps_av: deps_dt_av})

    def set_initial_conditions(self, variables):

        eps_n_av = variables["Average negative electrode porosity"]
        eps_s_av = variables["Average separator porosity"]
        eps_p_av = variables["Average positive electrode porosity"]

        self.initial_conditions = {eps_n_av: self.param.eps_n_init}
        self.initial_conditions.update({eps_s_av: self.param.eps_s_init})
        self.initial_conditions.update({eps_p_av: self.param.eps_p_init})
