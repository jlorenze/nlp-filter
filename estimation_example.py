import numpy as np
import matplotlib.pyplot as plt
import utils.nlp as nlp
import utils.dynamics as dynamics
import utils.cost_functions as cost_functions
import utils.constraints as constraints
import utils.simulate as simulate
import utils.measurements as measurements
import pdb

T = 10.


# Simulate open loop sequence
t = np.linspace(0, T, 50)
ux = np.sin(t)
uy = np.cos(t)
u = np.vstack((ux, uy))
x0 = np.zeros(2)
x = simulate.open_loop_sim(t, u, x0, dynamics.single_integrator_2D)

R = np.diag([0.01, 0.02]) # covariance matrix
y = simulate.generate_measurements(x, measurements.full_state, R)

# plt.figure()
# plt.plot(x[0,:], x[1,:], label='x')
# plt.plot(y[0,:], x[1,:], '.', label='y')
# plt.legend()
# plt.show()

# Time horizon
N = 20
n = 2
m = 2

problem = nlp.fixedTimeOptimalEstimationNLP(N, T, n, m)

# Define variables
X = problem.addVariables(N+1, 2, name='x')

# Define system dynamics
Q = np.diag([0.0001, 0.0001])
problem.addDynamics(dynamics.single_integrator_2D, X, t, u, np.linalg.inv(Q))

# Define cost function
problem.addResidualCost(measurements.full_state, X, t, y, np.linalg.inv(R))

# Solve problem
problem.build()
problem.solve()

x_opt = problem.extractSolution('x', t)

plt.figure(1)
plt.plot(x[0,:], x[1,:], label='x')
plt.plot(x_opt[:,0], x_opt[:,1], '--', label='xhat')
plt.plot(y[0,:], y[1,:], '.', label='y')
plt.xlabel('t')
plt.legend()
plt.show()



