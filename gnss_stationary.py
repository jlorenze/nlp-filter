import numpy as np
import matplotlib.pyplot as plt
import nlp.nlp as nlp
import nlp.dynamics as dynamics
import nlp.cost_functions as cost_functions
import nlp.constraints as constraints
import nlp.simulate as simulate
import nlp.measurements as measurements
from scipy.io import loadmat
import utils.gnss as gnss
import utils.utils as utils
import utils.ekf as ekf
import pdb

C = 299792458 # speed of light in m/s

Q = np.diag([0.0001, 0.0001, 0.0001, 0.1, 0.001]) # covariance for dynamics
r_pr = 100 # covariance for pseudorange measurement
r_bias = 0.001

# Reference location on Earth (Hoover Tower)
lat0 = 37.4276
lon0 = -122.1670
h0 = 0
p_ref_ECEF = utils.lla2ecef(np.array([lat0, lon0, h0]))

# Assuming data sampled a 1 Hz
dt = 1
T = 50
t = np.linspace(0, T, T + 1)
u = np.zeros((3, T + 1))

sat_data = loadmat('../data/onyx/gnss_log_2020_02_05_09_14_15onyxsatposecef.mat')
sat_pos = sat_data["svPoss"][1:,:,:3] # ECEF coordinates (meters)
ion_correction = sat_data["svPoss"][1:,:,3] # meters
sat_clock_bias = sat_data["svPoss"][1:,:,4] # seconds

# Load data and correct for ionosphere and satellite clock bias
pr_data = loadmat('../data/onyx/gnss_log_2020_02_05_09_14_15onyxranges.mat')
pr = pr_data["pseudoranges"][1:,:] + ion_correction + C*sat_clock_bias
sats = pr_data["pseudoranges"][0,:]


# Compute iterative least squares solutions
LS = {"t":t, "p_ref_ECEF":p_ref_ECEF, "bias":np.zeros(T+1),
      "x_ENU":np.zeros(T+1), "y_ENU":np.zeros(T+1), "z_ENU":np.zeros(T+1),
      "lat":np.zeros(T+1), "lon":np.zeros(T+1), "h":np.zeros(T+1)}
p = pr.shape[1]
for k in range(T+1):
    # Only take measurements that are not NaN
    sat_pos_k = np.array([]).reshape(0,3)
    pr_k = np.array([])
    for i in range(p):
        if not np.all(sat_pos[k,i,:] == 0.0) and not np.isnan(pr[k,i]):
            sat_pos_k = np.vstack((sat_pos_k, sat_pos[k,i,:].reshape((1,3))))
            pr_k = np.hstack((pr_k, pr[k,i]))

    # Solve least squares
    p_ECEF, b = gnss.iterativeLeastSquares(sat_pos_k, pr_k)
    p_ENU = utils.ecef2enu(p_ECEF, p_ref_ECEF)
    p_LLA = utils.ecef2lla(p_ECEF)
    LS["x_ENU"][k] = p_ENU[0]
    LS["y_ENU"][k] = p_ENU[1]
    LS["z_ENU"][k] = p_ENU[2]
    LS["lat"][k] = p_LLA[0]
    LS["lon"][k] = p_LLA[0]
    LS["h"][k] = p_LLA[0]
    LS["bias"][k] = b


# Compute iterative least squares using all measurements in a batch
p = pr.shape[1]

sat_pos_batch = np.array([]).reshape(0,3)
pr_batch = np.array([])
t_batch = np.array([])
for k in range(T+1):
    # Only take measurements that are not NaN
    for i in range(p):
        if not np.all(sat_pos[k,i,:] == 0.0) and not np.isnan(pr[k,i]):
            sat_pos_batch = np.vstack((sat_pos_batch, sat_pos[k,i,:].reshape((1,3))))
            pr_batch = np.hstack((pr_batch, pr[k,i]))
            t_batch = np.hstack((t_batch, t[k]))

# Solve batch least squares 
p_ECEF, b0, alpha = gnss.iterativeLeastSquares_multiTimeStep(t_batch, sat_pos_batch, pr_batch)
p_ENU = utils.ecef2enu(p_ECEF, p_ref_ECEF)
p_LLA = utils.ecef2lla(p_ECEF)
LS_batch = {"t":t, "p_ref_ECEF":p_ref_ECEF,
      "x_ENU":p_ENU[0], "y_ENU":p_ENU[1], "z_ENU":p_ENU[2],
      "lat":p_LLA[0], "lon":p_LLA[1], "h":p_LLA[2]}


# Compute using EKF
# Data storage dictionary
EKF = {"t":t, "p_ref_ECEF":p_ref_ECEF, "bias":np.zeros(T+1),
      "x_ENU":np.zeros(T+1), "y_ENU":np.zeros(T+1), "z_ENU":np.zeros(T+1),
      "lat":np.zeros(T+1), "lon":np.zeros(T+1), "h":np.zeros(T+1)}

# Create EKF object
bias_rate_guess = (LS["bias"][-1] - LS["bias"][0])/T
xhat0 = np.array([LS["x_ENU"][0], LS["y_ENU"][0], LS["z_ENU"][0], LS["bias"][0], bias_rate_guess]) # initialize estimate using Least squares solution
P0 = np.diag([1, 1, 1, 1, 1]) # initialize covariance
ekf_filter = ekf.EKF(gnss.gnss_pos_and_bias, gnss.multi_pseudorange, xhat0, P0)

