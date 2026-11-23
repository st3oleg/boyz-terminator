"""Five USB webcam exposure presets and V4L2 control range handling."""

import re


# exposure_time_absolute is measured in 100 microsecond units by V4L2.
# At 15 fps, 600 corresponds to 60 ms, below the roughly 67 ms frame interval.
CAMERA_IMAGE_PRESETS = {
    "night_plus": {"exposure": 600, "gain": 30, "label": "Notturno+"},
    "night": {"exposure": 250, "gain": 15, "label": "Notturno"},
    "balanced": {"exposure": 80, "gain": 0, "label": "Bilanciato"},
    "daylight": {"exposure": 40, "gain": 0, "label": "Diurno"},
    "sunlight": {"exposure": 5, "gain": 0, "label": "Sole forte"},
}


def fit_control_to_range(list_ctrls_output, control_name, requested):
    """Clamp and align a setting to the range reported by this V4L2 device."""
    line = next(
        (line for line in list_ctrls_output.splitlines()
         if re.match(rf"\s*{re.escape(control_name)}\b", line)),
        "",
    )
    fields = {name: int(value) for name, value in re.findall(r"\b(min|max|step)=(-?\d+)", line)}
    if not {"min", "max", "step"} <= fields.keys() or fields["step"] <= 0:
        return requested
    minimum, maximum, step = fields["min"], fields["max"], fields["step"]
    clipped = max(minimum, min(maximum, requested))
    return minimum + ((clipped - minimum) // step) * step


def current_control_value(get_ctrls_output, control_name):
    """Read a value returned by v4l2-ctl --get-ctrl, if present."""
    match = re.search(
        rf"(?m)^\s*{re.escape(control_name)}\s*:\s*(-?\d+)\s*$",
        get_ctrls_output,
    )
    return int(match.group(1)) if match else None
