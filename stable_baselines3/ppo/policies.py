# This file is here just to define MlpPolicy/CnnPolicy
# that work for PPO
from stable_baselines3.common.policies import (
    ActorCriticCnnPolicy,
    RecurrentActorCriticPolicy,
    ActorCriticPolicy,
    MultiInputActorCriticPolicy,
    register_policy,
)

MlpPolicy = ActorCriticPolicy
CnnPolicy = ActorCriticCnnPolicy
MultiInputPolicy = MultiInputActorCriticPolicy
LstmPolicy = RecurrentActorCriticPolicy

register_policy("MlpPolicy", ActorCriticPolicy)
register_policy("CnnPolicy", ActorCriticCnnPolicy)
register_policy("MultiInputPolicy", MultiInputPolicy)
register_policy("LstmPolicy", LstmPolicy)
