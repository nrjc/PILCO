import os
import pickle
import re
from typing import List, Tuple
import gin
import numpy as np
from matplotlib import pyplot as plt
import tensorflow as tf
from tf_agents.environments.py_environment import PyEnvironment
from tf_agents.trajectories.trajectory import Trajectory

plt.style.use('seaborn-darkgrid')


class Plotter(object):
    """
    This class plots different graphs for a single epoch from
    a list of trajectories generated by eval
    """

    def __init__(self):
        self.observations = []
        self.rewards = []
        self.actions = []
        self.ratio = []
        self.timesteps = 0

    def __call__(self, trajectories: List[Trajectory], **kwargs) -> None:
        raise NotImplementedError

    def _helper(self, trajectories: List[Trajectory], num_episodes: int = 1) -> None:
        self.trajectories = trajectories
        self.observations = [x.observation for x in trajectories]
        self.rewards = [x.reward for x in trajectories]
        self.actions = [x.action for x in trajectories]
        self.ratio = [x.policy_info for x in trajectories]
        self.timesteps = int(len(self.observations) / num_episodes)

    def traj2obs(self) -> np.ndarray:
        """
        Input:
            trajectories: trajectories from eval
        Output:
            np.ndarray of state observations
        """
        observations = [i.numpy()[0] for i in self.observations]
        observations = np.array(observations[:self.timesteps])
        return observations

    def traj2theta(self, obs_idx: int, acos: bool = False, asin: bool = False) -> np.ndarray:
        """
        Input:
            trajectories: trajectories from eval
            obs_idx: index of the observation corresponding to cosine or sine
        Output:
            np.ndarray of states
        """
        observations = self.traj2obs()
        theta = observations[:self.timesteps, obs_idx]

        assert not (acos and asin), '--- Error: Both acos and asin are True! ---'
        if asin:
            theta = tf.math.asin(theta)
        elif acos:
            theta = tf.math.acos(theta)
        theta = theta / np.pi * 180
        return theta

    def traj2info(self) -> np.ndarray:
        """
        Input:
            trajectories: trajectories from eval
        Output:
            np.ndarray of info/controller ratios
        """
        try:
            ratios = [i.numpy()[0] for i in self.ratio]
        except AttributeError:
            ratios = self.ratio
        ratios = np.array(ratios[:self.timesteps])
        return ratios


@gin.configurable
class StatePlotter(Plotter):
    def __init__(self, env: PyEnvironment):
        super().__init__()
        self.env_name = env.unwrapped.spec.id[:-3]

        # Depending on the env, cos(theta) or state of interest is located at different obs_idx
        if self.env_name == 'Pendulum':
            self.acos = True
            self.asin = False
            self.obs_idx = 0
        elif self.env_name == 'Cartpole':
            self.acos = True
            self.asin = False
            self.obs_idx = 2
        elif self.env_name == 'Mountaincar':
            self.acos = False
            self.asin = False
            self.obs_idx = 0
        else:
            raise Exception('--- Error: Wrong env in StatePlotter ---')

    def __call__(self, trajectories: List[Trajectory], num_episodes: int = 1) -> None:
        super()._helper(trajectories, num_episodes)

        thetas = self.traj2theta(obs_idx=self.obs_idx, acos=self.acos)
        ratios = self.traj2info()

        fig, ax1 = plt.subplots(figsize=(6, 4))

        # Plot theta
        ln1 = ax1.plot(np.arange(self.timesteps), thetas, color='royalblue', label='\u03B8')
        ax1.set_ylim(0, 180)
        ax1.set_xlabel('Timesteps')
        ax1.set_ylabel(f'\u03B8 (\u00B0)')

        # Plot linear ratio
        ax2 = ax1.twinx()
        ln2 = ax2.plot(np.arange(self.timesteps), ratios, color='darkorange', label='Controller Ratio')
        ax2.set_ylim(0.0, 1.0)
        ax2.set_ylabel(f'Linear Controller Ratio')
        ax2.grid(False)

        # Set legend and format
        lns = ln1 + ln2
        labs = [l.get_label() for l in lns]
        ax1.legend(lns, labs, loc=7)
        ax1.set_title(f'\u03B8 and Linear Controller Ratio')
        fig.show()


