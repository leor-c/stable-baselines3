import io
import os
import pathlib
import warnings
from copy import deepcopy

import gym
import numpy as np
import pytest
import torch as th

from stable_baselines3 import A2C, DDPG, DQN, PPO, SAC, TD3
from stable_baselines3.common.base_class import BaseAlgorithm
from stable_baselines3.common.identity_env import FakeImageEnv, IdentityEnv, IdentityEnvBox
from stable_baselines3.common.save_util import load_from_pkl, open_path, save_to_pkl
from stable_baselines3.common.utils import get_device
from stable_baselines3.common.vec_env import DummyVecEnv

MODEL_LIST = [PPO, A2C, TD3, SAC, DQN, DDPG]


def select_env(model_class: BaseAlgorithm) -> gym.Env:
    """
    Selects an environment with the correct action space as DQN only supports discrete action space
    """
    if model_class == DQN:
        return IdentityEnv(10)
    else:
        return IdentityEnvBox(10)


@pytest.mark.parametrize("model_class", MODEL_LIST)
def test_save_load(tmp_path, model_class):
    """
    Test if 'save' and 'load' saves and loads model correctly
    and if 'load_parameters' and 'get_policy_parameters' work correctly

    ''warning does not test function of optimizer parameter load

    :param model_class: (BaseAlgorithm) A RL model
    """

    env = DummyVecEnv([lambda: select_env(model_class)])

    # create model
    model = model_class("MlpPolicy", env, policy_kwargs=dict(net_arch=[16]), verbose=1)
    model.learn(total_timesteps=500, eval_freq=250)

    env.reset()
    observations = np.concatenate([env.step([env.action_space.sample()])[0] for _ in range(10)], axis=0)

    # Get dictionary of current parameters
    params = deepcopy(model.policy.state_dict())

    # Modify all parameters to be random values
    random_params = dict((param_name, th.rand_like(param)) for param_name, param in params.items())

    # Update model parameters with the new random values
    model.policy.load_state_dict(random_params)

    new_params = model.policy.state_dict()
    # Check that all params are different now
    for k in params:
        assert not th.allclose(params[k], new_params[k]), "Parameters did not change as expected."

    params = new_params

    # get selected actions
    selected_actions, _ = model.predict(observations, deterministic=True)

    # Check
    model.save(tmp_path / "test_save.zip")
    del model

    # Check if the model loads as expected for every possible choice of device:
    for device in ["auto", "cpu", "cuda", th.device("cpu"), th.device("cuda")]:
        model = model_class.load(str(tmp_path / "test_save.zip"), env=env, device=device)

        # check if the model was loaded to the correct device
        assert model.device.type == get_device(device).type

        # check if params are still the same after load
        new_params = model.policy.state_dict()

        # Check that all params are the same as before save load procedure now
        for key in params:
            assert th.allclose(params[key], new_params[key]), "Model parameters not the same after save and load."

        # check if model still selects the same actions
        new_selected_actions, _ = model.predict(observations, deterministic=True)
        assert np.allclose(selected_actions, new_selected_actions, 1e-4)

        # check if learn still works
        model.learn(total_timesteps=1000, eval_freq=500)

        del model

    # clear file from os
    os.remove(tmp_path / "test_save.zip")


@pytest.mark.parametrize("model_class", MODEL_LIST)
def test_set_env(model_class):
    """
    Test if set_env function does work correct
    :param model_class: (BaseAlgorithm) A RL model
    """

    # use discrete for DQN
    env = DummyVecEnv([lambda: select_env(model_class)])
    env2 = DummyVecEnv([lambda: select_env(model_class)])
    env3 = select_env(model_class)

    # create model
    model = model_class("MlpPolicy", env, policy_kwargs=dict(net_arch=[16]))
    # learn
    model.learn(total_timesteps=1000, eval_freq=500)

    # change env
    model.set_env(env2)
    # learn again
    model.learn(total_timesteps=1000, eval_freq=500)

    # change env test wrapping
    model.set_env(env3)
    # learn again
    model.learn(total_timesteps=1000, eval_freq=500)


@pytest.mark.parametrize("model_class", MODEL_LIST)
def test_exclude_include_saved_params(tmp_path, model_class):
    """
    Test if exclude and include parameters of save() work

    :param model_class: (BaseAlgorithm) A RL model
    """
    env = DummyVecEnv([lambda: select_env(model_class)])

    # create model, set verbose as 2, which is not standard
    model = model_class("MlpPolicy", env, policy_kwargs=dict(net_arch=[16]), verbose=2)

    # Check if exclude works
    model.save(tmp_path / "test_save", exclude=["verbose"])
    del model
    model = model_class.load(str(tmp_path / "test_save.zip"))
    # check if verbose was not saved
    assert model.verbose != 2

    # set verbose as something different then standard settings
    model.verbose = 2
    # Check if include works
    model.save(tmp_path / "test_save", exclude=["verbose"], include=["verbose"])
    del model
    model = model_class.load(str(tmp_path / "test_save.zip"))
    assert model.verbose == 2

    # clear file from os
    os.remove(tmp_path / "test_save.zip")


