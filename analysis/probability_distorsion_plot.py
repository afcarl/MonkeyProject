import os
from pylab import np, plt
import json

from analysis.parameters import parameters


"""
Produce the probability distortion figure
"""


class ProbabilityDistortionPlot:

    label_font_size = 20
    ticks_label_size = 14
    line_width = 3

    n_points = 1000

    def __init__(self, monkey, alpha):

        self.alpha = alpha
        self.monkey = monkey
        self.fig_name = self.get_fig_name(monkey)

    def get_fig_name(self, monkey):

        os.makedirs(parameters.folders["figures"], exist_ok=True)

        return "{}/probability_distortion_{}_{:.2f}.pdf".format(
            parameters.folders["figures"], monkey, self.alpha)

    def w(self, p):
        """Probability distortion"""

        return np.exp(-(-np.log(p))**self.alpha)

    def plot(self):

        plt.subplots_adjust(left=0.15, right=0.9, bottom=0.2, top=0.9)

        X = np.linspace(0.001, 1, self.n_points)
        plt.plot(
            X, self.w(X), label=r'$\alpha = {}$'.format(self.alpha),
            color="black", linewidth=self.line_width)

        plt.xlabel('$p$\nMonkey {}.'.format(self.monkey[0]), fontsize=self.label_font_size)
        plt.ylabel('$w(p)$', fontsize=self.label_font_size)

        plt.ylim(0, 1)
        plt.figaspect(1)

        ax = plt.gca()

        ax.spines['right'].set_color('none')
        ax.xaxis.set_ticks_position('bottom')
        ax.yaxis.set_ticks_position('left')
        ax.spines['top'].set_color('none')

        plt.xticks([0, 0.25, 0.5, 0.75, 1], fontsize=self.ticks_label_size)
        plt.yticks([0, 0.25, 0.5, 0.75, 1], fontsize=self.ticks_label_size)

        plt.figaspect(1)

        plt.savefig(self.fig_name)

        plt.close()


def main():

    for monkey in ["Havane", "Gladys"]:

        fit_results = "{}/{}_fit.json".format(parameters.folders["fit"], monkey)
        assert os.path.exists(fit_results), "I could not find the fit data.\n" \
                                            "Did you forgot to run the modeling script(analysis/modelling.py)?"

        # Open the file containing best parameters after fit
        with open(fit_results) as f:
            data = json.load(f)

        pdp = ProbabilityDistortionPlot(monkey=monkey, alpha=data["probability_distortion"])
        pdp.plot()


if __name__ == "__main__":

    main()
