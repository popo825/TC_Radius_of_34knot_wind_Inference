"""Display-only IR palette; never used as model input."""
from io import BytesIO
import numpy as np
from PIL import Image


def render_ir_png(patch):
    stops = np.array([170, 195, 215, 235, 255, 280, 310, 350])
    colors = np.array([[244, 109, 163], [155, 131, 234], [87, 192, 217], [202, 231, 237],
                       [120, 140, 153], [50, 67, 81], [15, 29, 42], [8, 18, 30]])
    data = np.nan_to_num(patch, nan=350)
    rgb = np.stack([np.interp(data, stops, colors[:, i]) for i in range(3)], -1).astype('uint8')
    rgb[~np.isfinite(patch)] = [255, 190, 70]
    out = BytesIO()
    Image.fromarray(rgb).resize((468, 468), Image.Resampling.NEAREST).save(out, format='PNG')
    return out.getvalue()
