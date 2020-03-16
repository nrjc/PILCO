import tensorflow as tf
import numpy as np
import gpflow
from .models import MGPR
from gpflow import settings, transforms
import math
import control

from .transforms import Squeeze

float_type = settings.dtypes.float_type


def squash_sin(m, s, max_action=None):
    '''
    Squashing function, passing the controls mean and variance
    through a sinus, as in gSin.m. The output is in [-max_action, max_action].
    IN: mean (m) and variance(s) of the control input, max_action
    OUT: mean (M) variance (S) and input-output (C) covariance of the squashed
         control input
    '''
    k = tf.shape(m)[1]
    if max_action is None:
        max_action = tf.ones((1, k), dtype=float_type)  # squashes in [-1,1] by default
    else:
        max_action = max_action * tf.ones((1, k), dtype=float_type)

    M = max_action * tf.exp(-tf.diag_part(s) / 2) * tf.sin(m)

    lq = -(tf.diag_part(s)[:, None] + tf.diag_part(s)[None, :]) / 2
    q = tf.exp(lq)
    S = (tf.exp(lq + s) - q) * tf.cos(tf.transpose(m) - m) \
        - (tf.exp(lq - s) - q) * tf.cos(tf.transpose(m) + m)
    S = max_action * tf.transpose(max_action) * S / 2

    C = max_action * tf.diag(tf.exp(-tf.diag_part(s) / 2) * tf.cos(m))
    return M, S, tf.reshape(C, shape=[k, k])


class LinearController(gpflow.Parameterized):
    def __init__(self, state_dim, control_dim, max_action=None, trainable=True):
        gpflow.Parameterized.__init__(self)
        self.W = gpflow.Param(np.random.rand(control_dim, state_dim), trainable=trainable)
        self.b = gpflow.Param(np.random.rand(1, control_dim), trainable=trainable)
        self.max_action = max_action

    @gpflow.params_as_tensors
    def compute_action(self, m, s, squash=True):
        '''
        Simple affine action:  M <- W(m-t) - b
        IN: mean (m) and variance (s) of the state
        OUT: mean (M) and variance (S) of the action
        '''
        M = m @ tf.transpose(self.W) + self.b  # mean output
        S = self.W @ s @ tf.transpose(self.W)  # output variance
        V = tf.transpose(self.W)  # input output covariance
        if squash:
            M, S, V2 = squash_sin(M, S, self.max_action)
            V = V @ V2
        return M, S, V

    def randomize(self):
        mean = 0;
        sigma = 1
        self.W.assign(mean + sigma * np.random.normal(size=self.W.shape))
        self.b.assign(mean + sigma * np.random.normal(size=self.b.shape))


def ControllerInverted(M=0.5, m=0.5, l=0.6, b=0.1):
    # reference http://ctms.engin.umich.edu/CTMS/index.php?example=InvertedPendulum&section=SystemModeling
    # M = mass of cart
    # m = mass of pendulum
    # l = length of pendulum
    # b = coefficient of friction of cart

    g = 9.82
    I = 1/12 * m * l**2
    r = l/2
    p = I * (M+m) + M * m * r**2

    A = np.array([[0, 1,                          0,                      0],
                  [0, -(I + m * r**2) * b / p,    (m**2 * g * r**2) / p,  0],
                  [0, 0,                          0,                      1],
                  [0, -(m*r*b)/p,                 m*g*r*(M+m)/p,          0]])
    
    B = np.array([[0],
                  [(I+m*r**2)/p],
                  [0],
                  [m*r/p]])

    return A, B

def ControllerSwingUp(m=1, l=1, b=0.1):
    # m = mass of pendulum
    # l = length of pendulum
    # b = coefficient of friction of pendulum

    g = 9.82
    I = 1/12 * m * l**2
    p = 1/4 * m * l**2 + I
    
    # using x to approximate sin(x)
    A = np.array([[-b/p,    -1/2 * m * l * g],
                  [1,       0]])
    
    B = np.array([[1/p],
                  [0]])

    return A, B


class LinearControllerIPTest(LinearController):
    def __init__(self, A, B, max_action=None, trainable=False):
        super(LinearControllerIPTest, self).__init__(1, 1, max_action=max_action, trainable=trainable)
        self.A = A
        self.B = B
        # control_dim = 1
        # state_dim = len(self.A)

        assert len(self.A) == 2 or len(self.A) == 4, "state_dim wrong?"
        if len(self.A) == 2:
            self.Q = np.array([[1, 0],
                               [0, 0]])
        elif len(self.A) == 4:
            self.Q = np.array([[1, 0, 0, 0],
                               [0, 0, 0, 0],
                               [0, 0, 1, 0],
                               [0, 0, 0, 0]])
        
        self.R = 1

        self.K, _, _ = control.lqr(self.A, self.B, self.Q, self.R)
        print(type(self.K))

        self.W = gpflow.Param(np.array(self.K), trainable=trainable)
        print(self.W)


