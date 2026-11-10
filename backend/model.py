"""Inference architecture copied from Sep_LDL_test.ipynb; no training changes."""
from functools import lru_cache
from pathlib import Path
import hashlib
import os
import numpy as np
import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = Path(os.getenv('R34_MODEL_PATH', str(ROOT / 'TCR34_reference_DNN_test1_25MAE.pth')))
MEAN_K, STD_K = 236.54854, 26.703743


class HurricaneAlexNet_ReferenceDNN(nn.Module):
    def __init__(self, num_classes=59):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 64, 11, stride=4, padding=2), nn.LeakyReLU(.01, inplace=True),
            nn.MaxPool2d(3, stride=2), nn.BatchNorm2d(64),
            nn.Conv2d(64, 192, 5, padding=2), nn.LeakyReLU(.01, inplace=True),
            nn.MaxPool2d(3, stride=2), nn.BatchNorm2d(192),
            nn.Conv2d(192, 384, 3, padding=1), nn.LeakyReLU(.01, inplace=True),
            nn.Conv2d(384, 256, 3, padding=1), nn.LeakyReLU(.01, inplace=True),
            nn.Conv2d(256, 256, 3, padding=1), nn.LeakyReLU(.01, inplace=True),
            nn.MaxPool2d(3, stride=2), nn.AdaptiveAvgPool2d((3, 3)))
        self.classifier = nn.Sequential(nn.Flatten(), nn.Dropout(.5), nn.Linear(2304, 4096),
            nn.LeakyReLU(.01, inplace=True), nn.Dropout(.5), nn.Linear(4096, 4096),
            nn.LeakyReLU(.01, inplace=True), nn.Linear(4096, num_classes))

    def forward(self, x):
        return self.classifier(self.features(x))


@lru_cache(maxsize=1)
def load_model():
    # The notebook checkpoint includes NumPy arrays. Allow only the required types;
    # never fall back to unrestricted pickle / weights_only=False.
    from numpy.core.multiarray import _reconstruct
    allowed = [_reconstruct, np.ndarray, np.dtype, type(np.dtype('float32')), type(np.dtype('int64'))]
    with torch.serialization.safe_globals(allowed):
        checkpoint = torch.load(MODEL_PATH, map_location='cpu', weights_only=True)
    bins = np.asarray(checkpoint['bin_centers'], dtype=np.float32)
    if bins.shape != (59,) or not np.array_equal(bins, np.arange(10, 305, 5)):
        raise ValueError('Checkpoint bin centers do not match the expected 59 bins.')
    model = HurricaneAlexNet_ReferenceDNN()
    model.load_state_dict(checkpoint['model_state_dict'], strict=True)
    model.eval()
    digest = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
    return model, bins, digest


def predict(kelvin):
    image = np.asarray(kelvin, dtype=np.float32)
    if image.shape != (156, 156):
        raise ValueError('Expected a storm-centered 156 × 156 Kelvin grid.')
    finite = np.isfinite(image)
    if finite.mean() < .98:
        raise ValueError('More than 2% of the brightness-temperature grid is missing.')
    if not np.all((image[finite] >= 100) & (image[finite] <= 350)):
        raise ValueError('Brightness temperatures must be in Kelvin (100–350 K).')
    image = np.where(finite, image, 245.0)
    normalized = (image - MEAN_K) / STD_K
    model, bins, digest = load_model()
    with torch.inference_mode():
        probability = torch.softmax(model(torch.from_numpy(normalized.copy())[None, None]), -1)[0].numpy()
    return {'bins_nmi': bins.tolist(), 'probabilities': probability.tolist(),
            'mean_nmi': float(np.dot(probability, bins)), 'model_sha256': digest,
            'missing_fraction': float(1 - finite.mean()), 'ground_truth': None}
