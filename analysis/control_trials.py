from pylab import np, plt
from os import makedirs

from utils.utils import log
from data_management.data_manager import import_data

from analysis.parameters import parameters
from analysis.tools.backup import Backup


"""
Produce the control trials figure
"""


def get_script_name():

    return __file__.split("/")[-1].split(".py")[0]


class Analyst:

    control_conditions = [
        "identical p, positive vs negative x0",
        "identical p, positive x0",
        "identical p, negative x0",
        "identical x, positive x0",
        "identical x, negative x0"
    ]

    name = "Analyst 'control trials'"

    def __init__(self, data, fig_name="figure.pdf", monkey=""):

        self.data = data
        self.fig_name = fig_name
        self.monkey = monkey

        self.sorted_data = None
        self.results = None
        self.n_trials = None

    def is_trial_with_losses_only(self, t):
        return self.data["x0"]["left"][t] < 0 and self.data["x0"]["right"][t] < 0

    def is_trial_with_gains_only(self, t):
        return self.data["x0"]["left"][t] > 0 and self.data["x0"]["right"][t] > 0

    def is_trial_with_fixed_p(self, t):

        return self.data["p"]["left"][t] == self.data["p"]["right"][t]

    def is_trial_with_fixed_x(self, t):

        return self.data["x0"]["left"][t] == self.data["x0"]["right"][t]

    def is_trial_with_best_option_on_left(self, t, condition):

        if condition in \
                ("identical p, positive vs negative x0",
                 "identical p, negative x0",
                 "identical p, positive x0"):
            return self.data["x0"]["left"][t] > self.data["x0"]["right"][t]

        elif condition == "identical x, negative x0":
            return self.data["p"]["left"][t] < self.data["p"]["right"][t]

        elif condition == "identical x, positive x0":
            return self.data["p"]["left"][t] > self.data["p"]["right"][t]

        else:
            raise Exception("Condition not understood.")

    def is_trial_a_hit(self, t, best_option):

        return self.data["choice"][t] == best_option

    def get_best_option(self, t, condition):

        best_is_left = self.is_trial_with_best_option_on_left(t, condition)
        return "left" if best_is_left else "right"

    def get_alternative(self, t, best_option):

        not_best_option = "left" if best_option != "left" else "right"
        alternative = (
            (self.data["p"][best_option][t], self.data["x0"][best_option][t]),
            (self.data["p"][not_best_option][t], self.data["x0"][not_best_option][t])
        )

        return alternative

    def which_type_of_control(self, t):

        type_of_control = None

        if self.is_trial_with_fixed_p(t):

            if self.is_trial_with_gains_only(t):
                type_of_control = "identical p, positive x0"

            elif self.is_trial_with_losses_only(t):
                type_of_control = "identical p, negative x0"

            else:
                type_of_control = "identical p, positive vs negative x0"

        elif self.is_trial_with_fixed_x(t):

            if self.is_trial_with_gains_only(t):
                type_of_control = "identical x, positive x0"

            elif self.is_trial_with_losses_only(t):
                type_of_control = "identical x, negative x0"

            else:
                raise Exception("Revise your logic!")

        return type_of_control

    def sort_data(self):

        self.sorted_data = {i: {} for i in self.control_conditions}

        self.n_trials = len(self.data["p"]["left"])

        for t in range(self.n_trials):
            control_type = self.which_type_of_control(t)

            if control_type is None:
                continue

            best_option = self.get_best_option(t, control_type)
            is_a_hit = self.is_trial_a_hit(t, best_option)
            alternative = self.get_alternative(t, best_option)

            if alternative not in self.sorted_data[control_type].keys():
                self.sorted_data[control_type][alternative] = []

            self.sorted_data[control_type][alternative].append(is_a_hit)

    def get_results(self):

        self.results = {i: {} for i in self.control_conditions}

        for cond in self.control_conditions:

            log("Condition '{}'.".format(cond), self.name)

            data = self.sorted_data[cond]
            alternatives = sorted(list(data.keys()))

            n_trials = []
            means = []

            for i, alt in enumerate(alternatives):
                n = len(data[alt])
                mean = np.mean(data[alt])
                n_trials.append(n)

                self.results[cond][alt] = mean

                means.append(mean)

                log("{} {}: mean {}, n {}".format(i, alt, mean, n), self.name)

            # noinspection PyTypeChecker
            perc_75, perc_25 = np.percentile(means, [75, 25])

            log("Number of pairs of lotteries: {}".format(len(n_trials)), self.name)
            
            log("The median of frequencies for {}: {:.02f} (IQR = {:.02f} -- {:.02f})"
                .format(cond, np.median(means), perc_25, perc_75), self.name)
            
            log("A few other stats about the number of trials for a specific pair", self.name)

            log("Min: {}".format(np.min(n_trials)), self.name)
            log("Max: {}".format(np.max(n_trials)), self.name)
            log("Median: {}".format(np.median(n_trials)), self.name)
            log("Mean: {}".format(np.mean(n_trials)), self.name)
            log("Std: {}".format(np.std(n_trials)), self.name)
            log("Sum: {}".format(np.sum(n_trials)), self.name)

    def plot(self):

        fig, ax = plt.subplots()

        n = len(self.control_conditions)

        names = ["Loss\nvs\ngains", "Diff. $x_0$ +\nSame p", "Diff. $x_0$ -\nSame p",
                 "Diff. p\nSame $x_0$ +", "Diff. p\nSame $x_0$ -"]

        colors = ["black", "C0", "C1", "C0", "C1"]
        positions = list(range(n))

        x_scatter = []
        y_scatter = []
        colors_scatter = []

        values_box_plot = []

        for i, cond in enumerate(self.control_conditions):

            values_box_plot.append([])

            for v in self.results[cond].values():

                # For box plot
                values_box_plot[-1].append(v)

                # For scatter
                y_scatter.append(v)
                x_scatter.append(i)
                colors_scatter.append(colors[i])

        fontsize = 10

        ax.scatter(x_scatter, y_scatter, c=colors_scatter, s=30, alpha=1, linewidth=0.0, zorder=2)

        plt.xticks(positions, names, fontsize=fontsize)
        plt.xlabel("Type of control\nMonkey {}.".format(self.monkey[0]), fontsize=fontsize)

        plt.yticks(np.arange(0.4, 1.1, 0.2), fontsize=fontsize)
        plt.ylabel("Success rate", fontsize=fontsize)
        ax.set_ylim(0.35, 1.02)

        # Boxplot
        bp = ax.boxplot(values_box_plot, positions=positions, labels=names, showfliers=False, zorder=1)

        for median in bp['medians']:
            median.set(color="black")
            median.set_alpha(0.5)

        for e in ['boxes', 'caps', 'whiskers']:
            for b in bp[e]:
                b.set_alpha(0.5)

        ax.set_aspect(3)
        # plt.legend()

        plt.tight_layout()

        plt.savefig(fname=self.fig_name)
        plt.close()

    def run(self):

        self.sort_data()
        self.get_results()
        self.plot()


def main(force=False):

    makedirs(parameters.folders["figures"], exist_ok=True)

    for monkey in ["Havane", "Gladys"]:

        log(monkey, name="control_trials.__main__")

        starting_point = parameters.starting_points[monkey]

        b = Backup(monkey, kind_of_analysis="data", folder=parameters.folders["pickle"])
        data = b.load()

        fig_name = "{}/{}_{}.pdf" \
            .format(parameters.folders["figures"], monkey, get_script_name())

        if force is True or data is None:

            data = import_data(monkey=monkey, starting_point=starting_point, end_point=parameters.end_point,
                               database_path=parameters.database_path)
            b.save(data)

        analyst = Analyst(data=data, fig_name=fig_name, monkey=monkey)
        analyst.run()


if __name__ == "__main__":
    main()