@gin.configurable
class ControlMetricsPlotter(Plotter):
    def __init__(self, env: PyEnvironment):
        super().__init__()
        self.env_name = env.unwrapped.spec.id[:-3]

        # Depending on the env, sin(theta) or state of interest is located at different obs_idx
        if self.env_name == 'Pendulum':
            self.asin = True
            self.acos = False
            self.obs_idx = 1
        elif self.env_name == 'Cartpole':
            self.asin = True
            self.acos = False
            self.obs_idx = 3
        elif self.env_name == 'Mountaincar':
            self.asin = False
            self.acos = False
            self.obs_idx = 0
        else:
            raise Exception('--- Error: Wrong env in ControlMetricsPlotter ---')

    def __call__(self, trajectories: List[List[Trajectory]], num_episodes: int = 1) -> None:
        fig, ax = plt.subplots(figsize=(6, 4))
        lns, labs = [], []
        colors = ['mediumblue', 'dodgerblue', 'firebrick', 'orange', 'green']
        labels = ['DDPG_baseline', 'DDPG_hybrid', 'PILCO_baseline', 'PILCO_hybrid', 'linear_ctrl']
        j = 0

        for trajectory in trajectories:
            super()._helper(trajectory, num_episodes)
            thetas = self.traj2theta(obs_idx=self.obs_idx, asin=self.asin)

            # Plot theta
            ln = ax.plot(np.arange(self.timesteps), thetas, color=colors[j], label=labels[j])
            lns = lns + ln
            j += 1

        ax.set_xlabel('Timesteps')
        ax.set_ylabel(f'\u03B8 (\u00B0)')

        # Set legend and format
        labs = [l.get_label() for l in lns]
        ax.legend(lns, labs)
        ax.set_title(f'{self.env_name}')
        fig.show()

    def obs2metrics(self, target: List[float], stability_bound: float) -> Tuple[float, int, int]:
        """
        Input:
            trajectories: trajectories from eval
        Output:
            np.ndarray of the control theory metrics
        """
        theta = self.traj2theta(obs_idx=self.obs_idx, asin=self.asin)
        peak_overshot = max(abs(theta)) - target
        rising_time = theta.index(max(theta))

        theta_reverse = theta[::-1]
        upper_stability_bound, lower_stability_bound = target + stability_bound, target - stability_bound
        settling_time = np.argmax(lower_stability_bound < theta_reverse < upper_stability_bound)
        settling_time = len(theta_reverse) - settling_time

        return (peak_overshot, rising_time, settling_time)


class LearningCurvePlotter(object):
    """
    This class plots learning curves for the entire training session from
    a list of np.arrays

    Input:
        rewards: a dictionary of the rewards
        The content of the dictionary should be structured as such:
        dict['controller/env/model'] = [([interaction time for x-axis ... ], [eval rewards for y-axis ... ]) ... ]
        The dictionary can be loaded from a pickle file using the load_pickle function
    """

    def __init__(self, rewards: dict = None, pickle_path: str = None):
        self.rewards = rewards
        self.pickle_path = pickle_path
        if self.pickle_path:
            self.load_pickle()

    def load_pickle(self):
        # load pickle into memory
        if os.path.isfile(self.pickle_path) and os.access(self.pickle_path, os.R_OK):
            # checks if file exists
            with open(self.pickle_path, 'rb') as f:
                self.rewards = pickle.load(f)
        else:
            raise Exception('--- Error: No pickle file found! ---')

    def __call__(self) -> None:
        # Partition the data into lines, each line representing a controller
        lines = self.rewards.keys()
        all = {}
        averages = {}
        best = {}
        worst = {}
        xs = {}

        for key in self.rewards:
            # Put the data for each line into an ndarray. Put this ndarray into dict all.
            xs[key] = np.array(self.rewards[key][0][0])
            all[key] = np.array(self.rewards[key][0][1])
            if len(self.rewards[key]) == 1:
                all[key] = np.expand_dims(all[key], axis=0)
            for i in range(1, len(self.rewards[key])):
                all[key] = np.vstack((all[key], self.rewards[key][i][1]))

            # Compute average, best, worst
            best_reward, worst_reward = np.max(all[key]), np.min(all[key])
            averages[key] = np.mean(all[key], axis=0)
            best[key] = np.max(all[key], axis=0)
            worst[key] = np.min(all[key], axis=0)
            # Standardisation
            averages[key] = (averages[key] - best_reward) / (best_reward - worst_reward) + 1.0
            best[key] = (best[key] - best_reward) / (best_reward - worst_reward) + 1.0
            worst[key] = (worst[key] - best_reward) / (best_reward - worst_reward) + 1.0

        # Plot graph
        titles = ['Pendulum', 'Cartpole', 'Mountaincar']
        regex = [r'controllers/pendulum/.*', r'controllers/cartpole/.*', r'controllers/mountaincar/.*']
        colors = ['mediumblue', 'dodgerblue', 'firebrick', 'orange', 'green']
        total_graphs = 3

        fig, axs = plt.subplots(1, total_graphs, figsize=(15, 5))  #, constrained_layout=True)
        for i in range(total_graphs):
            cur_axis = axs[i]
            j = 0
            for line in lines:
                if re.match(regex[i], line):
                    cur_axis.plot(xs[line], averages[line], color=colors[j], label=line)
                    cur_axis.fill_between(xs[line], worst[line], best[line], alpha=0.5, facecolor=colors[j])
                    j += 1

            cur_axis.set_ylim(0.0, 1.0)
            cur_axis.set_xlabel('Interaction time (s)')
            cur_axis.set_ylabel('Standardised rewards \u00B1 ')
            cur_axis.legend()
            cur_axis.set_title(titles[i])

        plt.show()
