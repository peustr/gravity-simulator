"""Validated, serialisable choices for the physical solver and its approximations."""
import math


DEFAULTS = dict(gravity='tracers', epsilon=1e-9, forecast_limit=20, escape_distance=15000.0)


def settings(value, partial=False):
    if not isinstance(value, dict) or set(value) - DEFAULTS.keys() or (not partial and value.keys() != DEFAULTS.keys()):
        raise ValueError('Invalid physics settings')
    result = DEFAULTS | value
    if result['gravity'] not in ('full', 'tracers'):
        raise ValueError('Gravity must be full or tracers')
    epsilon = result['epsilon']
    if type(epsilon) not in (int, float) or not math.isfinite(epsilon) or not 1e-12 <= epsilon <= 1e-6:
        raise ValueError('IAS15 epsilon must be between 1e-12 and 1e-6')
    limit = result['forecast_limit']
    if type(limit) is not int or not 0 <= limit <= 1321:
        raise ValueError('Forecast limit must be 0 (all bodies) or 1–1321')
    radius = result['escape_distance']
    if radius is not None and (type(radius) not in (int, float) or not math.isfinite(radius) or not 0 < radius <= 1e9):
        raise ValueError('Removal distance must be positive and finite, or null to disable removal')
    return result