@pytest.mark.parametrize("model_class", [SAC, TD3, DQN])
def test_save_load_replay_buffer(tmp_path, model_class):
    path = pathlib.Path(tmp_path / "logs/replay_buffer.pkl")
    path.parent.mkdir(exist_ok=True, parents=True)  # to not raise a warning
    model = model_class("MlpPolicy", select_env(model_class), buffer_size=1000)
    model.learn(500)
    old_replay_buffer = deepcopy(model.replay_buffer)
    model.save_replay_buffer(path)
    model.replay_buffer = None
    model.load_replay_buffer(path)

    assert np.allclose(old_replay_buffer.observations, model.replay_buffer.observations)
    assert np.allclose(old_replay_buffer.actions, model.replay_buffer.actions)
    assert np.allclose(old_replay_buffer.rewards, model.replay_buffer.rewards)
    assert np.allclose(old_replay_buffer.dones, model.replay_buffer.dones)

    # test extending replay buffer
    model.replay_buffer.extend(
        old_replay_buffer.observations,
        old_replay_buffer.observations,
        old_replay_buffer.actions,
        old_replay_buffer.rewards,
        old_replay_buffer.dones,
    )


@pytest.mark.parametrize("model_class", [DQN, SAC, TD3])
@pytest.mark.parametrize("optimize_memory_usage", [False, True])
def test_warn_buffer(recwarn, model_class, optimize_memory_usage):
    """
    When using memory efficient replay buffer,
    a warning must be emitted when calling `.learn()`
    multiple times.
    See https://github.com/DLR-RM/stable-baselines3/issues/46
    """
    # remove gym warnings
    warnings.filterwarnings(action="ignore", category=DeprecationWarning)
    warnings.filterwarnings(action="ignore", category=UserWarning, module="gym")

    model = model_class(
        "MlpPolicy",
        select_env(model_class),
        buffer_size=100,
        optimize_memory_usage=optimize_memory_usage,
        policy_kwargs=dict(net_arch=[64]),
        learning_starts=10,
    )

    model.learn(150)

    model.learn(150, reset_num_timesteps=False)

    # Check that there is no warning
    assert len(recwarn) == 0

    model.learn(150)

    if optimize_memory_usage:
        assert len(recwarn) == 1
        warning = recwarn.pop(UserWarning)
        assert "The last trajectory in the replay buffer will be truncated" in str(warning.message)
    else:
        assert len(recwarn) == 0


@pytest.mark.parametrize("model_class", MODEL_LIST)
@pytest.mark.parametrize("policy_str", ["MlpPolicy", "CnnPolicy"])
def test_save_load_policy(tmp_path, model_class, policy_str):
    """
    Test saving and loading policy only.

    :param model_class: (BaseAlgorithm) A RL model
    :param policy_str: (str) Name of the policy.
    """
    kwargs = {}
    if policy_str == "MlpPolicy":
        env = select_env(model_class)
    else:
        if model_class in [SAC, TD3, DQN]:
            # Avoid memory error when using replay buffer
            # Reduce the size of the features
            kwargs = dict(buffer_size=250)
        env = FakeImageEnv(screen_height=40, screen_width=40, n_channels=2, discrete=model_class == DQN)

    env = DummyVecEnv([lambda: env])

    # create model
    model = model_class(policy_str, env, policy_kwargs=dict(net_arch=[16]), verbose=1, **kwargs)
    model.learn(total_timesteps=500, eval_freq=250)

    env.reset()
    observations = np.concatenate([env.step([env.action_space.sample()])[0] for _ in range(10)], axis=0)

    policy = model.policy
    policy_class = policy.__class__
    actor, actor_class = None, None
    if model_class in [SAC, TD3]:
        actor = policy.actor
        actor_class = actor.__class__

    # Get dictionary of current parameters
    params = deepcopy(policy.state_dict())

    # Modify all parameters to be random values
    random_params = dict((param_name, th.rand_like(param)) for param_name, param in params.items())

    # Update model parameters with the new random values
    policy.load_state_dict(random_params)

    new_params = policy.state_dict()
    # Check that all params are different now
    for k in params:
        assert not th.allclose(params[k], new_params[k]), "Parameters did not change as expected."

    params = new_params

    # get selected actions
    selected_actions, _ = policy.predict(observations, deterministic=True)
    # Should also work with the actor only
    if actor is not None:
        selected_actions_actor, _ = actor.predict(observations, deterministic=True)

    # Save and load policy
    policy.save(tmp_path / "policy.pkl")
    # Save and load actor
    if actor is not None:
        actor.save(tmp_path / "actor.pkl")

    del policy, actor

    policy = policy_class.load(tmp_path / "policy.pkl")
    if actor_class is not None:
        actor = actor_class.load(tmp_path / "actor.pkl")

    # check if params are still the same after load
    new_params = policy.state_dict()

    # Check that all params are the same as before save load procedure now
    for key in params:
        assert th.allclose(params[key], new_params[key]), "Policy parameters not the same after save and load."

    # check if model still selects the same actions
    new_selected_actions, _ = policy.predict(observations, deterministic=True)
    assert np.allclose(selected_actions, new_selected_actions, 1e-4)

    if actor_class is not None:
        new_selected_actions_actor, _ = actor.predict(observations, deterministic=True)
        assert np.allclose(selected_actions_actor, new_selected_actions_actor, 1e-4)
        assert np.allclose(selected_actions_actor, new_selected_actions, 1e-4)

    # clear file from os
    os.remove(tmp_path / "policy.pkl")
    if actor_class is not None:
        os.remove(tmp_path / "actor.pkl")


