import itertools as it
from os import makedirs, path
import tqdm

import numpy as np
import json
from scipy.stats import binom

from analysis.tools.model import ProspectTheoryModel

from data_management.data_manager import import_data

from utils.utils import log


"""
Get best parameters from data [necessary in order to produce result figures]

"""


class ModelRunner(object):

    name = "ModelRunner"

    alternatives = None

    parameters_list = None
    n_set_parameters = None

    p_list = None

    @classmethod
    def prepare(cls, alternatives, range_parameters, n_values_per_parameter):

        cls.alternatives = alternatives

        cls.prepare_parameters_list(
            range_parameters=range_parameters,
            n_values_per_parameter=n_values_per_parameter
        )

    @classmethod
    def prepare_parameters_list(cls, range_parameters, n_values_per_parameter):
        
        assert sorted(range_parameters.keys()) == ProspectTheoryModel.labels
        
        possible_parameter_values = \
            {k: np.linspace(v[0], v[1], n_values_per_parameter) 
             for k, v in range_parameters.items()}

        cls.n_set_parameters = n_values_per_parameter ** len(possible_parameter_values)
        cls.parameters_list = [possible_parameter_values[i] for i in sorted(possible_parameter_values.keys())]

    @classmethod
    def compute(cls, parameters):

        ps = np.zeros(len(cls.alternatives))
        model = ProspectTheoryModel(parameters)

        for i, (l1, l2) in enumerate(cls.alternatives):

            ps[i] = model.get_p(l1, l2)

        return ps

    @classmethod
    def run(cls, alternatives, range_parameters, n_values_per_parameter):

        cls.prepare(
            alternatives=alternatives, 
            range_parameters=range_parameters, 
            n_values_per_parameter=n_values_per_parameter)

        log("Run the model...", cls.name)

        log("Number of different sets of parameters: {}.".format(cls.n_set_parameters), cls.name)

        cls.p_list = []

        for i, parameters in tqdm.tqdm(enumerate(it.product(*cls.parameters_list)), total=cls.n_set_parameters):
            cls.p_list.append(cls.compute(parameters))

        cls.p_list = np.array(cls.p_list)

        log("Done!", cls.name)


class LlsComputer(object):

    name = "LlsComputer"
    k = None
    n = None
    p = None

    @classmethod
    def prepare(cls, k, n, p):

        cls.k = k
        cls.n = n
        cls.p = p

    @classmethod
    def run(cls):

        log("Compute log-likelihoods...", cls.name)

        assert len(cls.k) == len(cls.n) == len(cls.p[0, :]), \
            "len k: {}; len n: {}; len p: {}.".format(
                len(cls.k), len(cls.n), len(cls.p[0, :]))

        n_sets = len(cls.p[:, 0])
        len_n = len(cls.n)

        lls_list = np.zeros(n_sets)

        for i in tqdm.tqdm(range(n_sets)):
            log_likelihood_sum = 0

            for j in range(len_n):
                k, n, p = cls.k[j], cls.n[j], cls.p[i, j]

                log_likelihood = binom.logpmf(k=k, n=n, p=p)
                if log_likelihood == -np.inf:
                    log_likelihood_sum = - np.inf
                    break

                log_likelihood_sum += log_likelihood

            lls_list[i] = log_likelihood_sum

        log("Done!", cls.name)

        return lls_list


class AlternativesNKGetter(object):

    def __init__(self, data):

        self.data = data

    def run(self):

        results = {}

        n_trials = len(self.data["p"]["left"])

        for t in range(n_trials):

            alternative = (
                (self.data["p"]["left"][t], self.data["x0"]["left"][t]),
                (self.data["p"]["right"][t], self.data["x0"]["right"][t])
            )

            reversed_alternative = alternative[::-1]

            reverse = False
            if alternative not in results.keys():
                if reversed_alternative not in results.keys():
                    results[alternative] = {"n": 0, "k": 0}
                else:
                    reverse = True

            if reverse:
                results[reversed_alternative]["n"] += 1
                results[reversed_alternative]["k"] += int(self.data["choice"][t] == "right")
            else:
                results[alternative]["n"] += 1
                results[alternative]["k"] += int(self.data["choice"][t] == "left")

        alternatives, n, k = [], [], []

        idx = 0
        for i, j in results.items():

            alternatives.append(i), n.append(j["n"]), k.append(j["k"])

            idx += 1

        return alternatives, n, k


