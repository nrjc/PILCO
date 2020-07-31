import unittest
from typing import List

import numpy as np
import gym

from pilco.controller_utils import LQR
from pilco.controllers import CombinedController, LinearController
from pilco.noise_robust_analysis import percentage_stable, analyze_robustness
from utils import load_controller_from_obj


class myPendulum():
    def __init__(self, initialize_top=False):
        self.env = gym.make('Pendulum-v0').env
        self.action_space = self.env.action_space
        self.observation_space = self.env.observation_space
        self.observation_space_dim = self.observation_space.shape[0]
        self.up = initialize_top

    def step(self, action):
        return self.env.step(action)

    def reset(self):
        if self.up:
            self.env.state = [np.pi / 180, 0]
        else:
            self.env.state = [np.pi, 0]
        self.env.last_u = None
        return self.env._get_obs()

    def render(self):
        self.env.render()

    def close(self):
        self.env.close()

    def mutate_with_noise(self, noise_mag, arg_names: List[str]):
        for k in arg_names:
            self.env.__dict__[k] = self.env.__dict__[k] * (1 + np.random.uniform(-noise_mag, noise_mag))

    def control(self):
        # m := mass of pendulum
        # l := length of pendulum from end to centre
        # b := coefficient of friction of pendulum
        b = 0
        g = self.env.g
        m = self.env.m
        l = self.env.l / 2
        I = 1 / 3 * m * (l ** 2)
        p = m * (l ** 2) + I

        # using x to approximate sin(x)
        A = np.array([[0, 1],
                      [m * l * g / p, -b / p]])

        B = np.array([[0],
                      [-1 / p]])

        C = np.array([[1, 0]])

        Q = np.diag([2.0, 2.0])

        return A, B, C, Q


class TestRobustNess(unittest.TestCase):
    def setUp(self):
        bf = 30
        max_action = 2.0
        target = np.array([1.0, 0.0, 0.0])

        # Set up objects and variables
        env = myPendulum(True)
        A, B, C, Q = env.control()
        W_matrix = LQR().get_W_matrix(A, B, Q, env='swing up')

        state_dim = 3
        control_dim = 1

        self.controller = CombinedController(state_dim=state_dim, control_dim=control_dim, num_basis_functions=bf,
                                             controller_location=target, W=W_matrix, max_action=max_action)
        self.lin_controller = LinearController(state_dim=state_dim, control_dim=control_dim, W=W_matrix,
                                         max_action=max_action)
        self.rbf_controller = load_controller_from_obj('data/swingup/rbf/swingup_rbf_controller4.pkl')
        self.env = env

    def test_percentage_stable(self):
        percentage_stable(self.controller, self.env, [(0.5, 1.2), (-np.pi / 4, np.pi / 4), (-1, 1)], ['g', 'm', 'l'], 0.2)

    def test_stable_across_noise(self):
        p_extended = analyze_robustness(self.controller, self.env, [(0.5, 1.2), (-.0192, .0192), (-1, 1)], ['g', 'm', 'l'],
                          np.asarray([0.1, 0.3, 0.5, 0.7, 1.0]))
        p_linear = analyze_robustness(self.lin_controller, self.env, [(0.5, 1.2), (-.0192, .0192), (-1, 1)], ['g', 'm', 'l'],
                          np.asarray([0.1, 0.3, 0.5, 0.7, 1.0]))
        p_rbf = analyze_robustness(self.rbf_controller, self.env, [(0.5, 1.2), (-.0192, .0192), (-1, 1)], ['g', 'm', 'l'],
                          np.asarray([0.1, 0.3, 0.5, 0.7, 1.0]))
        pass

if __name__ == '__main__':
    unittest.main()