# Run EKF
for k in range(T):
    EKF["x_ENU"][k] = ekf_filter.mu[0]
    EKF["y_ENU"][k] = ekf_filter.mu[1]
    EKF["z_ENU"][k] = ekf_filter.mu[2]
    EKF["bias"][k] = ekf_filter.mu[3]

    # Only take measurements that are not NaN (at time k+1)
    sat_pos_k = np.array([]).reshape(0,3)
    pr_k = np.array([])
    for i in range(p):
        if not np.all(sat_pos[k+1,i,:] == 0.0) and not np.isnan(pr[k+1,i]):
            sat_pos_ENU = utils.ecef2enu(np.array([sat_pos[k+1, i, 0], sat_pos[k+1, i, 1], sat_pos[k+1, i, 2]]), p_ref_ECEF)
            sat_pos_k = np.vstack((sat_pos_k, sat_pos_ENU.reshape((1,3))))
            pr_k = np.hstack((pr_k, pr[k+1,i]))

    # Update EKF using measurement and control from next time step
    R = np.diag(r_pr*np.ones(pr_k.shape[0]))
    ekf_filter.update(u[:,k+1], pr_k, Q, R, dyn_func_params={"dt":dt}, meas_func_params={"sat_pos":sat_pos_k})

EKF["x_ENU"][-1] = ekf_filter.mu[0]
EKF["y_ENU"][-1] = ekf_filter.mu[1]
EKF["z_ENU"][-1] = ekf_filter.mu[2]
EKF["bias"][-1] = ekf_filter.mu[3]

# TODO: initialize optimizer
# Time horizon
N = 10
n = 5
m = 3

problem = nlp.fixedTimeOptimalEstimationNLP(N, T, n, m)

# Define variables
X = problem.addVariables(N+1, n, name='x')

# Define system dynamics
problem.addDynamics(dynamics.gnss_pos_and_bias, X, t, u, np.linalg.inv(Q))

# Define cost function, adding measurements individually
for k in range(T+1):
    for (i, sat) in enumerate(sats):
        if not np.isnan(pr[k, i]):
            sat_pos_ENU = utils.ecef2enu(np.array([sat_pos[k, i, 0], sat_pos[k, i, 1], sat_pos[k, i, 2]]), p_ref_ECEF)
            params = {"sat_pos": sat_pos_ENU}
            R = np.diag([r_pr])
            y = np.array([[pr[k, i]]])
            tk = np.array([[t[k]]])
            problem.addResidualCost(measurements.pseudorange, X, tk, y, np.linalg.inv(R), params)

# Solve problem
print('Building problem.')
problem.build()

print('Solving problem.')
problem.solve()

NLP = {"t":t, "p_ref_ECEF":p_ref_ECEF, "bias":np.zeros(T+1),
      "x_ENU":np.zeros(T+1), "y_ENU":np.zeros(T+1), "z_ENU":np.zeros(T+1),
      "lat":np.zeros(T+1), "lon":np.zeros(T+1), "h":np.zeros(T+1)}
x_opt = problem.extractSolution('x', t)
for k in range(T+1):
    p_ENU = np.array([x_opt[k, 0], x_opt[k, 1], x_opt[k, 2]])
    p_ECEF = utils.enu2ecef(p_ENU, p_ref_ECEF)
    p_LLA = utils.ecef2lla(p_ECEF)
    NLP["x_ENU"][k] = p_ENU[0]
    NLP["y_ENU"][k] = p_ENU[1]
    NLP["z_ENU"][k] = p_ENU[2]
    NLP["lat"][k] = p_LLA[0]
    NLP["lon"][k] = p_LLA[0]
    NLP["h"][k] = p_LLA[0]
    NLP["bias"][k] = x_opt[k,3]





# Plotting
plt.figure(1)
plt.scatter(LS["x_ENU"], LS["y_ENU"], c='r', marker='x', label='LS')
plt.scatter(LS_batch["x_ENU"], LS_batch["y_ENU"], c='k', marker='s', label='Batch LS')
plt.scatter(EKF["x_ENU"], EKF["y_ENU"], c='g', marker='d', label='EKF')
plt.scatter(NLP["x_ENU"], NLP["y_ENU"], c='b', marker='o', label='NLP')
plt.xlabel('x (m)')
plt.ylabel('y (m)')
plt.legend()

plt.figure(2)
plt.plot(LS["t"], LS["x_ENU"], c='r', label='x (LS)')
plt.plot(LS_batch["t"], LS_batch["x_ENU"]*np.ones(T+1), c='k', label='x (Batch LS)')
plt.plot(EKF["t"], EKF["x_ENU"], c='g', label='x (EKF)')
plt.plot(NLP["t"], NLP["x_ENU"], c='b', label='x (NLP)')
plt.xlabel('t (s)')
plt.ylabel('x (m)')
plt.legend()

plt.figure(3)
plt.plot(LS["t"], LS["y_ENU"], c='r', label='y (LS)')
plt.plot(LS_batch["t"], LS_batch["y_ENU"]*np.ones(T+1), c='k', label='y (Batch LS)')
plt.plot(EKF["t"], EKF["y_ENU"], c='g', label='y (EKF)')
plt.plot(NLP["t"], NLP["y_ENU"], c='b', label='y (NLP)')
plt.xlabel('t (s)')
plt.ylabel('y (m)')
plt.legend()

# plt.figure(4)
# plt.plot(LS["t"], LS["bias"], c='r', label='LS')
# plt.plot(EKF["t"], EKF["bias"], c='g', label='EKF')
# plt.plot(NLP["t"], NLP["bias"], c='b', label='NLP')
# plt.legend()
plt.show()