def get_model_data(npy, alternatives, 
                   range_parameters,
                   n_values_per_parameter,
                   force=False):

    if all([path.exists(file) for file in npy.values()]) and not force:

        parameters_it = np.load(npy["parameters"])
        p = np.load(npy["p"])

        return parameters_it, p

    else:

        m = ModelRunner()
        m.run(alternatives=alternatives,
              range_parameters=range_parameters,
              n_values_per_parameter=n_values_per_parameter)

        try:
            np.save(npy["parameters"], m.parameters_list)
            np.save(npy["p"], m.p_list)

        except Exception as e:
            log("Could not save: {}".format(e))

        return m.parameters_list, m.p_list


def get_monkey_data(monkey, npy, starting_point, end_point, database_path=None, force=False):

    if all([path.exists(file) for file in npy.values()]) and not force:

        alternatives = np.load(npy["alternatives"])
        n = np.load(npy["n"])
        k = np.load(npy["k"])

    else:

        data = \
            import_data(monkey=monkey, starting_point=starting_point, end_point=end_point, database_path=database_path)

        alternatives_n_k_getter = AlternativesNKGetter(data)
        alternatives, n, k = alternatives_n_k_getter.run()

        try:
            np.save(npy["n"], n)
            np.save(npy["k"], k)
            np.save(npy["alternatives"], alternatives)
        except Exception as e:
            print("Could not save: {}".format(e))

    return alternatives, n, k


def get_lls(n, k, p, npy_file, force=False):

    if path.exists(npy_file) and not force:

        lls = np.load(npy_file)

    else:

        lls_computer = LlsComputer()
        lls_computer.prepare(k=k, n=n, p=p)
        lls = lls_computer.run()

        try:
            np.save(npy_file, lls)
        except Exception as e:
            print("Could not save: {}".format(e))
    return lls


def treat_results(monkey, lls_list, parameters, json_file):

    arg = np.argmax(lls_list)

    best_parameters = None
    for i, param in enumerate(it.product(*parameters)):
        if i == arg:
            best_parameters = param
            break

    msg = "{}: ".format(monkey) + \
        "".join(["{}: {:.2f}; ".format(k, v) for k, v in zip(sorted(ProspectTheoryModel.labels), best_parameters)])
    log(msg, name="modelling.treat_results")

    result = dict([(k, v) for k, v in zip(sorted(ProspectTheoryModel.labels), best_parameters)])
    with open(json_file, "w") as file:
        json.dump(result, file)


def main(force=False):

    from analysis.parameters import \
        folders, range_parameters, n_values_per_parameter, starting_points, end_point, database_path

    for folder in folders.values():
        makedirs(folder, exist_ok=True)

    files = dict()
    files["model"] = {
        "p": "{}/{}.npy".format(folders["npy"], "model_p"),
        "parameters": "{}/{}.npy".format(folders["npy"], "model_parameters")
    }

    for monkey in ["Havane", "Gladys"]:

        files[monkey] = {
            "data": {
                "alternatives": "{}/{}_{}.npy".format(folders["npy"], monkey, "alternatives"),
                "n": "{}/{}_{}.npy".format(folders["npy"], monkey, "n"),
                "k": "{}/{}_{}.npy".format(folders["npy"], monkey, "k"),
            },
            "LLS": "{}/{}_{}.npy".format(folders["npy"], monkey, "lls"),
            "fit": "{}/{}_{}.json".format(folders["fit"], monkey, "fit")  # What will be used for producing figures
        }

    monkeys = ["Gladys", "Havane"]

    for monkey in monkeys:

        starting_point = starting_points[monkey]

        log("Processing for {}...".format(monkey), name="modelling.__main__")

        log("Getting experimental data for {}...".format(monkey), name="modelling.__main__")
        alternatives, n, k = get_monkey_data(
            monkey=monkey, starting_point=starting_point, end_point=end_point,
            database_path=database_path,
            npy=files[monkey]["data"], force=force)

        log("Getting model predictions for {}...".format(monkey), name="modelling.__main__")
        parameters, p = \
            get_model_data(
                range_parameters=range_parameters,
                n_values_per_parameter=n_values_per_parameter,           
                npy=files["model"], alternatives=alternatives, force=True)

        log("Getting the best parameters for {}...".format(monkey), name="modelling.__main__")
        lls_list = get_lls(
            k=k,
            n=n,
            p=p,
            npy_file=files[monkey]["LLS"], force=force)

        treat_results(
            monkey=monkey, lls_list=lls_list, parameters=parameters,
            json_file=files[monkey]["fit"])

        log("Done!", name="modelling.__main__")


if __name__ == "__main__":

    main()
