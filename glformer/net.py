from aug import CusTomFilterByRange, CusTomRandomFlip3D, CusTomGlobalScaling, CusTomGlobalRotation
from sample import SeqInferenceSampler
from track_evaluator import CustomWaymoTrackEvaluator
from env import CustomWDDataset
from glformer import glFormer


__all__ = [
    "CusTomFilterByRange", "CusTomRandomFlip3D", "CusTomGlobalScaling", "CusTomGlobalRotation",
    "SeqInferenceSampler", "CustomWaymoTrackEvaluator", "CustomWDDataset",
]


def build_model(self, config):
    model = glFormer(config)

    return model
