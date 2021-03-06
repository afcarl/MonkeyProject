import numpy as np
from pylab import plt

"""
Demo for fitting data with a sigmoid function
"""


from scipy.optimize import curve_fit


def sigmoid(x, x0, k):

    y = 1 / (1 + np.exp(-k*(x-x0)))
    return y


xdata = np.array([0.0, 0.0, 1.0, 3.0, 4.3, 7.0, 8.0, 8.5, 10.0, 12.0])
ydata = np.array([0.01, 0.02, 0.02, 0.04, 0.11, 0.43,  0.7, 0.89, 0.95, 0.99])

popt, pcov = curve_fit(sigmoid, xdata, ydata)

x = np.linspace(-1, 15, 50)
y = sigmoid(x, *popt)

plt.plot(xdata, ydata, 'o', label='data')
plt.plot(x, y, label='fit')
plt.ylim(0, 1.05)
plt.legend(loc='best')
plt.show()
