"""Load the SD-TCR checkpoint and estimate a radius distribution from Kelvin crops."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import hashlib
import os
import numpy as np
import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = Path(os.getenv('R34_MODEL_PATH', str(ROOT / 'SD_TCR_vgg_target_nae_dsm.pth')))
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


class HurricaneVGGCompact(nn.Module):
    """VGG target from Sep_SD_TCR_VGG_NAE_DSM_Colab.ipynb."""

    def __init__(self, num_classes=59):
        super().__init__()
        layers = []
        in_channels = 1
        for channels in (16, 32, 64, 96):
            for _ in range(2):
                layers.extend([
                    nn.Conv2d(in_channels, channels, 3, padding=1, bias=False),
                    nn.BatchNorm2d(channels),
                    nn.ReLU(inplace=True),
                ])
                in_channels = channels
            layers.append(nn.MaxPool2d(2))
        self.features = nn.Sequential(*layers)
        self.classifier = nn.Sequential(
            nn.AdaptiveAvgPool2d((3, 3)),
            nn.Flatten(),
            nn.Linear(96 * 3 * 3, 64),
            nn.ReLU(inplace=True),
            nn.Dropout(0.25),
            nn.Linear(64, num_classes),
        )

    def forward(self, image):
        return self.classifier(self.features(image))


@dataclass(frozen=True)
class LoadedModel:
    network: nn.Module
    bins: np.ndarray
    digest: str
    mean_k: float
    std_k: float


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
    architecture = checkpoint.get('architecture', 'alexnet_reference')
    if architecture == 'vgg_compact':
        network = HurricaneVGGCompact()
        mean_k, std_k = float(checkpoint['mean_k']), float(checkpoint['std_k'])
    elif architecture == 'alexnet_reference':
        network = HurricaneAlexNet_ReferenceDNN()
        mean_k = float(checkpoint.get('mean_k', MEAN_K))
        std_k = float(checkpoint.get('std_k', STD_K))
    else:
        raise ValueError(f'Unsupported checkpoint architecture: {architecture!r}.')
    if not np.isfinite([mean_k, std_k]).all() or std_k <= 0:
        raise ValueError('Checkpoint normalization requires a finite mean and positive standard deviation.')

    network.load_state_dict(checkpoint['model_state_dict'], strict=True)
    network.eval()
    with MODEL_PATH.open('rb') as weights:
        digest = hashlib.file_digest(weights, 'sha256').hexdigest()
    return LoadedModel(network, bins, digest, mean_k, std_k)


def predict(kelvin, *, center_lat=0.0):
    image = np.asarray(kelvin, dtype=np.float32)
    if image.shape != (156, 156):
        raise ValueError('Expected a storm-centered 156 × 156 Kelvin grid.')
    finite = np.isfinite(image)
    if finite.mean() < .98:
        raise ValueError('More than 2% of the brightness-temperature grid is missing.')
    if not np.all((image[finite] >= 100) & (image[finite] <= 350)):
        raise ValueError('Brightness temperatures must be in Kelvin (100–350 K).')
    image = np.where(finite, image, 245.0)
    # Reverse rows for Southern Hemisphere model inputs. Keep the source crop north-up.
    flipped = center_lat < 0
    if flipped:
        image = image[::-1, :]
    model = load_model()
    normalized = (image - model.mean_k) / model.std_k
    with torch.inference_mode():
        logits = model.network(torch.from_numpy(normalized.copy())[None, None])
        probability = torch.softmax(logits, dim=-1)[0].numpy()
    return {'bins_nmi': model.bins.tolist(), 'probabilities': probability.tolist(),
            'mean_nmi': float(np.dot(probability, model.bins)), 'model_sha256': model.digest,
            'normalization': {'mean_k': model.mean_k, 'std_k': model.std_k},
            'input_vertical_flip': flipped,
            'missing_fraction': float(1 - finite.mean()), 'ground_truth': None}