class FakeGPR(gpflow.Parameterized):
    def __init__(self, X, Y, kernel):
        gpflow.Parameterized.__init__(self)
        self.X = gpflow.Param(X)
        self.Y = gpflow.Param(Y)

        self.kern = kernel
        self.likelihood = gpflow.likelihoods.Gaussian()


class RbfController(MGPR):
    '''
    An RBF Controller implemented as a deterministic GP
    See Deisenroth et al 2015: Gaussian Processes for Data-Efficient Learning in Robotics and Control
    Section 5.3.2.
    '''

    def __init__(self, state_dim, control_dim, num_basis_functions, max_action=None):
        MGPR.__init__(self,
                      np.random.randn(num_basis_functions, state_dim),
                      0.1 * np.random.randn(num_basis_functions, control_dim)
                      )
        for model in self.models:
            model.kern.variance = 1.0
            model.kern.variance.trainable = False
            self.max_action = max_action

    def create_models(self, X, Y):
        self.models = gpflow.params.ParamList([])
        for i in range(self.num_outputs):
            kern = gpflow.kernels.RBF(input_dim=X.shape[1], ARD=True)
            self.models.append(FakeGPR(X, Y[:, i:i + 1], kern))

    def compute_action(self, m, s, squash=True):
        '''
        RBF Controller. See Deisenroth's Thesis Section
        IN: mean (m) and variance (s) of the state
        OUT: mean (M) and variance (S) of the action
        '''
        iK, beta = self.calculate_factorizations()
        M, S, V = self.predict_given_factorizations(m, s, 0.0 * iK, beta)
        S = S - tf.diag(self.variance - 1e-6)
        if squash:
            M, S, V2 = squash_sin(M, S, self.max_action)
            V = V @ V2
        return M, S, V

    def randomize(self):
        print("Randomising controller")
        for m in self.models:
            mean = 0;
            sigma = 0.1
            m.X.assign(mean + sigma * np.random.normal(size=m.X.shape))
            m.Y.assign(mean + sigma * np.random.normal(size=m.Y.shape))
            mean = 1;
            sigma = 0.1
            m.kern.lengthscales.assign(mean + sigma * np.random.normal(size=m.kern.lengthscales.shape))


class CombinedController(gpflow.Parameterized):
    '''
    An RBF Controller implemented as a deterministic GP
    See Deisenroth et al 2015: Gaussian Processes for Data-Efficient Learning in Robotics and Control
    Section 5.3.2.
    '''

    def __init__(self, state_dim, control_dim, num_basis_functions, controller_location=None, max_action=None):
        gpflow.Parameterized.__init__(self)
        if controller_location == None:
            controller_location = np.zeros((1, state_dim))
        self.rbc_controller = RbfController(state_dim, control_dim, num_basis_functions, max_action)
        self.linear_controller = LinearController(state_dim, control_dim, max_action)
        self.a = gpflow.Param(controller_location, trainable=False)
        self.S = gpflow.Param(np.random.randn(3, 1) * np.identity(3),
                              transform=Squeeze()(transforms.DiagMatrix(state_dim))(transforms.positive))
        self.zeta = gpflow.Param(0.5, transform=transforms.positive)
        self.max_action = max_action

    def compute_ratio(self, x):
        '''
        Compute the ratio of the linear controller
        '''
        r = (x - self.a.parameter_tensor) @ self.S.constrained_tensor @ tf.transpose(x - self.a.parameter_tensor)
        ratio = -1 / math.pi * tf.math.atan2(- r * self.zeta.constrained_tensor, (1 - tf.math.pow(r, 2)))
        return ratio

    def compute_action(self, m, s, squash=True):
        '''
        RBF Controller. See Deisenroth's Thesis Section
        IN: mean (m) and variance (s) of the state
        OUT: mean (M) and variance (S) of the action
        '''
        r = self.compute_ratio(m)
        M1, S1, V1 = self.linear_controller.compute_action(m, s, False)
        M2, S2, V2 = self.rbc_controller.compute_action(m, s, False)
        M = (1 - r) * M1 + r * M2
        S = (1 - r) * S1 + r * S2 + (1 - r) * (M1 - M) @ tf.transpose(M1 - M) + r * (M2 - M) @ tf.transpose(M2 - M)
        V = (1 - r) * V1 + r * V2
        if squash:
            M, S, V2 = squash_sin(M, S, self.max_action)
            V = V @ V2
        return M, S, V

    def randomize(self):
        self.rbc_controller.randomize()
        self.linear_controller.randomize()
