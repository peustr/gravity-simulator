"""Compare values executed by Godot with the physics implementation."""
import numpy as np

import server
import world


def check(data):
    assert data['keys'] == list(world.TYPE_KEYS)
    assert data['port'] == server.DEFAULT_PORT
    assert data['layout'] == [server.HEADER_FLOATS, server.BODY_FLOATS, server.EVENT_FLOATS]
    assert data['presets'] == list(world.SCENARIOS)
    expected_ids = {key.upper(): value for key, value in world.TYPE_KEYS.items()}
    expected_ids.update({key: value for key, value in vars(world).items() if key.startswith('EV_')})
    assert data['ids'] == expected_ids
    np.testing.assert_allclose(data['masses'], list(world.DEFAULT_MASS.values()), rtol=1e-7)
    for kind, row in enumerate(data['radii']):
        np.testing.assert_allclose(row, [world.radius_for(kind, m) for m in data['samples']], rtol=1e-7)
    assert len(data['radii']) == len(world.TYPE_KEYS)
    print('Python/Godot contract checks PASSED')
