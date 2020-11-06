# Set metas for the entire experiment/run
import numpy as np
import gpflow

gpflow.config.set_default_float(np.float64)

import tensorflow as tf
tf.compat.v1.logging.set_verbosity(tf.compat.v1.logging.ERROR)

import gin

# Import relevant local modules
import dao.envs
from dao.envloader import load_py_env
from dao.trainer import PILCOTrainer, DDPGTrainer, Visualiser

gin.parse_config_file('config.gin')
# %%
# ddpg_trainer = DDPGTrainer()
# # %%
# ddpg_trainer.train()
# #%%
visualizer = Visualiser()
#%%
visualizer(500)
#%%


# # Load and test control metrics
# pilco_trainer = PILCOTrainer()