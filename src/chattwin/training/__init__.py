"""Optional training code. Importing contracts does not import torch or model SDKs."""

from .spec import TrainingSpec, validate_dataset

__all__ = ["TrainingSpec", "validate_dataset"]