@pytest.mark.parametrize("pathtype", [str, pathlib.Path])
def test_open_file_str_pathlib(tmp_path, pathtype):
    # check that suffix isn't added because we used open_path first
    with open_path(pathtype(f"{tmp_path}/t1"), "w") as fp1:
        save_to_pkl(fp1, "foo")
    assert fp1.closed
    with pytest.warns(None) as record:
        assert load_from_pkl(pathtype(f"{tmp_path}/t1")) == "foo"
    assert not record

    # test custom suffix
    with open_path(pathtype(f"{tmp_path}/t1.custom_ext"), "w") as fp1:
        save_to_pkl(fp1, "foo")
    assert fp1.closed
    with pytest.warns(None) as record:
        assert load_from_pkl(pathtype(f"{tmp_path}/t1.custom_ext")) == "foo"
    assert not record

    # test without suffix
    with open_path(pathtype(f"{tmp_path}/t1"), "w", suffix="pkl") as fp1:
        save_to_pkl(fp1, "foo")
    assert fp1.closed
    with pytest.warns(None) as record:
        assert load_from_pkl(pathtype(f"{tmp_path}/t1.pkl")) == "foo"
    assert not record

    # test that a warning is raised when the path doesn't exist
    with open_path(pathtype(f"{tmp_path}/t2.pkl"), "w") as fp1:
        save_to_pkl(fp1, "foo")
    assert fp1.closed
    with pytest.warns(None) as record:
        assert load_from_pkl(open_path(pathtype(f"{tmp_path}/t2"), "r", suffix="pkl")) == "foo"
    assert len(record) == 0

    with pytest.warns(None) as record:
        assert load_from_pkl(open_path(pathtype(f"{tmp_path}/t2"), "r", suffix="pkl", verbose=2)) == "foo"
    assert len(record) == 1

    fp = pathlib.Path(f"{tmp_path}/t2").open("w")
    fp.write("rubbish")
    fp.close()
    # test that a warning is only raised when verbose = 0
    with pytest.warns(None) as record:
        open_path(pathtype(f"{tmp_path}/t2"), "w", suffix="pkl", verbose=0).close()
        open_path(pathtype(f"{tmp_path}/t2"), "w", suffix="pkl", verbose=1).close()
        open_path(pathtype(f"{tmp_path}/t2"), "w", suffix="pkl", verbose=2).close()
    assert len(record) == 1


def test_open_file(tmp_path):

    # path must much the type
    with pytest.raises(TypeError):
        open_path(123, None, None, None)

    p1 = tmp_path / "test1"
    fp = p1.open("wb")

    # provided path must match the mode
    with pytest.raises(ValueError):
        open_path(fp, "r")
    with pytest.raises(ValueError):
        open_path(fp, "randomstuff")

    # test identity
    _ = open_path(fp, "w")
    assert _ is not None
    assert fp is _

    # Can't use a closed path
    with pytest.raises(ValueError):
        fp.close()
        open_path(fp, "w")

    buff = io.BytesIO()
    assert buff.writable()
    assert buff.readable() is ("w" == "w")
    _ = open_path(buff, "w")
    assert _ is buff
    with pytest.raises(ValueError):
        buff.close()
        open_path(buff, "w")
